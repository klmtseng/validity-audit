from __future__ import annotations

from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from validity_audit.schemas import SCHEMA_FILES, load_schema, schema_bytes

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", sorted(SCHEMA_FILES))
def test_packaged_schema_matches_repository_contract(name: str) -> None:
    filename = SCHEMA_FILES[name]
    assert schema_bytes(name) == (ROOT / "schemas" / filename).read_bytes()


@pytest.mark.parametrize("name", sorted(SCHEMA_FILES))
def test_packaged_schema_is_valid_draft_2020_12(name: str) -> None:
    schema = load_schema(name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(schema)
