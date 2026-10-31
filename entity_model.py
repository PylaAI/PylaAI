"""Read entity-model metadata and decode box + ground-point YOLO pose exports."""
import ast

import numpy as np


def read_layout(session):
    metadata = session.get_modelmeta().custom_metadata_map
    names = ast.literal_eval(metadata.get('names', '{}'))
    classes = [names[i] for i in sorted(names)] if isinstance(names, dict) else list(names)
    keypoints = tuple(ast.literal_eval(metadata.get('kpt_shape', '()')))
    if keypoints and (len(keypoints) != 2 or keypoints[0] < 1 or keypoints[1] not in (2, 3)):
        raise ValueError(f'Unsupported entity keypoint shape: {keypoints}')
    shape = session.get_inputs()[0].shape
    size = tuple(shape[2:]) if len(shape) == 4 and all(isinstance(v, int) for v in shape[2:]) else None
    return dict(classes=classes, keypoints=keypoints, input_size=size,
                end_to_end=str(metadata.get('end2end', '')).lower() == 'true')


def decode_pose(raw_output, classes, keypoints, threshold, end_to_end, nms, keep_points=False):
    """Return rows [xyxy, score, class, optional keypoints]; keypoints never become class scores.

    Accept both the classic [1, 4 + classes + K*D, anchors] head and the NMS-free
    [1, detections, 6 + K*D] head. Only early access requests the trailing point columns.
    """
    raw = np.asarray(raw_output[0] if isinstance(raw_output, (list, tuple)) else raw_output)
    prediction = raw[0] if raw.ndim == 3 else raw
    channels = (6 if end_to_end else 4 + classes) + keypoints[0] * keypoints[1]
    if prediction.ndim != 2:
        raise ValueError(f'Unexpected pose output shape: {raw.shape}')
    if prediction.shape[1] != channels and prediction.shape[0] == channels:
        prediction = prediction.T
    if prediction.shape[1] != channels:
        raise ValueError(f'Pose output has {prediction.shape[1]} channels; expected {channels}')
    if end_to_end:
        rows = prediction[prediction[:, 4] >= threshold].astype(np.float32, copy=True)
    else:
        scores = prediction[:, 4:4 + classes]
        class_ids = scores.argmax(1)
        confidence = scores[np.arange(len(scores)), class_ids]
        accepted = confidence >= threshold
        selected = prediction[accepted]
        xywh = selected[:, :4]
        boxes = np.column_stack((xywh[:, 0] - xywh[:, 2] / 2, xywh[:, 1] - xywh[:, 3] / 2,
                                 xywh[:, 0] + xywh[:, 2] / 2, xywh[:, 1] + xywh[:, 3] / 2))
        rows = np.column_stack((boxes, confidence[accepted], class_ids[accepted], selected[:, 4 + classes:]))
        rows = rows.astype(np.float32, copy=False)
    rows = rows[np.isfinite(rows[:, :6]).all(1)]
    rows = rows[(rows[:, 2] > rows[:, 0]) & (rows[:, 3] > rows[:, 1])]
    results = []
    for class_id in np.unique(rows[:, 5]):
        group = rows[rows[:, 5] == class_id]
        if not end_to_end:
            group = group[nms(group[:, :4], group[:, 4], .6)]
        group = group[np.argsort(-group[:, 4], kind='stable')]
        results.append(group if keep_points else group[:, :6])
    return results
