"""Let an image model take the frame's own bytes: uint8 [1, H, W, 3] instead of float32 [1, 3, H, W] in 0..1.

Pyla's models (Ultralytics exports) take RGB scaled to 0..1, channels first. Building that tensor on the CPU (a
transpose and a multiply per pixel) and handing ORT four bytes per value cost ~1 ms per inference on DirectML, mostly
the upload of the 4x larger input (measured 2026-11-16 on an RTX 4070 laptop, input prep + run: entity 3.51 -> 2.51 ms,
terrain 5.27 -> 3.24 ms; a little faster on CPU too). uint8_input_model adds the same three steps in front of the
graph (Transpose on the bytes, Cast to float, Mul by 1/255: the multiply detect.py did, so the values are the same),
which the GPU runs, and replaces the graph's input with the uint8 one.

The model file is edited in memory at the protobuf wire level, so no onnx package is needed: every field of the model
is copied byte for byte except the graph's input list, and the new nodes go first in the graph's node list (ONNX keeps
nodes in topological order). Anything unexpected (another input layout, dynamic sizes, external weights) returns None
and the model is used as it is.
"""
import struct
from pathlib import Path

# ONNX TensorProto.DataType
_FLOAT, _UINT8 = 1, 2
# Field numbers (onnx.proto)
_MODEL_GRAPH = 7
_GRAPH_NODE, _GRAPH_INITIALIZER, _GRAPH_INPUT = 1, 5, 11
_VALUE_NAME, _VALUE_TYPE = 1, 2
_TYPE_TENSOR = 1
_TENSOR_TYPE_ELEM, _TENSOR_TYPE_SHAPE = 1, 2
_SHAPE_DIM = 1
_DIM_VALUE = 1
_TENSOR_DATA_LOCATION = 14
_EXTERNAL = 1

PREFIX = "pyla_u8_"


# ---- wire format ------------------------------------------------------------------------------------------------------

def _varint(data, pos):
    result = shift = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            return result, pos
        shift += 7


def _fields(data):
    """(field number, wire type, value, start, end) of each field of a message; value is an int (varint, fixed) or a
    memoryview (length-delimited). start:end spans the whole field, key included."""
    pos, end = 0, len(data)
    while pos < end:
        start = pos
        key, pos = _varint(data, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire == 1:
            value, pos = int.from_bytes(data[pos:pos + 8], "little"), pos + 8
        elif wire == 2:
            length, pos = _varint(data, pos)
            value, pos = data[pos:pos + length], pos + length
        elif wire == 5:
            value, pos = int.from_bytes(data[pos:pos + 4], "little"), pos + 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wire}")
        if pos > end:
            raise ValueError("truncated protobuf field")
        yield number, wire, value, start, pos


def _encode_varint(value):
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _key(number, wire):
    return _encode_varint(number << 3 | wire)


def _bytes_field(number, payload):
    return _key(number, 2) + _encode_varint(len(payload)) + payload


def _int_field(number, value):
    return _key(number, 0) + _encode_varint(value & 0xFFFFFFFFFFFFFFFF)


def _first(data, number):
    return next((value for n, _, value, _, _ in _fields(data) if n == number), None)


# ---- onnx messages ----------------------------------------------------------------------------------------------------

def _attribute_int(name, value):
    # AttributeProto: name 1, i 3, type 20 (INT = 2)
    return _bytes_field(1, name.encode()) + _int_field(3, value) + _int_field(20, 2)


def _attribute_ints(name, values):
    # ints 8 (repeated int64), type 20 (INTS = 7)
    return _bytes_field(1, name.encode()) + b"".join(_int_field(8, v) for v in values) + _int_field(20, 7)


def _node(op_type, inputs, outputs, name, attributes=()):
    # NodeProto: input 1, output 2, name 3, op_type 4, attribute 5
    return (b"".join(_bytes_field(1, i.encode()) for i in inputs) + b"".join(_bytes_field(2, o.encode()) for o in outputs)
            + _bytes_field(3, name.encode()) + _bytes_field(4, op_type.encode())
            + b"".join(_bytes_field(5, a) for a in attributes))


def _value_info(name, elem_type, dims):
    shape = b"".join(_bytes_field(_SHAPE_DIM, _int_field(_DIM_VALUE, d)) for d in dims)
    tensor_type = _int_field(_TENSOR_TYPE_ELEM, elem_type) + _bytes_field(_TENSOR_TYPE_SHAPE, shape)
    return _bytes_field(_VALUE_NAME, name.encode()) + _bytes_field(_VALUE_TYPE, _bytes_field(_TYPE_TENSOR, tensor_type))


def _scalar_float(name, value):
    # TensorProto: dims none (scalar), data_type 2, name 8, raw_data 9
    return _int_field(2, _FLOAT) + _bytes_field(8, name.encode()) + _bytes_field(9, struct.pack("<f", value))


def _input_layout(value_info):
    """(name, elem_type, dims) of a graph input; dims None when one is not a fixed number."""
    name = bytes(_first(value_info, _VALUE_NAME) or b"").decode()
    tensor = _first(_first(value_info, _VALUE_TYPE) or b"", _TYPE_TENSOR)
    if tensor is None:
        return name, None, None
    elem_type = _first(tensor, _TENSOR_TYPE_ELEM)
    dims = []
    for number, _, dim, _, _ in _fields(_first(tensor, _TENSOR_TYPE_SHAPE) or b""):
        if number == _SHAPE_DIM:
            value = _first(dim, _DIM_VALUE)
            if value is None:
                return name, elem_type, None
            dims.append(value)
    return name, elem_type, dims


def uint8_input_model(path):
    """(model bytes taking uint8 [1, H, W, 3], (H, W)) for an image model with one float [1, 3, H, W] input, else
    None (the model is then used unchanged)."""
    try:
        data = memoryview(Path(path).read_bytes())
        model = list(_fields(data))
        graph_fields = [f for f in model if f[0] == _MODEL_GRAPH]
        if len(graph_fields) != 1:
            return None
        graph_view = graph_fields[0][2]
        graph = list(_fields(graph_view))
        initializer_names = set()
        for number, _, value, _, _ in graph:
            if number == _GRAPH_INITIALIZER:
                if _first(value, _TENSOR_DATA_LOCATION) == _EXTERNAL:
                    return None     # weights in another file: the bytes alone would not load
                initializer_names.add(bytes(_first(value, 8) or b"").decode())
        # Old exports also list initializers as graph inputs: the image is the input that is not one.
        inputs = [(i, value) for i, (number, _, value, _, _) in enumerate(graph) if number == _GRAPH_INPUT
                  and bytes(_first(value, _VALUE_NAME) or b"").decode() not in initializer_names]
        if len(inputs) != 1:
            return None
        index, value_info = inputs[0]
        name, elem_type, dims = _input_layout(value_info)
        if elem_type != _FLOAT or dims is None or len(dims) != 4 or dims[0] != 1 or dims[1] != 3:
            return None
        height, width = dims[2], dims[3]
        if any(name.startswith(PREFIX) for name in initializer_names):
            return None     # already has nodes of ours (never expected)

        u8, chw, as_float, scale = PREFIX + "input", PREFIX + "chw", PREFIX + "float", PREFIX + "scale"
        nodes = [_node("Transpose", [u8], [chw], PREFIX + "transpose", [_attribute_ints("perm", [0, 3, 1, 2])]),
                 _node("Cast", [chw], [as_float], PREFIX + "cast", [_attribute_int("to", _FLOAT)]),
                 _node("Mul", [as_float, scale], [name], PREFIX + "scale_mul")]
        parts = [_bytes_field(_GRAPH_NODE, node) for node in nodes]
        for i, (number, _, _, start, end) in enumerate(graph):
            if i == index:
                parts.append(_bytes_field(_GRAPH_INPUT, _value_info(u8, _UINT8, [1, height, width, 3])))
            else:
                parts.append(bytes(graph_view[start:end]))
        # Same constant as detect.py's float path: np.float32(1.0 / 255.0).
        parts.append(_bytes_field(_GRAPH_INITIALIZER, _scalar_float(scale, 1.0 / 255.0)))
        new_graph = b"".join(parts)

        out = []
        for number, _, _, start, end in model:
            out.append(_bytes_field(_MODEL_GRAPH, new_graph) if number == _MODEL_GRAPH else bytes(data[start:end]))
        return b"".join(out), (height, width)
    except (OSError, ValueError, IndexError, UnicodeDecodeError):
        return None
