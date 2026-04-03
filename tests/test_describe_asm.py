# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the describe_asm MCP tool."""

import json
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

from allotrope_mcp_server.server import describe_asm


# Load the real model_reference.json once for use in assertions
_PACKAGE_DIR = Path(__file__).parent.parent / 'allotrope_mcp_server'
_MODEL_REF_PATH = _PACKAGE_DIR / 'model_reference.json'

with open(_MODEL_REF_PATH) as _f:
    _MODEL_REFERENCE = json.load(_f)


class TestDescribeAsmValidModels:
    """Unit tests for describe_asm with valid model names (Requirements 1.1, 1.2, 1.4)."""

    async def test_absorbance_returns_all_required_fields(self):
        """Test that 'plate-reader' returns metadata with all four required fields."""
        result_json = await describe_asm('plate-reader')
        result = json.loads(result_json)

        assert 'error' not in result
        assert 'description' in result
        assert 'asm_manifest' in result
        assert 'asm_json_schema' in result
        assert 'asm_data_instance_examples' in result

    async def test_absorbance_metadata_matches_reference(self):
        """Test that 'plate-reader' metadata matches the bundled model_reference.json."""
        result_json = await describe_asm('plate-reader')
        result = json.loads(result_json)

        expected = _MODEL_REFERENCE['plate-reader']
        assert result == expected

    async def test_balance_returns_all_required_fields(self):
        """Test that 'balance' returns metadata with all four required fields."""
        result_json = await describe_asm('balance')
        result = json.loads(result_json)

        assert 'error' not in result
        assert 'description' in result
        assert 'asm_manifest' in result
        assert 'asm_json_schema' in result
        assert 'asm_data_instance_examples' in result

    async def test_balance_metadata_matches_reference(self):
        """Test that 'balance' metadata matches the bundled model_reference.json."""
        result_json = await describe_asm('balance')
        result = json.loads(result_json)

        expected = _MODEL_REFERENCE['balance']
        assert result == expected

    async def test_response_is_valid_json_string(self):
        """Test that the response is always a valid JSON string."""
        result_json = await describe_asm('absorbance')
        # Should not raise
        result = json.loads(result_json)
        assert isinstance(result, dict)


class TestDescribeAsmErrorPaths:
    """Unit tests for describe_asm error handling (Requirements 2.1, 2.2)."""

    async def test_unknown_model_name_returns_error_key(self):
        """Test that an unrecognised model name returns JSON with 'error' key."""
        result_json = await describe_asm('nonexistent-model-xyz')
        result = json.loads(result_json)

        assert 'error' in result

    async def test_unknown_model_name_error_contains_bad_name(self):
        """Test that the error message includes the unrecognised model name."""
        bad_name = 'nonexistent-model-xyz'
        result_json = await describe_asm(bad_name)
        result = json.loads(result_json)

        assert bad_name in result['error']

    async def test_unknown_model_name_includes_valid_model_names(self):
        """Test that the error response includes 'valid_model_names' with all reference keys."""
        result_json = await describe_asm('nonexistent-model-xyz')
        result = json.loads(result_json)

        assert 'valid_model_names' in result
        assert set(result['valid_model_names']) == set(_MODEL_REFERENCE.keys())

    async def test_missing_model_reference_file_returns_error(self):
        """Test that a missing model_reference.json returns a file-not-found error string."""
        with patch('builtins.open', MagicMock(side_effect=FileNotFoundError)):
            result_json = await describe_asm('absorbance')

        result = json.loads(result_json)
        assert 'error' in result
        assert 'Model reference file not found' in result['error']
        assert 'model_reference.json' in result['error']

    async def test_malformed_model_reference_file_returns_error(self):
        """Test that malformed model_reference.json returns a malformed-JSON error string."""
        invalid_json = 'not valid json at all'
        mock_file = mock_open(read_data=invalid_json)

        with patch('builtins.open', mock_file):
            result_json = await describe_asm('absorbance')

        result = json.loads(result_json)
        assert 'error' in result
        assert 'malformed JSON' in result['error']
