import ast
import json
import os
import threading
import weakref
from collections import deque
from contextlib import contextmanager

from entity_model import decode_pose, read_layout
from model_input import uint8_input_model

import cv2
import numpy as np
import onnxruntime as ort
from utils import load_toml_as_dict
import warnings

# PYLA_FLOAT_MODEL_INPUT=1: give the models float32 input built on the CPU, as before model_input.py (for comparisons).
UINT8_MODEL_INPUT = os.environ.get("PYLA_FLOAT_MODEL_INPUT") != "1"


class GpuTurns:
    """One lock for every DirectML run in the process, handed out in turns instead of to whichever thread wakes first.

    Required: with per-session locks, 3 instances running at once made DirectML fail ("DmlFusedNode ... 80004005") and
    fall back to CPU. A plain Lock is not fair: under load one thread kept winning it (one instance ran 376 entity
    models/s while another got 87). Here waiting runs go first come, first served."""

    def __init__(self):
        self._condition = threading.Condition()
        self._busy = False
        self._waiting = deque()     # tickets in arrival order

    @contextmanager
    def turn(self):
        ticket = object()
        with self._condition:
            self._waiting.append(ticket)
            self._condition.wait_for(lambda: not self._busy and self._waiting[0] is ticket)
            self._waiting.popleft()
            self._busy = True
        try:
            yield
        finally:
            with self._condition:
                self._busy = False
                self._condition.notify_all()


_dml_lock = GpuTurns()
# Sessions shared by all instances (Detect._shared_session).
_sessions = weakref.WeakValueDictionary()
_sessions_lock = threading.Lock()
_cpu_arena = None       # True once the shared CPU arena is registered, False when this ORT cannot
_cpu_arena_lock = threading.Lock()  # not _sessions_lock: session factories run while _shared_session holds that one


def _shared_cpu_arena():
    """One CPU memory arena for every CPU session instead of one each. A session's arena keeps its peak for good and
    grows in powers of two; shared, CPU inference takes much less memory at the same speed (no arena at all saved
    more but made entity inference 38 % slower). Registered once."""
    global _cpu_arena
    with _cpu_arena_lock:
        if _cpu_arena is None:
            try:
                memory = ort.OrtMemoryInfo("Cpu", ort.OrtAllocatorType.ORT_ARENA_ALLOCATOR, 0, ort.OrtMemType.DEFAULT)
                # max memory 0 (none), extend strategy 0 (next power of two), default chunk sizes
                ort.create_and_register_allocator(memory, ort.OrtArenaCfg(0, 0, -1, -1))
                _cpu_arena = True
            except Exception as exc:
                print(f"Shared CPU memory arena unavailable ({exc}); each model keeps its own.")
                _cpu_arena = False
        return _cpu_arena

_TERRAIN_TILE_CLASSES = ['wall', 'bush', 'rope_fence', 'water', 'out_of_bounds']
_SEMANTIC_TILE_NAMES = dict(wall='wall', indestructible_wall='wall', fragile='wall',
                          bush='bush', rope_fence='rope_fence', water='water', out_of_bounds='out_of_bounds')

warnings.filterwarnings(
    "ignore",
    message=".*'pin_memory' argument is set as true but no accelerator is found.*",
    category=UserWarning
)


def _numpy_nms(boxes, scores, iou_threshold=0.6):
    if len(boxes) == 0:
        return np.array([], dtype=np.int32)

    x1 = boxes[:, 0]
    y1 = boxes[:, 1]
    x2 = boxes[:, 2]
    y2 = boxes[:, 3]

    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]

    keep = []

    while order.size > 0:
        i = order[0]
        keep.append(i)

        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)

        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)

        inds = np.where(iou <= iou_threshold)[0]
        order = order[inds + 1]

    return np.array(keep, dtype=np.int32)


def _normalize_yolo_output(raw_output, end2end=False):
    """
    Accepts either:
        outputs
        outputs[0]

    Supports common YOLO ONNX shapes:
        (1, 84, 8400)
        (1, 8400, 84)
        (84, 8400)
        (8400, 84)
        (1, 300, 6) for end-to-end models

    Returns:
        prediction with shape (num_boxes, num_channels)
    """

    if isinstance(raw_output, (list, tuple)):
        prediction = raw_output[0]
    else:
        prediction = raw_output

    prediction = np.asarray(prediction)

    if prediction.ndim == 3:
        prediction = prediction[0]

    if prediction.ndim != 2:
        raise ValueError(f"Unexpected YOLO output shape: {prediction.shape}")

    # YOLOv8 ONNX often gives (84, 8400), needs transpose to (8400, 84)
    if not end2end and prediction.shape[0] < prediction.shape[1] and prediction.shape[0] <= 256:
        prediction = prediction.T

    return prediction


def _postprocess_raw(raw_output, conf_tresh=0.6, iou_thresh=0.6, end2end=False):
    prediction = _normalize_yolo_output(raw_output, end2end=end2end)

    if end2end:
        # YOLO26 returns [x1, y1, x2, y2, confidence, class_id]; no extra NMS is needed.
        return [prediction[prediction[:, 4] >= conf_tresh].copy()]

    n_detections = prediction.shape[0]
    n_classes = prediction.shape[1] - 4

    if n_classes <= 0:
        return []

    boxes_cxcywh = prediction[:, :4]
    class_scores = prediction[:, 4:]

    class_ids = np.argmax(class_scores, axis=1)
    confidences = class_scores[np.arange(n_detections), class_ids]

    mask = confidences >= conf_tresh

    if not np.any(mask):
        return []

    boxes_cxcywh = boxes_cxcywh[mask]
    confidences = confidences[mask]
    class_ids = class_ids[mask]

    x1 = boxes_cxcywh[:, 0] - boxes_cxcywh[:, 2] / 2
    y1 = boxes_cxcywh[:, 1] - boxes_cxcywh[:, 3] / 2
    x2 = boxes_cxcywh[:, 0] + boxes_cxcywh[:, 2] / 2
    y2 = boxes_cxcywh[:, 1] + boxes_cxcywh[:, 3] / 2

    boxes_xyxy = np.stack([x1, y1, x2, y2], axis=1)

    results = []

    for cls in np.unique(class_ids):
        cls_mask = class_ids == cls

        cls_boxes = boxes_xyxy[cls_mask]
        cls_scores = confidences[cls_mask]

        keep = _numpy_nms(cls_boxes, cls_scores, iou_thresh)

        if len(keep) == 0:
            continue

        kept_boxes = cls_boxes[keep]
        kept_scores = cls_scores[keep]
        kept_cls = np.full((len(keep), 1), cls, dtype=np.float32)

        det = np.hstack(
            [
                kept_boxes,
                kept_scores.reshape(-1, 1),
                kept_cls,
            ]
        ).astype(np.float32, copy=False)

        results.append(det)

    return results


class Detect:
    keypoint_shape = ()

    def __init__(self, model_path, ignore_classes=None, classes=None, input_size=(640, 640), tile_size=54):
        threads_to_use = load_toml_as_dict("cfg/general_config.toml")['used_threads']

        def get_optimal_threads(max_limit=6):
            threads = os.cpu_count() or 1
            threads_amount = min(threads, max(2, threads // 2), max_limit)
            print(f"Detected {threads} CPU threads, using {threads_amount} threads.")
            return threads_amount

        self.optimal_threads_amount = get_optimal_threads() if threads_to_use == "auto" else max(1, int(threads_to_use))
        # Keep OpenCV's shared pool separate from ONNX inference threads.
        cv2.setNumThreads(max(1, int(os.environ.get("PYLA_OPENCV_THREADS", min(self.optimal_threads_amount, 4)))))
        self.preferred_device = str(
            load_toml_as_dict("cfg/general_config.toml").get("cpu_or_gpu", "auto") or "auto"
        ).strip().lower()
        self.model_path = model_path
        self.classes = classes
        self.ignore_classes = set(ignore_classes) if ignore_classes else set()
        self.input_size = input_size
        self.tile_size = max(1.0, float(tile_size))
        self.model, self.device = self.load_model()
        self._configure_input()
        layout = read_layout(self.model)
        self.keypoint_shape = layout['keypoints']
        self.end_to_end = layout['end_to_end']
        if layout['classes']:
            self.classes = layout['classes']
        if layout['input_size']:
            self.input_size = layout['input_size']
        metadata = self.model.get_modelmeta().custom_metadata_map
        self.end2end = metadata.get("end2end", "False").lower() == "true"
        self.semantic_outputs = {output.name: i for i, output in enumerate(self.model.get_outputs())}
        self.semantic = {'class_ids', 'confidence'}.issubset(self.semantic_outputs)
        if self.semantic:
            with open(os.path.splitext(model_path)[0] + '.json', encoding='utf-8') as file:
                manifest = json.load(file)
            self.semantic_names = [manifest['class_ids'][str(i)] for i in range(len(manifest['class_ids']))]
            self.input_size = (manifest['height'], manifest['width'])
            expected = [1, *self.input_size, 3] if self.input_u8 else [1, 3, *self.input_size]
            if self.model.get_inputs()[0].shape != expected:
                raise ValueError('Semantic model input size does not match its JSON manifest.')
            self.classes = list(_TERRAIN_TILE_CLASSES)
        if self.end2end and "names" in metadata:
            names = ast.literal_eval(metadata["names"])
            self.classes = [names[i] for i in range(len(names))]
        # Centred letterbox, grey 114 (end-to-end, semantic and pose models); the original models: bottom-right, 128.
        self.letterbox_center = bool(self.end2end or self.semantic or self.keypoint_shape)
        self.pad_byte = 114 if self.letterbox_center else 128
        self.pad_value = self.pad_byte / 255.0
        self._allocate_input_buffer()

    def _configure_input(self):
        """Input name and format of the current session: uint8 [1, H, W, 3] (model_input.uint8_input_model) or the
        model's own float [1, 3, H, W]."""
        model_input = self.model.get_inputs()[0]
        self.input_name = model_input.name
        self.input_u8 = model_input.type == "tensor(uint8)"

    def _allocate_input_buffer(self):
        """The letterboxed model input, reused for every frame; its padding is (re)filled by preprocess_image."""
        in_h, in_w = self.input_size
        if self.input_u8:
            self._padded_img_buffer = np.full((1, in_h, in_w, 3), self.pad_byte, dtype=np.uint8)
        else:
            self._padded_img_buffer = np.full((1, 3, in_h, in_w), self.pad_value, dtype=np.float32)
        self._last_size = None

    def _session_options(self, gpu):
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if gpu:
            # The GPU does the work; a large spinning CPU pool just burns cores.
            so.intra_op_num_threads = 1
            so.inter_op_num_threads = 1
            so.add_session_config_entry("session.intra_op.allow_spinning", "0")
            so.add_session_config_entry("session.inter_op.allow_spinning", "0")
            # Required by DirectML (no memory patterns, no parallel execution).
            so.enable_mem_pattern = False
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        else:
            so.intra_op_num_threads = self.optimal_threads_amount
            so.inter_op_num_threads = self.optimal_threads_amount
            if _shared_cpu_arena():
                so.add_session_config_entry("session.use_env_allocators", "1")
        return so

    def _create_session(self, sess_options, providers):
        """InferenceSession of the model taking the frame's bytes (model_input.uint8_input_model) when the model allows
        it, else of the model as it is."""
        wrapped = uint8_input_model(self.model_path) if UINT8_MODEL_INPUT else None
        if wrapped is not None:
            try:
                return ort.InferenceSession(wrapped[0], sess_options=sess_options, providers=providers)
            except Exception as exc:
                print(f"{os.path.basename(self.model_path)}: uint8 input unavailable ({exc}), using float input.")
        return ort.InferenceSession(self.model_path, sess_options=sess_options, providers=providers)

    def _shared_session(self, provider, factory):
        """One session per model, provider and thread setting for the whole process, shared by every instance
        (and by its CPU fallback): each costs a few hundred MB of RAM. Runs on one session are thread-safe on CPU and
        CUDA, and DirectML runs are serialised by _dml_lock anyway. A session is released once no Detect uses it."""
        key = (os.path.abspath(self.model_path), provider, self.optimal_threads_amount)
        with _sessions_lock:
            session = _sessions.get(key)
            if session is None:
                session = factory()
                _sessions[key] = session
            return session

    def _cpu_session(self):
        return self._shared_session("CPUExecutionProvider", lambda: self._create_session(
            self._session_options(False), ["CPUExecutionProvider"]))

    def load_model(self):
        available_providers = ort.get_available_providers()
        onnx_provider = "CPUExecutionProvider"
        if self.preferred_device == "gpu" or self.preferred_device == "auto":
            for candidate in ("CUDAExecutionProvider", "DmlExecutionProvider"):
                if candidate in available_providers:
                    onnx_provider = candidate
                    break
            else:
                print("Using CPU as no GPU provider found")

        if onnx_provider == "CPUExecutionProvider":
            return self._cpu_session(), onnx_provider

        try:
            model = self._shared_session(onnx_provider, lambda: self._create_session(
                self._session_options(True), [onnx_provider, "CPUExecutionProvider"]))
        except Exception as e:
            print(f"Failed to initialize GPU provider {onnx_provider}: {e}. Falling back to CPU.")
            return self._cpu_session(), "CPUExecutionProvider"

        # get_available_providers() only lists what the wheel was built with;
        # the session reports what was actually registered.
        active = model.get_providers()[0]
        if active != onnx_provider:
            print(f"{onnx_provider} was not usable on this machine, running on CPU instead.")
            return self._cpu_session(), "CPUExecutionProvider"

        print(f"Using GPU ({'CUDA' if active == 'CUDAExecutionProvider' else 'DirectML'})")
        return model, active

    def preprocess_image(self, img):
        """Letterbox a frame into the model input, written straight into the reused input buffer:
        (input, new_w, new_h). A uint8 input only takes the resized pixels; the model itself scales them to 0..1 and
        puts the channels first (model_input.py)."""
        h, w = img.shape[:2]
        in_h, in_w = self.input_size
        scale = min(in_h / h, in_w / w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        pad_x = pad_y = 0
        if self.letterbox_center:
            new_w, new_h = round(w * scale), round(h * scale)
            pad_x = (in_w - new_w) // 2
            pad_y = (in_h - new_h) // 2
        if self._last_size != (w, h):
            # Padding only changes with the source size; content always overwrites the same region.
            self._padded_img_buffer.fill(self.pad_byte if self.input_u8 else self.pad_value)
            self._last_size = (w, h)

        if self.input_u8:
            region = self._padded_img_buffer[0, pad_y:pad_y + new_h, pad_x:pad_x + new_w]
            resized_img = cv2.resize(img, (new_w, new_h), dst=region, interpolation=cv2.INTER_LINEAR)
            if not np.may_share_memory(resized_img, region):    # OpenCV could not write into the view
                region[...] = resized_img
            return self._padded_img_buffer, new_w, new_h

        resized_img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        # HWC uint8 -> CHW float32 scaled to [0, 1], written straight into the padded input in one pass.
        np.multiply(
            resized_img.transpose(2, 0, 1),
            np.float32(1.0 / 255.0),
            out=self._padded_img_buffer[0, :, pad_y:pad_y + new_h, pad_x:pad_x + new_w],
            casting="unsafe",
        )
        return self._padded_img_buffer, new_w, new_h

    def postprocess(self, raw_output, orig_img_shape, resized_shape, conf_tresh=0.6):
        if self.semantic:
            return self._semantic_tile_detections(raw_output, orig_img_shape, resized_shape, conf_tresh)

        if self.keypoint_shape:
            detections = decode_pose(raw_output, len(self.classes), self.keypoint_shape, conf_tresh,
                                     self.end_to_end, _numpy_nms, keep_points=False)
        else:
            detections = _postprocess_raw(
                raw_output,
                conf_tresh=conf_tresh,
                iou_thresh=0.6,
                end2end=self.end2end
            )

        orig_h, orig_w = orig_img_shape
        resized_w, resized_h = resized_shape

        scale_w = orig_w / resized_w
        scale_h = orig_h / resized_h

        results = []

        for det in detections:
            if len(det):
                if self.end2end or self.keypoint_shape:
                    det[:, [0, 2]] -= (self.input_size[1] - resized_w) // 2
                    det[:, [1, 3]] -= (self.input_size[0] - resized_h) // 2
                det[:, 0] *= scale_w
                det[:, 1] *= scale_h
                det[:, 2] *= scale_w
                det[:, 3] *= scale_h
                if self.end2end or self.keypoint_shape:
                    det[:, [0, 2]] = np.clip(det[:, [0, 2]], 0, orig_w)
                    det[:, [1, 3]] = np.clip(det[:, [1, 3]], 0, orig_h)
                results.append(det)

        return results

    def _semantic_tile_detections(self, raw_output, orig_img_shape, resized_shape, conf_tresh):
        """Convert transient semantic predictions to coarse boxes; gameplay only receives ordinary lists."""
        orig_h, orig_w = orig_img_shape
        new_w, new_h = resized_shape
        pad_x = (self.input_size[1] - new_w) // 2
        pad_y = (self.input_size[0] - new_h) // 2
        crop = (0, slice(pad_y, pad_y + new_h), slice(pad_x, pad_x + new_w))
        ids = raw_output[self.semantic_outputs['class_ids']][crop]
        confidence = raw_output[self.semantic_outputs['confidence']][crop]
        scale_x, scale_y = orig_w / new_w, orig_h / new_h
        step_x = max(1, int(self.tile_size / scale_x))
        step_y = max(1, int(self.tile_size / scale_y))
        rows = []

        for class_id, name in enumerate(self.semantic_names):
            tile_name = _SEMANTIC_TILE_NAMES.get(name)
            if tile_name is None:
                continue
            minimum = 0.0 if name == 'out_of_bounds' else max(
                conf_tresh, {'rope_fence': .65, 'water': .75}.get(name, .60))
            region = np.ascontiguousarray((ids == class_id) & (confidence >= minimum), dtype=np.uint8)
            if not region.any():
                continue
            if name != 'out_of_bounds':
                # Same small/weak-component rejection as the deployed semantic model.
                n, labels, stats, _ = cv2.connectedComponentsWithStats(region, connectivity=8)
                area = stats[:, cv2.CC_STAT_AREA]
                mean = np.bincount(labels.ravel(), weights=confidence.ravel(), minlength=n) / np.maximum(area, 1)
                keep = (area >= .0006 * new_w * new_h) & (mean >= .80)
                keep[0] = False
                region = keep[labels].astype(np.uint8)

            x0, y0, width, height = cv2.boundingRect(region)
            output_id = self.classes.index(tile_name)
            # Each occupied cell produces one bounded rectangle, rather than one box around an entire lake/wall.
            for y in range(y0 // step_y * step_y, y0 + height, step_y):
                for x in range(x0 // step_x * step_x, x0 + width, step_x):
                    cell = region[y:y + step_y, x:x + step_x]
                    bx, by, bw, bh = cv2.boundingRect(cell)
                    if not bw or not bh:
                        continue
                    score = float(confidence[y:y + step_y, x:x + step_x][cell > 0].mean())
                    rows.append([int((x + bx) * scale_x), int((y + by) * scale_y),
                                 min(orig_w, int(np.ceil((x + bx + bw) * scale_x))),
                                 min(orig_h, int(np.ceil((y + by + bh) * scale_y))), score, output_id])

        return [np.asarray(rows, dtype=np.float32).reshape(-1, 6)]

    def detect_objects(self, img, conf_tresh=0.6):
        orig_h, orig_w = img.shape[:2]

        preprocessed_img, resized_w, resized_h = self.preprocess_image(img)

        try:
            if self.device == "DmlExecutionProvider":
                with _dml_lock.turn():
                    outputs = self.model.run(
                        None,
                        {self.input_name: preprocessed_img}
                    )
            else:
                outputs = self.model.run(
                    None,
                    {self.input_name: preprocessed_img}
                )
        except Exception as e:
            if self.device != "CPUExecutionProvider":
                print(f"ONNX Runtime inference failed on {self.device}: {e}. Re-initializing model on CPU...")
                self.device = "CPUExecutionProvider"
                self.model = self._cpu_session()
                was_u8 = self.input_u8
                self._configure_input()
                if self.input_u8 != was_u8:
                    # The CPU session takes the other input format (never expected): convert this frame's input and
                    # build the next frames' in that format.
                    if self.input_u8:
                        preprocessed_img = np.ascontiguousarray(
                            np.rint(preprocessed_img * 255.0).clip(0, 255).astype(np.uint8).transpose(0, 2, 3, 1))
                    else:
                        preprocessed_img = np.ascontiguousarray(
                            preprocessed_img.transpose(0, 3, 1, 2)).astype(np.float32) * np.float32(1.0 / 255.0)
                    self._allocate_input_buffer()
                outputs = self.model.run(
                    None,
                    {self.input_name: preprocessed_img}
                )
            else:
                raise e

        detections = self.postprocess(
            outputs,
            (orig_h, orig_w),
            (resized_w, resized_h),
            conf_tresh
        )

        results = {}

        for detection in detections:
            for row in detection:
                x1, y1, x2, y2 = int(row[0]), int(row[1]), int(row[2]), int(row[3])
                class_id = int(row[5])

                if self.classes is None:
                    class_name = str(class_id)
                else:
                    if class_id < 0 or class_id >= len(self.classes):
                        print(
                            f"WARNING: class_id {class_id} is out of range "
                            f"(classes length: {len(self.classes)}). Detection ignored."
                        )
                        continue

                    class_name = self.classes[class_id]

                if class_id in self.ignore_classes or class_name in self.ignore_classes:
                    continue

                if class_name not in results:
                    results[class_name] = []

                results[class_name].append([x1, y1, x2, y2])

        return results
