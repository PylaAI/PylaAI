import os
import threading

import cv2
import numpy as np
import onnxruntime as ort
from utils import load_toml_as_dict
import warnings

_dml_lock = threading.Lock()

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


def _normalize_yolo_output(raw_output):
    """
    Accepts either:
        outputs
        outputs[0]

    Supports common YOLO ONNX shapes:
        (1, 84, 8400)
        (1, 8400, 84)
        (84, 8400)
        (8400, 84)

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
    if prediction.shape[0] < prediction.shape[1] and prediction.shape[0] <= 256:
        prediction = prediction.T

    return prediction


def _postprocess_raw(raw_output, conf_tresh=0.6, iou_thresh=0.6):
    prediction = _normalize_yolo_output(raw_output)

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
    def __init__(self, model_path, ignore_classes=None, classes=None, input_size=(640, 640)):
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
        self.model, self.device = self.load_model()
        self.input_name = self.model.get_inputs()[0].name
        self._padded_img_buffer = np.full(
            (1, 3, self.input_size[0], self.input_size[1]),
            128.0 / 255.0,
            dtype=np.float32
        )

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
        return so

    def _cpu_session(self):
        return ort.InferenceSession(self.model_path, sess_options=self._session_options(False),
                                    providers=["CPUExecutionProvider"])

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
            model = ort.InferenceSession(self.model_path, sess_options=self._session_options(True),
                                         providers=[onnx_provider, "CPUExecutionProvider"])
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
        h, w = img.shape[:2]

        scale = min(self.input_size[0] / h, self.input_size[1] / w)
        new_w = int(w * scale)
        new_h = int(h * scale)

        resized_img = cv2.resize(
            img,
            (new_w, new_h),
            interpolation=cv2.INTER_LINEAR
        )

        img_float = resized_img.astype(np.float32, copy=True)
        np.multiply(img_float, 1.0 / 255.0, out=img_float)

        self._padded_img_buffer[0, 0, :new_h, :new_w] = img_float[:, :, 0]
        self._padded_img_buffer[0, 1, :new_h, :new_w] = img_float[:, :, 1]
        self._padded_img_buffer[0, 2, :new_h, :new_w] = img_float[:, :, 2]

        return self._padded_img_buffer, new_w, new_h

    def postprocess(self, raw_output, orig_img_shape, resized_shape, conf_tresh=0.6):
        detections = _postprocess_raw(
            raw_output,
            conf_tresh=conf_tresh,
            iou_thresh=0.6
        )

        orig_h, orig_w = orig_img_shape
        resized_w, resized_h = resized_shape

        scale_w = orig_w / resized_w
        scale_h = orig_h / resized_h

        results = []

        for det in detections:
            if len(det):
                det[:, 0] *= scale_w
                det[:, 1] *= scale_h
                det[:, 2] *= scale_w
                det[:, 3] *= scale_h
                results.append(det)

        return results

    def detect_objects(self, img, conf_tresh=0.6):
        orig_h, orig_w = img.shape[:2]

        preprocessed_img, resized_w, resized_h = self.preprocess_image(img)

        try:
            if self.device == "DmlExecutionProvider":
                with _dml_lock:
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
                self.input_name = self.model.get_inputs()[0].name
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
