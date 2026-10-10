"""Exact declared v2 proof shapes, independently of value-only canonical hashes."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from functools import lru_cache
from types import UnionType
from typing import Literal, Union, get_args, get_origin, get_type_hints


@lru_cache(maxsize=None)
def _fields(kind):
    hints = get_type_hints(kind)
    return tuple((field.name, hints[field.name]) for field in fields(kind))


def matches_shape(value, annotation):
    """The annotation comes from the fixed public proof, never a stored payload."""
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        return any(matches_shape(value, item) for item in arguments)
    if origin is Literal:
        return any(type(value) is type(item) and value == item for item in arguments)
    if origin is tuple:
        return (type(value) is tuple and len(arguments) == 2 and arguments[1] is Ellipsis
                and all(matches_shape(item, arguments[0]) for item in value))
    if origin is Mapping:
        return (isinstance(value, Mapping) and len(arguments) == 2
                and all(matches_shape(key, arguments[0]) and matches_shape(item, arguments[1])
                        for key, item in value.items()))
    if annotation in (type(None), str, bool, int):
        return type(value) is annotation
    if is_dataclass(annotation):
        return (type(value) is annotation and all(matches_shape(getattr(value, name), kind)
                for name, kind in _fields(annotation)))
    return False
