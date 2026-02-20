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

"""Unit tests for the list_asm_techniques tool and _fetch_asm_techniques helper."""

import json
import pytest
import urllib.error
from awslabs.allotrope_mcp_server.server import (
    _fetch_asm_techniques,
    list_asm_techniques,
    mcp,
)
from email.message import Message
from io import BytesIO
from unittest.mock import MagicMock, patch


def _make_response(body_bytes, headers=None):
    """Create a mock urllib response with the given body and headers."""
    resp = MagicMock()
    resp.read.return_value = body_bytes
    resp.headers = MagicMock()
    resp.headers.get = lambda key, default='': (headers or {}).get(key, default)
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestFetchAsmTechniques:
    """Tests for the _fetch_asm_techniques helper function."""

    @patch('awslabs.allotrope_mcp_server.server.urllib.request.urlopen')
    def test_single_page_returns_filtered_names(self, mock_urlopen):
        """Test successful single-page fetch returns only tree-type entries."""
        entries = [
            {'name': 'cell-counting', 'type': 'tree', 'path': 'json-schemas/adm/cell-counting'},
            {'name': 'README.md', 'type': 'blob', 'path': 'json-schemas/adm/README.md'},
            {'name': 'balance', 'type': 'tree', 'path': 'json-schemas/adm/balance'},
        ]
        mock_urlopen.return_value = _make_response(json.dumps(entries).encode())

        result = _fetch_asm_techniques()

        assert result == ['cell-counting', 'balance']
        mock_urlopen.assert_called_once()

    @patch('awslabs.allotrope_mcp_server.server.urllib.request.urlopen')
    def test_multi_page_pagination(self, mock_urlopen):
        """Test pagination follows x-next-page header and combines results."""
        page1_entries = [
            {'name': 'balance', 'type': 'tree', 'path': 'p1'},
        ]
        page2_entries = [
            {'name': 'cell-counting', 'type': 'tree', 'path': 'p2'},
        ]
        resp1 = _make_response(json.dumps(page1_entries).encode(), {'x-next-page': '2'})
        resp2 = _make_response(json.dumps(page2_entries).encode())
        mock_urlopen.side_effect = [resp1, resp2]

        result = _fetch_asm_techniques()

        assert result == ['balance', 'cell-counting']
        assert mock_urlopen.call_count == 2

    @patch('awslabs.allotrope_mcp_server.server.urllib.request.urlopen')
    def test_http_error_raises(self, mock_urlopen):
        """Test HTTP error (non-2xx) raises urllib.error.HTTPError."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url='https://gitlab.com', code=500, msg='Server Error', hdrs=Message(), fp=BytesIO(b'')
        )

        with pytest.raises(urllib.error.HTTPError):
            _fetch_asm_techniques()

    @patch('awslabs.allotrope_mcp_server.server.urllib.request.urlopen')
    def test_network_error_raises(self, mock_urlopen):
        """Test network/connection error raises urllib.error.URLError."""
        mock_urlopen.side_effect = urllib.error.URLError('Connection refused')

        with pytest.raises(urllib.error.URLError):
            _fetch_asm_techniques()

    @patch('awslabs.allotrope_mcp_server.server.urllib.request.urlopen')
    def test_invalid_json_raises(self, mock_urlopen):
        """Test invalid JSON response raises json.JSONDecodeError."""
        mock_urlopen.return_value = _make_response(b'not json at all')

        with pytest.raises(json.JSONDecodeError):
            _fetch_asm_techniques()

    @patch('awslabs.allotrope_mcp_server.server.urllib.request.urlopen')
    def test_timeout_raises(self, mock_urlopen):
        """Test timeout raises TimeoutError."""
        mock_urlopen.side_effect = TimeoutError('timed out')

        with pytest.raises(TimeoutError):
            _fetch_asm_techniques()


class TestListAsmTechniquesTool:
    """Tests for the list_asm_techniques MCP tool wrapper."""

    def test_list_asm_techniques_tool_registered(self):
        """Test that list_asm_techniques tool is registered on the MCP server."""
        tools = mcp._tool_manager._tools
        assert 'list_asm_techniques' in tools

    @patch('awslabs.allotrope_mcp_server.server._fetch_asm_techniques')
    async def test_success_returns_json_with_techniques(self, mock_fetch):
        """Test successful invocation returns JSON with techniques key."""
        mock_fetch.return_value = ['balance', 'cell-counting']

        result_json = await list_asm_techniques()
        result = json.loads(result_json)

        assert 'techniques' in result
        assert result['techniques'] == ['balance', 'cell-counting']

    @patch('awslabs.allotrope_mcp_server.server._fetch_asm_techniques')
    async def test_http_error_returns_json_with_error(self, mock_fetch):
        """Test HTTP error returns JSON with error key."""
        mock_fetch.side_effect = urllib.error.HTTPError(
            url='https://gitlab.com', code=500, msg='Server Error', hdrs=Message(), fp=BytesIO(b'')
        )

        result_json = await list_asm_techniques()
        result = json.loads(result_json)

        assert 'error' in result
        assert '500' in result['error']

    @patch('awslabs.allotrope_mcp_server.server._fetch_asm_techniques')
    async def test_network_error_returns_json_with_error(self, mock_fetch):
        """Test network error returns JSON with error key."""
        mock_fetch.side_effect = urllib.error.URLError('Connection refused')

        result_json = await list_asm_techniques()
        result = json.loads(result_json)

        assert 'error' in result
        assert 'connect' in result['error'].lower()

    @patch('awslabs.allotrope_mcp_server.server._fetch_asm_techniques')
    async def test_timeout_returns_json_with_error(self, mock_fetch):
        """Test timeout returns JSON with error key."""
        mock_fetch.side_effect = TimeoutError('timed out')

        result_json = await list_asm_techniques()
        result = json.loads(result_json)

        assert 'error' in result
        assert 'timed out' in result['error'].lower()
