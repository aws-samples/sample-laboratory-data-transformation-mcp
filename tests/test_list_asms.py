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

"""Unit and property-based tests for the list_asms tool."""

import json
from awslabs.allotrope_mcp_server.server import list_asms
from pathlib import Path


class TestListAsmsTool:
    """Unit tests for the list_asms MCP tool."""

    async def test_successful_asm_listing(self):
        """Test successful ASM listing with actual model_reference.json file.

        Verifies:
        - Response is valid JSON
        - All expected ASM IDs are present
        - Descriptions match file content
        """
        # Call the list_asms function
        result_json = await list_asms()

        # Verify response is valid JSON
        result = json.loads(result_json)

        # Verify no error key in response
        assert 'error' not in result

        # Read the actual model_reference.json file to compare
        package_dir = Path(__file__).parent.parent / 'awslabs' / 'allotrope_mcp_server'
        model_ref_path = package_dir / 'model_reference.json'

        with open(model_ref_path) as f:
            expected_data = json.load(f)

        # Verify all expected ASM IDs are present
        expected_ids = set(expected_data.keys())
        actual_ids = set(result.keys())
        assert expected_ids == actual_ids, (
            f'Missing IDs: {expected_ids - actual_ids}, Extra IDs: {actual_ids - expected_ids}'
        )

        # Verify descriptions match file content
        for asm_id, description in result.items():
            expected_description = expected_data[asm_id]['description']
            assert description == expected_description, f'Description mismatch for {asm_id}'

        # Verify we have a reasonable number of ASMs (sanity check)
        assert len(result) > 40, f'Expected more than 40 ASMs, got {len(result)}'

    async def test_file_not_found_error(self):
        """Test handling of FileNotFoundError when model_reference.json is missing.

        Verifies:
        - Response contains 'error' key
        - Error message mentions 'Model reference file not found'
        - Error message contains the file path
        """
        from unittest.mock import MagicMock, patch

        # Mock builtins.open to raise FileNotFoundError
        with patch('builtins.open', MagicMock(side_effect=FileNotFoundError)):
            result_json = await list_asms()

        # Parse response
        result = json.loads(result_json)

        # Verify error response
        assert 'error' in result
        assert 'Model reference file not found' in result['error']
        assert 'model_reference.json' in result['error']

    async def test_json_parsing_error(self):
        """Test handling of malformed JSON in model_reference.json.

        Verifies:
        - Response contains 'error' key
        - Error message mentions 'malformed JSON'
        """
        from unittest.mock import mock_open, patch

        # Mock builtins.open to return invalid JSON
        invalid_json = 'not valid json at all'
        mock_file = mock_open(read_data=invalid_json)

        with patch('builtins.open', mock_file):
            result_json = await list_asms()

        # Parse response
        result = json.loads(result_json)

        # Verify error response
        assert 'error' in result
        assert 'malformed JSON' in result['error']

    async def test_missing_description_field(self):
        """Test handling of ASM entry missing description field.

        Verifies:
        - Response contains 'error' key
        - Error message mentions the ASM ID
        - Error message mentions 'missing description field'
        """
        from unittest.mock import mock_open, patch

        # Mock builtins.open to return JSON with missing description
        invalid_data = json.dumps({'test-asm': {'asm_manifest': 'url'}})
        mock_file = mock_open(read_data=invalid_data)

        with patch('builtins.open', mock_file):
            result_json = await list_asms()

        # Parse response
        result = json.loads(result_json)

        # Verify error response
        assert 'error' in result
        assert 'test-asm' in result['error']
        assert 'missing description field' in result['error']

    async def test_unexpected_exception_handling(self):
        """Test handling of unexpected exceptions during file operations.

        Verifies:
        - Response contains 'error' key
        - Error message mentions 'Unexpected error'
        - No unhandled exception propagates
        """
        from unittest.mock import MagicMock, patch

        # Mock builtins.open to raise RuntimeError
        with patch('builtins.open', MagicMock(side_effect=RuntimeError('unexpected error'))):
            result_json = await list_asms()

        # Parse response
        result = json.loads(result_json)

        # Verify error response
        assert 'error' in result
        assert 'Unexpected error' in result['error']
