"""Load and validate the versioned JSON Schemas shipped in the wheel."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

SCHEMA_FILES = {
    "task_contract": "task_contract.schema.json",
    "attestation": "attestation.schema.json",
    "reviewer_output": "reviewer_output.schema.json",
}
FORMAT_CHECKER = FormatChecker()


class SchemaValidationError(ValueError):
    """Raised when a runtime document does not satisfy its public schema."""


def schema_bytes(name: str) -> bytes:
    try:
        filename = SCHEMA_FILES[name]
    except KeyError as exc:
        raise KeyError(f"unknown schema {name!r}") from exc
    return resources.files("validity_audit.schema_files").joinpath(filename).read_bytes()


def load_schema(name: str) -> dict[str, Any]:
    return json.loads(schema_bytes(name))


def validate_document(instance: Any, schema_name: str) -> None:
    if "date-time" not in FORMAT_CHECKER.checkers:
        raise RuntimeError(
            "The date-time format checker is unavailable. Reinstall validity-audit "
            "with its declared runtime dependencies."
        )
    schema = load_schema(schema_name)
    try:
        Draft202012Validator(schema, format_checker=FORMAT_CHECKER).validate(instance)
    except ValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        raise SchemaValidationError(
            f"{schema_name} validation failed at {location}: {exc.message}"
        ) from exc
