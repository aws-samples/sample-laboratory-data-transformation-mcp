# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for the validate_field_map MCP tool and _validate_field_map_entries helper."""

import json
import os
from allotrope_mcp_server.server import _validate_field_map_entries, mcp, validate_field_map
from hypothesis import given, settings
from hypothesis import strategies as st


TESTDATA_DIR = os.path.join(os.path.dirname(__file__), 'testdata')
MAP_PASS = os.path.join(TESTDATA_DIR, 'plate_reader_weyland_yutani_instrument_data_map_pass.json')
MAP_FAIL = os.path.join(TESTDATA_DIR, 'plate_reader_weyland_yutani_instrument_data_map_fail.json')


class TestToolRegistration:
    """Tests for validate_field_map MCP tool registration."""

    def test_validate_field_map_tool_registered(self):
        """Test that validate_field_map is registered as an MCP tool."""
        tools = mcp._tool_manager._tools
        assert 'validate_field_map' in tools

    def test_validate_field_map_accepts_field_map_path(self):
        """Test that the tool accepts a valid path and returns parseable JSON."""
        result_json = validate_field_map(MAP_PASS)
        result = json.loads(result_json)
        assert isinstance(result, dict)


class TestValidateFieldMapTool:
    """Happy-path tests for validate_field_map using real fixtures."""

    def test_pass_fixture_returns_expected_keys(self):
        """Test that the pass fixture result contains all expected keys."""
        result = json.loads(validate_field_map(MAP_PASS))
        assert 'matched' in result
        assert 'total' in result
        assert 'mismatches' in result
        assert 'message' in result

    def test_pass_fixture_total_is_19(self):
        """Test that the pass fixture has 19 total entries."""
        result = json.loads(validate_field_map(MAP_PASS))
        assert result['total'] == 19

    def test_pass_fixture_has_two_mismatches(self):
        """Test that the pass fixture has exactly 2 mismatches."""
        result = json.loads(validate_field_map(MAP_PASS))
        assert len(result['mismatches']) == 2

    def test_pass_fixture_message_contains_needs_to_be_updated(self):
        """Test that the pass fixture message indicates mismatches exist."""
        result = json.loads(validate_field_map(MAP_PASS))
        assert 'accurately reproduced' not in result['message']
        assert 'needs to be updated' in result['message']

    def test_fail_fixture_has_three_mismatches(self):
        """Test that the fail fixture has exactly 3 mismatches."""
        result = json.loads(validate_field_map(MAP_FAIL))
        assert len(result['mismatches']) == 3

    def test_fail_fixture_message_contains_needs_to_be_updated(self):
        """Test that the fail fixture message indicates mismatches exist."""
        result = json.loads(validate_field_map(MAP_FAIL))
        assert 'needs to be updated' in result['message']

    def test_fail_fixture_mismatch_objects_have_required_keys(self):
        """Test that each mismatch object contains all required keys."""
        result = json.loads(validate_field_map(MAP_FAIL))
        for mismatch in result['mismatches']:
            assert 'source_field' in mismatch
            assert 'source_value' in mismatch
            assert 'asm_field' in mismatch
            assert 'asm_value' in mismatch
            assert 'unit' in mismatch


class TestValidateFieldMapErrors:
    """Error-handling tests for validate_field_map."""

    def test_missing_file_returns_error(self, tmp_path):
        """Test that a nonexistent file returns an error key."""
        missing = str(tmp_path / 'does_not_exist.json')
        result = json.loads(validate_field_map(missing))
        assert 'error' in result

    def test_invalid_json_returns_error(self, tmp_path):
        """Test that invalid JSON content returns an error key."""
        bad_file = tmp_path / 'bad.json'
        bad_file.write_text('{not valid json!!!', encoding='utf-8')
        result = json.loads(validate_field_map(str(bad_file)))
        assert 'error' in result

    def test_non_array_object_returns_error(self, tmp_path):
        """Test that a JSON object (not array) returns an error key."""
        obj_file = tmp_path / 'obj.json'
        obj_file.write_text('{}', encoding='utf-8')
        result = json.loads(validate_field_map(str(obj_file)))
        assert 'error' in result

    def test_non_array_string_returns_error(self, tmp_path):
        """Test that a JSON string (not array) returns an error key."""
        str_file = tmp_path / 'str.json'
        str_file.write_text('"hello"', encoding='utf-8')
        result = json.loads(validate_field_map(str(str_file)))
        assert 'error' in result

    def test_missing_source_value_key_no_exception(self, tmp_path):
        """Test that an entry missing source_value does not raise."""
        entry_file = tmp_path / 'entry.json'
        entry_file.write_text(
            json.dumps([{'asm_value': 'x', 'source_field': 'f', 'asm_field': 'a', 'unit': ''}]),
            encoding='utf-8',
        )
        result = json.loads(validate_field_map(str(entry_file)))
        assert 'matched' in result

    def test_missing_asm_value_key_no_exception(self, tmp_path):
        """Test that an entry missing asm_value does not raise."""
        entry_file = tmp_path / 'entry.json'
        entry_file.write_text(
            json.dumps([{'source_value': 'x', 'source_field': 'f', 'asm_field': 'a', 'unit': ''}]),
            encoding='utf-8',
        )
        result = json.loads(validate_field_map(str(entry_file)))
        assert 'matched' in result


class TestValidateFieldMapPathHandling:
    """Path handling tests for validate_field_map."""

    def test_dotdot_path_resolves_correctly(self):
        """Test that a path with '..' resolves to the correct file."""
        # Construct a path using '..' that resolves to MAP_PASS
        testdata_dir = os.path.dirname(MAP_PASS)
        traversal_path = os.path.join(testdata_dir, 'subdir', '..', os.path.basename(MAP_PASS))
        result = json.loads(validate_field_map(traversal_path))
        assert result['total'] == 19


class TestValidateFieldMapProperties:
    """Property-based tests for _validate_field_map_entries."""

    @given(
        entries=st.lists(
            st.fixed_dictionaries(
                {
                    'source_field': st.text(),
                    'source_value': st.one_of(
                        st.text(), st.integers(), st.floats(allow_nan=False), st.none()
                    ),
                    'asm_field': st.text(),
                    'asm_value': st.one_of(
                        st.text(), st.integers(), st.floats(allow_nan=False), st.none()
                    ),
                    'unit': st.text(),
                }
            )
        )
    )
    @settings(max_examples=100)
    def test_result_completeness_invariant(self, entries):
        """Property 1: matched + len(mismatches) == total == len(entries)."""
        result = _validate_field_map_entries(entries)
        assert result['matched'] + len(result['mismatches']) == result['total'] == len(entries)

    @given(v=st.one_of(st.text(), st.integers()))
    @settings(max_examples=100)
    def test_string_equal_entries_always_match(self, v):
        """Property 2: string-equal entries are always classified as matches."""
        entries = [
            {
                'source_field': 'f',
                'source_value': v,
                'asm_field': 'a',
                'asm_value': v,
                'unit': '',
            }
        ]
        result = _validate_field_map_entries(entries)
        assert result['matched'] == 1
        assert result['mismatches'] == []

    @given(n=st.integers())
    @settings(max_examples=100)
    def test_numerically_equal_entries_always_match(self, n):
        """Property 3: numerically-equal entries (int vs float) are matches."""
        entries = [
            {
                'source_field': 'f',
                'source_value': n,
                'asm_field': 'a',
                'asm_value': float(n),
                'unit': '',
            }
        ]
        result = _validate_field_map_entries(entries)
        assert result['matched'] == 1
        assert result['mismatches'] == []

    @given(
        entries=st.lists(
            st.fixed_dictionaries(
                {
                    'source_field': st.text(),
                    'source_value': st.just('x'),
                    'asm_field': st.text(),
                    'asm_value': st.just('y'),
                    'unit': st.text(),
                }
            ),
            min_size=1,
        )
    )
    @settings(max_examples=100)
    def test_mismatch_object_completeness(self, entries):
        """Property 4: mismatch objects contain all required keys."""
        result = _validate_field_map_entries(entries)
        for mismatch in result['mismatches']:
            assert 'source_field' in mismatch
            assert 'source_value' in mismatch
            assert 'asm_field' in mismatch
            assert 'asm_value' in mismatch
            assert 'unit' in mismatch
