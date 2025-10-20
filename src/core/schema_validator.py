from __future__ import annotations

from typing import Any, Dict, Type, TypeVar, Tuple, Optional

from pydantic import BaseModel, ValidationError
from jsonschema import Draft202012Validator
import json
import os


ModelT = TypeVar("ModelT", bound=BaseModel)


def validate_and_parse(model_cls: Type[ModelT], data: Any) -> ModelT:
    """Validate arbitrary data against a Pydantic model and return the instance.

    Raises ValidationError if invalid.
    """
    if issubclass(model_cls, BaseModel) is False:
        raise TypeError("model_cls must be a subclass of pydantic.BaseModel")
    return model_cls.model_validate(data)


def try_validate_and_parse(model_cls: Type[ModelT], data: Any) -> tuple[ModelT | None, list[str]]:
    """Validate data and return (model, errors). If invalid, model is None and errors are strings."""
    try:
        model = validate_and_parse(model_cls, data)
        return model, []
    except ValidationError as exc:
        return None, [str(e) for e in exc.errors()]  # type: ignore[return-value]


def json_schema(model_cls: Type[BaseModel]) -> Dict[str, Any]:
    """Return the JSON schema for a Pydantic model (useful for LLM JSON-mode prompts)."""
    return model_cls.model_json_schema()


def load_json_schema_from_file(path: str) -> Dict[str, Any]:
    """Load a JSON schema dict from a file path."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def try_validate_with_jsonschema(schema: Dict[str, Any], data: Any) -> Tuple[bool, Optional[list[str]]]:
    """Validate data against a JSON Schema dict. Returns (is_valid, errors)."""
    validator = Draft202012Validator(schema)
    errors = [e.message for e in validator.iter_errors(data)]
    return (len(errors) == 0, None if not errors else errors)


class SchemaValidator:
    """Simple wrapper class for JSON Schema validation."""
    
    def __init__(self, schema_path: str):
        """Load schema from file path."""
        self.schema = load_json_schema_from_file(schema_path)
    
    def validate(self, data: Any) -> Tuple[bool, Optional[list[str]]]:
        """Validate data against the loaded schema. Returns (is_valid, errors)."""
        return try_validate_with_jsonschema(self.schema, data)


__all__ = [
    "BaseModel",
    "ValidationError",
    "validate_and_parse",
    "try_validate_and_parse",
    "json_schema",
    "load_json_schema_from_file",
    "try_validate_with_jsonschema",
    "SchemaValidator",
]


