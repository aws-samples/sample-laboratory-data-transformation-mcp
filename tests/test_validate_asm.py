# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for MCP server registration and the validate_asm_schema tool."""

import json
import os
from allotrope_mcp_server.server import (
    mcp,
    validate_asm_schema,
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
        assert mcp.name == 'allotrope-mcp-server'

    def test_validate_asm_tool_registered(self):
        """Test that validate_asm_schema tool is registered."""
        tools = mcp._tool_manager._tools
        assert 'validate_asm_schema' in tools


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

    def test_document_file_not_found(self, tmp_path):
        """Test that a missing document file returns an error."""
        missing = str(tmp_path / 'does_not_exist_abc123.json')
        result = validate_asm_document(missing, SCHEMA)
        assert result.is_valid is False
        assert result.error_message is not None
        assert 'not found' in result.error_message

    def test_schema_file_not_found(self, tmp_path):
        """Test that a missing schema file returns an error."""
        missing = str(tmp_path / 'does_not_exist_abc123.json')
        result = validate_asm_document(VALID_DOC, missing)
        assert result.is_valid is False
        assert result.error_message is not None
        assert 'not found' in result.error_message

    def test_malformed_document_json(self, tmp_path):
        """Test that malformed JSON in the document returns an error."""
        tmp_file = tmp_path / 'malformed_doc.json'
        tmp_file.write_text('{not valid json!!!', encoding='utf-8')
        try:
            result = validate_asm_document(str(tmp_file), SCHEMA)
            assert result.is_valid is False
            assert result.error_message is not None
            assert 'malformed JSON' in result.error_message
        finally:
            tmp_file.unlink(missing_ok=True)

    def test_malformed_schema_json(self, tmp_path):
        """Test that malformed JSON in the schema returns an error."""
        tmp_file = tmp_path / 'malformed_schema.json'
        tmp_file.write_text('{not valid json!!!', encoding='utf-8')
        try:
            result = validate_asm_document(VALID_DOC, str(tmp_file))
            assert result.is_valid is False
            assert result.error_message is not None
            assert 'malformed JSON' in result.error_message
        finally:
            tmp_file.unlink(missing_ok=True)

    def test_document_exceeds_size_limit(self, tmp_path):
        """Test that a document exceeding the size limit returns an error."""
        from allotrope_mcp_server.server import MAX_FILE_SIZE_BYTES
        big_file = tmp_path / 'big_doc.json'
        # Write a file just over the limit (content doesn't need to be valid JSON).
        big_file.write_bytes(b'x' * (MAX_FILE_SIZE_BYTES + 1))
        result = validate_asm_document(str(big_file), SCHEMA)
        assert result.is_valid is False
        assert result.error_message is not None
        assert 'exceeds maximum' in result.error_message

    def test_schema_exceeds_size_limit(self, tmp_path):
        """Test that a schema exceeding the size limit returns an error."""
        from allotrope_mcp_server.server import MAX_FILE_SIZE_BYTES
        big_file = tmp_path / 'big_schema.json'
        big_file.write_bytes(b'x' * (MAX_FILE_SIZE_BYTES + 1))
        result = validate_asm_document(VALID_DOC, str(big_file))
        assert result.is_valid is False
        assert result.error_message is not None
        assert 'exceeds maximum' in result.error_message


class TestValidateAsmDocumentPathTraversal:
    """Tests that path traversal sequences are neutralised."""

    def test_document_path_with_dotdot_is_canonicalised(self, tmp_path):
        """A document path containing '..' is resolved before use, not rejected."""
        # Build a path that uses '..' but ultimately resolves to a real file.
        doc = tmp_path / 'doc.json'
        doc.write_text('{}', encoding='utf-8')
        schema = tmp_path / 'schema.json'
        schema.write_text('{}', encoding='utf-8')
        # Construct a path with '..' that still resolves to the same file.
        traversal_doc = str(tmp_path / 'subdir' / '..' / 'doc.json')
        result = validate_asm_document(traversal_doc, str(schema))
        # Should succeed (empty doc is valid against empty schema).
        assert result.error_message is None or 'not found' not in (result.error_message or '')

    def test_schema_path_with_dotdot_is_canonicalised(self, tmp_path):
        """A schema path containing '..' is resolved before use, not rejected."""
        doc = tmp_path / 'doc.json'
        doc.write_text('{}', encoding='utf-8')
        schema = tmp_path / 'schema.json'
        schema.write_text('{}', encoding='utf-8')
        traversal_schema = str(tmp_path / 'subdir' / '..' / 'schema.json')
        result = validate_asm_document(str(doc), traversal_schema)
        assert result.error_message is None or 'not found' not in (result.error_message or '')


class TestValidateAsmSchemaTool:
    """Tests for the validate_asm_schema MCP tool wrapper."""

    def test_valid_document_returns_json(self):
        """Test that validate_asm_schema returns valid JSON for a valid document."""
        result_json = validate_asm_schema(VALID_DOC, SCHEMA)
        result = json.loads(result_json)
        assert result['is_valid'] is True
        assert result['errors'] == []
        assert 'error_message' not in result

    def test_invalid_document_returns_json(self):
        """Test that validate_asm_schema returns valid JSON for an invalid document."""
        result_json = validate_asm_schema(INVALID_DOC, SCHEMA)
        result = json.loads(result_json)
        assert result['is_valid'] is False
        assert len(result['errors']) > 0

    def test_missing_file_returns_json_with_error_message(self, tmp_path):
        """Test that validate_asm_schema returns JSON with error_message for missing files."""
        missing = str(tmp_path / 'nonexistent.json')
        result_json = validate_asm_schema(missing, SCHEMA)
        result = json.loads(result_json)
        assert result['is_valid'] is False
        assert 'error_message' in result
