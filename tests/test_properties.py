# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Property-based tests for validate_asm_document and describe_asm."""

import json
import tempfile
from awslabs.allotrope_mcp_server.server import describe_asm, validate_asm_document
from hypothesis import given, settings
from hypothesis import strategies as st
from pathlib import Path

# Load MODEL_REFERENCE once at module level for use in describe_asm property tests.
_model_ref_path = Path(__file__).parent.parent / 'awslabs' / 'allotrope_mcp_server' / 'model_reference.json'
with open(_model_ref_path) as _f:
    MODEL_REFERENCE: dict = json.load(_f)


# A simple test schema: object with a required string "name" and integer "age".
TEST_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'type': 'object',
    'required': ['name', 'age'],
    'properties': {
        'name': {'type': 'string'},
        'age': {'type': 'integer'},
    },
    'additionalProperties': False,
}

# Strategy that generates documents valid against TEST_SCHEMA.
valid_documents = st.fixed_dictionaries({'name': st.text(min_size=0), 'age': st.integers()})


def _write_tmp_json(data: object, suffix: str = '.json') -> str:
    """Write data as JSON to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False)
    json.dump(data, f)
    f.close()
    return f.name


@given(doc=valid_documents)
@settings(max_examples=100)
def test_valid_documents_pass_validation(doc: dict) -> None:
    """Property 1: Valid documents pass validation."""
    doc_path = _write_tmp_json(doc)
    schema_path = _write_tmp_json(TEST_SCHEMA)
    try:
        result = validate_asm_document(doc_path, schema_path)
        assert result.is_valid is True, f'Expected valid but got errors: {result.errors}'
        assert result.errors == [], f'Expected no errors but got: {result.errors}'
        assert result.error_message is None
    finally:
        Path(doc_path).unlink(missing_ok=True)
        Path(schema_path).unlink(missing_ok=True)


# Strategy that generates documents invalid against TEST_SCHEMA.
_wrong_name_type = st.fixed_dictionaries(
    {'name': st.one_of(st.integers(), st.booleans(), st.none()), 'age': st.integers()}
)
_wrong_age_type = st.fixed_dictionaries(
    {'name': st.text(), 'age': st.one_of(st.text(min_size=1), st.booleans(), st.none())}
)
_missing_name = st.fixed_dictionaries({'age': st.integers()})
_missing_age = st.fixed_dictionaries({'name': st.text()})
_extra_property = st.fixed_dictionaries(
    {'name': st.text(), 'age': st.integers(), 'extra': st.text()}
)

invalid_documents = st.one_of(
    _wrong_name_type, _wrong_age_type, _missing_name, _missing_age, _extra_property
)


@given(doc=invalid_documents)
@settings(max_examples=100)
def test_invalid_document_errors_contain_required_fields(doc: dict) -> None:
    """Property 2: Invalid document errors contain required fields."""
    doc_path = _write_tmp_json(doc)
    schema_path = _write_tmp_json(TEST_SCHEMA)
    try:
        result = validate_asm_document(doc_path, schema_path)
        assert result.is_valid is False, f'Expected invalid but got valid for {doc}'
        assert len(result.errors) > 0, f'Expected errors but got none for {doc}'
        for err in result.errors:
            assert err.message, f'Error has empty message: {err}'
            assert err.validator, f'Error has empty validator: {err}'
    finally:
        Path(doc_path).unlink(missing_ok=True)
        Path(schema_path).unlink(missing_ok=True)


# Strategy for file paths that don't exist on disk.
_nonexistent_paths = st.text(
    alphabet=st.sampled_from('abcdefghijklmnopqrstuvwxyz0123456789_-'),
    min_size=1,
    max_size=60,
).map(lambda s: f'/tmp/nonexistent_{s}.json')


@given(bad_path=_nonexistent_paths)
@settings(max_examples=100)
def test_nonexistent_file_path_returns_identifying_error(bad_path: str) -> None:
    """Property 3: Non-existent file path returns identifying error."""
    # Use bad path as document, with a valid schema on disk
    schema_path = _write_tmp_json(TEST_SCHEMA)
    try:
        result = validate_asm_document(bad_path, schema_path)
        assert result.is_valid is False
        assert result.error_message is not None
        assert bad_path in result.error_message
    finally:
        Path(schema_path).unlink(missing_ok=True)

    # Use bad path as schema, with a valid document on disk
    doc_path = _write_tmp_json({'name': 'x', 'age': 1})
    try:
        result = validate_asm_document(doc_path, bad_path)
        assert result.is_valid is False
        assert result.error_message is not None
        assert bad_path in result.error_message
    finally:
        Path(doc_path).unlink(missing_ok=True)


# Strategy for strings that are NOT valid JSON.
_not_json = st.text(min_size=1).filter(lambda s: _is_not_json(s))


def _is_not_json(s: str) -> bool:
    """Return True if s is not valid JSON."""
    try:
        json.loads(s)
        return False
    except (json.JSONDecodeError, ValueError):
        return True


def _write_tmp_text(content: str, suffix: str = '.json') -> str:
    """Write raw text to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False)
    f.write(content)
    f.close()
    return f.name


@given(bad_json=_not_json)
@settings(max_examples=100)
def test_malformed_document_json_returns_document_specific_error(bad_json: str) -> None:
    """Property 4: Malformed document JSON returns document-specific error."""
    doc_path = _write_tmp_text(bad_json)
    schema_path = _write_tmp_json(TEST_SCHEMA)
    try:
        result = validate_asm_document(doc_path, schema_path)
        assert result.is_valid is False
        assert result.error_message is not None
        assert 'malformed json' in result.error_message.lower()
        assert doc_path in result.error_message
    finally:
        Path(doc_path).unlink(missing_ok=True)
        Path(schema_path).unlink(missing_ok=True)


@given(bad_json=_not_json)
@settings(max_examples=100)
def test_malformed_schema_json_returns_schema_specific_error(bad_json: str) -> None:
    """Property 5: Malformed schema JSON returns schema-specific error."""
    doc_path = _write_tmp_json({'name': 'x', 'age': 1})
    schema_path = _write_tmp_text(bad_json)
    try:
        result = validate_asm_document(doc_path, schema_path)
        assert result.is_valid is False
        assert result.error_message is not None
        assert 'malformed json' in result.error_message.lower()
        assert schema_path in result.error_message
    finally:
        Path(doc_path).unlink(missing_ok=True)
        Path(schema_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# describe_asm property tests
# ---------------------------------------------------------------------------


# Feature: describe-asm, Property 1: Metadata round-trip
# Validates: Requirements 1.2, 3.1, 3.2
@given(model_name=st.sampled_from(list(MODEL_REFERENCE.keys())))
@settings(max_examples=100)
async def test_describe_asm_round_trip(model_name: str) -> None:
    """Property 1: Metadata round-trip — parsed response equals original MODEL_REFERENCE entry."""
    result = await describe_asm(model_name)
    parsed = json.loads(result)
    assert parsed == MODEL_REFERENCE[model_name], (
        f'Round-trip mismatch for {model_name!r}: got {parsed!r}'
    )


# Feature: describe-asm, Property 2: Required fields present in response
# Validates: Requirements 1.4
@given(model_name=st.sampled_from(list(MODEL_REFERENCE.keys())))
@settings(max_examples=100)
async def test_describe_asm_required_fields(model_name: str) -> None:
    """Property 2: Required fields present — all four metadata fields exist in the response."""
    result = await describe_asm(model_name)
    parsed = json.loads(result)
    for field in ('description', 'asm_manifest', 'asm_json_schema', 'asm_data_instance_examples'):
        assert field in parsed, f'Missing field {field!r} for model {model_name!r}'


# Feature: describe-asm, Property 3: Invalid model name error response
# Validates: Requirements 2.1, 2.2
@given(model_name=st.text().filter(lambda s: s not in MODEL_REFERENCE))
@settings(max_examples=100)
async def test_describe_asm_invalid_name_error(model_name: str) -> None:
    """Property 3: Invalid model name error response — error contains name and valid_model_names."""
    result = await describe_asm(model_name)
    parsed = json.loads(result)
    assert 'error' in parsed, f'Expected "error" key for invalid name {model_name!r}'
    assert model_name in parsed['error'], (
        f'Error message does not contain {model_name!r}: {parsed["error"]!r}'
    )
    assert 'valid_model_names' in parsed, (
        f'Expected "valid_model_names" key for invalid name {model_name!r}'
    )
    assert parsed['valid_model_names'] == sorted(MODEL_REFERENCE.keys()), (
        f'valid_model_names mismatch for {model_name!r}'
    )
