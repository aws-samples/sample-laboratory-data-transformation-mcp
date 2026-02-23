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

"""Unit tests for MCP server registration and the validate_asm tool."""

import json
import os
import tempfile
from awslabs.allotrope_mcp_server.server import (
    mcp,
    validate_asm,
    validate_asm_document,
)
from mcp.server.fastmcp import FastMCP


TESTDATA_DIR = os.path.join(os.path.dirname(__file__), 'testdata')
VALID_DOC = os.path.join(TESTDATA_DIR, 'plate_reader_weyland_yutani_valid.json')
INVALID_DOC = os.path.join(TESTDATA_DIR, 'plate_reader_weyland_yutani_invalid.json')
SCHEMA = os.path.join(TESTDATA_DIR, 'plate_reader.embed.schema.json')


class TestMcpServer:
    """Tests for MCP server instance and tool registration."""

    def test_mcp_is_fastmcp_instance(self):
        """Test that mcp is a FastMCP instance."""
        assert isinstance(mcp, FastMCP)

    def test_mcp_server_name(self):
        """Test that the server has the correct name."""
        assert mcp.name == 'awslabs.allotrope-mcp-server'

    def test_validate_asm_tool_registered(self):
        """Test that validate_asm tool is registered."""
        tools = mcp._tool_manager._tools
        assert 'validate_asm' in tools


class TestValidateAsmDocument:
    """Tests for validate_asm_document using real testdata fixtures."""

    def test_valid_document(self):
        """Test that a valid document passes validation."""
        result = validate_asm_document(VALID_DOC, SCHEMA)
        assert result.is_valid is True
        assert result.errors == []
        assert result.error_message is None

    def test_invalid_document(self):
        """Test that an invalid document fails validation with errors."""
        result = validate_asm_document(INVALID_DOC, SCHEMA)
        assert result.is_valid is False
        assert len(result.errors) > 0
        for error in result.errors:
            assert error.path
            assert error.message
            assert error.validator

    def test_document_file_not_found(self):
        """Test that a missing document file returns an error."""
        missing = '/tmp/does_not_exist_abc123.json'
        result = validate_asm_document(missing, SCHEMA)
        assert result.is_valid is False
        assert result.error_message is not None
        assert missing in result.error_message

    def test_schema_file_not_found(self):
        """Test that a missing schema file returns an error."""
        missing = '/tmp/does_not_exist_abc123.json'
        result = validate_asm_document(VALID_DOC, missing)
        assert result.is_valid is False
        assert result.error_message is not None
        assert missing in result.error_message

    def test_malformed_document_json(self):
        """Test that malformed JSON in the document returns an error."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{not valid json!!!')
            tmp_path = f.name
        try:
            result = validate_asm_document(tmp_path, SCHEMA)
            assert result.is_valid is False
            assert result.error_message is not None
            assert 'malformed JSON' in result.error_message
        finally:
            os.unlink(tmp_path)

    def test_malformed_schema_json(self):
        """Test that malformed JSON in the schema returns an error."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{not valid json!!!')
            tmp_path = f.name
        try:
            result = validate_asm_document(VALID_DOC, tmp_path)
            assert result.is_valid is False
            assert result.error_message is not None
            assert 'malformed JSON' in result.error_message
        finally:
            os.unlink(tmp_path)


class TestValidateAsmTool:
    """Tests for the validate_asm MCP tool wrapper."""

    def test_valid_document_returns_json(self):
        """Test that validate_asm returns valid JSON for a valid document."""
        result_json = validate_asm(VALID_DOC, SCHEMA)
        result = json.loads(result_json)
        assert result['is_valid'] is True
        assert result['errors'] == []
        assert 'error_message' not in result

    def test_invalid_document_returns_json(self):
        """Test that validate_asm returns valid JSON for an invalid document."""
        result_json = validate_asm(INVALID_DOC, SCHEMA)
        result = json.loads(result_json)
        assert result['is_valid'] is False
        assert len(result['errors']) > 0

    def test_missing_file_returns_json_with_error_message(self):
        """Test that validate_asm returns JSON with error_message for missing files."""
        result_json = validate_asm('/tmp/nonexistent.json', SCHEMA)
        result = json.loads(result_json)
        assert result['is_valid'] is False
        assert 'error_message' in result
