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

"""Tests for get_asm_schema helpers and tool."""

import json
from unittest.mock import MagicMock, patch

from awslabs.allotrope_mcp_server.server import (
    _generate_embed_filename,
    _normalize_schema_id,
    _resolve_refs,
)
from hypothesis import given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Path segments: lowercase letters and digits, 1-15 chars each.
_path_segment = st.text(
    alphabet=st.sampled_from('abcdefghijklmnopqrstuvwxyz0123456789_-'),
    min_size=1,
    max_size=15,
)

# A bare schema suffix like "adm/conductivity/REC/2021/12/conductivity.schema"
_bare_suffix = st.lists(_path_segment, min_size=1, max_size=6).map(lambda parts: '/'.join(parts))

# Filenames that contain at least one dot (required by _generate_embed_filename).
_dotted_filename = st.tuples(
    st.text(
        alphabet=st.sampled_from('abcdefghijklmnopqrstuvwxyz0123456789_-'),
        min_size=1,
        max_size=15,
    ),
    st.lists(
        st.text(
            alphabet=st.sampled_from('abcdefghijklmnopqrstuvwxyz0123456789'),
            min_size=1,
            max_size=10,
        ),
        min_size=1,
        max_size=3,
    ),
).map(lambda t: t[0] + '.' + '.'.join(t[1]))


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


# Feature: get-asm-schema, Property 1: Schema ID normalization convergence
@given(suffix=_bare_suffix)
@settings(max_examples=100)
def test_normalization_convergence(suffix: str) -> None:
    """All three input forms produce the same normalized path starting with json-schemas/."""
    full_uri = f'http://purl.allotrope.org/json-schemas/{suffix}'
    prefixed = f'json-schemas/{suffix}'
    bare = suffix

    result_uri = _normalize_schema_id(full_uri)
    result_prefixed = _normalize_schema_id(prefixed)
    result_bare = _normalize_schema_id(bare)

    # All forms converge to the same value.
    assert result_uri == result_prefixed, (
        f'URI vs prefixed mismatch: {result_uri!r} != {result_prefixed!r}'
    )
    assert result_prefixed == result_bare, (
        f'Prefixed vs bare mismatch: {result_prefixed!r} != {result_bare!r}'
    )

    # Result always starts with json-schemas/.
    assert result_uri.startswith('json-schemas/'), (
        f'Expected json-schemas/ prefix, got {result_uri!r}'
    )


# Feature: get-asm-schema, Property 3: Embed filename generation
@given(filename=_dotted_filename)
@settings(max_examples=100)
def test_embed_filename_generation(filename: str) -> None:
    """Output contains .embed. and ends with .json."""
    result = _generate_embed_filename(filename)

    assert '.embed.' in result, f'Expected .embed. in {result!r}'
    assert result.endswith('.json'), f'Expected .json suffix in {result!r}'


# Strategy: generate a schema tree where some leaf dicts contain a $ref pointing
# to one of a small set of http:// URIs.  The cache is pre-populated with simple
# resolved schemas (no further refs) so _resolve_refs never hits the network.

_REF_URIS = [f'http://example.com/schemas/type{i}.json' for i in range(5)]

_ref_uri = st.sampled_from(_REF_URIS)


@st.composite
def _schema_with_refs(draw: st.DrawFn) -> tuple[dict, dict[str, dict]]:
    """Generate a random schema tree with $ref entries and a matching cache.

    Returns a tuple of (schema, cache) where cache maps every referenced URI
    to a simple resolved dict (no further $ref values).
    """
    used_uris: set[str] = set()

    def _build(depth: int) -> dict:
        result: dict = {}
        n_keys = draw(st.integers(min_value=1, max_value=4))
        for i in range(n_keys):
            key = f'field_{depth}_{i}'
            choice = draw(st.integers(min_value=0, max_value=3))
            if choice == 0 and depth < 3:
                # Nested dict (recurse)
                result[key] = _build(depth + 1)
            elif choice == 1:
                # A $ref entry — put it as a standalone dict value
                uri = draw(_ref_uri)
                fragment = draw(st.sampled_from(['', '#/definitions/MyType']))
                ref_value = uri if not fragment else f'{uri}{fragment}'
                result[key] = {'$ref': ref_value}
                used_uris.add(uri)
            elif choice == 2:
                # List with possible ref dicts
                items = []
                for _ in range(draw(st.integers(min_value=0, max_value=2))):
                    if draw(st.booleans()):
                        uri = draw(_ref_uri)
                        items.append({'$ref': uri})
                        used_uris.add(uri)
                    else:
                        items.append({'value': draw(st.integers())})
                result[key] = items
            else:
                result[key] = draw(st.text(min_size=0, max_size=10))
        return result

    schema = _build(0)

    # Build cache: each URI maps to a simple schema with a definitions section.
    cache: dict[str, dict] = {}
    for uri in used_uris:
        cache[uri] = {
            'type': 'object',
            'definitions': {
                'MyType': {'type': 'string', 'description': 'resolved'},
            },
        }

    return schema, cache


def _collect_refs(obj: object) -> list[str]:
    """Walk a nested dict/list and return all $ref string values."""
    refs: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == '$ref' and isinstance(v, str):
                refs.append(v)
            else:
                refs.extend(_collect_refs(v))
    elif isinstance(obj, list):
        for item in obj:
            refs.extend(_collect_refs(item))
    return refs


# Feature: get-asm-schema, Property 4: Resolution completeness
@given(data=_schema_with_refs())
@settings(max_examples=100)
def test_resolution_completeness(data: tuple[dict, dict[str, dict]]) -> None:
    """After _resolve_refs, no $ref values starting with http remain.

    **Validates: Requirements 5.5, 5.6**
    """
    schema, cache = data
    resolved = _resolve_refs(schema, cache, set(), 'http://example.com/root.json')

    remaining = [r for r in _collect_refs(resolved) if r.startswith('http')]
    assert remaining == [], f'Unresolved $ref values remain: {remaining}'


# Strategy: generate a nested dict with a known value at a random path, then
# return the dict, the JSON pointer string, and the expected leaf value.

_LEAF_VALUES = st.one_of(
    st.integers(min_value=-1000, max_value=1000),
    st.text(
        alphabet=st.sampled_from('abcdefghijklmnopqrstuvwxyz0123456789'),
        min_size=1,
        max_size=10,
    ),
    st.booleans(),
)

_DICT_KEY = st.text(
    alphabet=st.sampled_from('abcdefghijklmnopqrstuvwxyz'),
    min_size=1,
    max_size=8,
)


@st.composite
def _nested_dict_with_path(
    draw: st.DrawFn,
) -> tuple[dict, str, object]:
    """Build a nested dict, a valid JSON pointer path, and the expected value.

    Returns (nested_dict, pointer_string, expected_value).
    The pointer_string looks like ``/key1/key2/key3``.
    """
    depth = draw(st.integers(min_value=1, max_value=4))
    keys: list[str] = [draw(_DICT_KEY) for _ in range(depth)]
    leaf = draw(_LEAF_VALUES)

    # Build the nested dict from the inside out.
    current: dict | object = leaf
    for key in reversed(keys):
        current = {key: current}

    pointer = '/' + '/'.join(keys)
    return current, pointer, leaf  # type: ignore[return-value]


_FAKE_FRAGMENT_URI = 'http://test.com/schema.json'


# Feature: get-asm-schema, Property 5: JSON pointer fragment extraction
@given(data=_nested_dict_with_path())
@settings(max_examples=100)
def test_fragment_extraction(data: tuple[dict, str, object]) -> None:
    """Navigating a JSON pointer fragment returns the correct nested value.

    **Validates: Requirements 5.2, 5.4**
    """
    nested_dict, pointer, expected = data

    # Pre-populate cache with the generated nested dict.
    cache: dict[str, dict] = {_FAKE_FRAGMENT_URI: nested_dict}

    # Schema with a single $ref that includes the fragment.
    schema = {'$ref': f'{_FAKE_FRAGMENT_URI}#{pointer}'}

    resolved = _resolve_refs(schema, cache, set(), 'http://test.com/root.json')

    # The resolved value should equal the expected leaf.
    assert resolved == expected, (
        f'Fragment {pointer!r} resolved to {resolved!r}, expected {expected!r}'
    )


# Feature: get-asm-schema, Property 5: JSON pointer fragment extraction (empty fragment)
@given(data=_nested_dict_with_path())
@settings(max_examples=100)
def test_empty_fragment_returns_entire_schema(
    data: tuple[dict, str, object],
) -> None:
    """An empty fragment (no '#' or '#' with empty path) returns the entire schema.

    **Validates: Requirements 5.2, 5.4**
    """
    nested_dict, _pointer, _expected = data

    cache: dict[str, dict] = {_FAKE_FRAGMENT_URI: nested_dict}

    # $ref with no fragment at all.
    schema_no_hash = {'$ref': _FAKE_FRAGMENT_URI}
    resolved_no_hash = _resolve_refs(
        schema_no_hash, cache, set(), 'http://test.com/root.json'
    )

    # The resolved output should be the recursively-resolved version of the
    # entire nested dict (no fragment navigation).
    expected_full = _resolve_refs(
        nested_dict, cache, set(), _FAKE_FRAGMENT_URI
    )
    assert resolved_no_hash == expected_full, (
        f'No-hash ref resolved to {resolved_no_hash!r}, '
        f'expected full schema {expected_full!r}'
    )

    # $ref with '#' but empty path after it.
    schema_empty_frag = {'$ref': f'{_FAKE_FRAGMENT_URI}#'}
    resolved_empty = _resolve_refs(
        schema_empty_frag, cache, set(), 'http://test.com/root.json'
    )
    assert resolved_empty == expected_full, (
        f'Empty-fragment ref resolved to {resolved_empty!r}, '
        f'expected full schema {expected_full!r}'
    )


# Strategy: generate two unique URIs with schemas that form a circular $ref
# chain (A → B → A).  Both schemas are pre-populated in the cache so no
# network access is needed.

_URI_SUFFIX = st.text(
    alphabet=st.sampled_from('abcdefghijklmnopqrstuvwxyz0123456789'),
    min_size=1,
    max_size=12,
)

_EXTRA_FIELDS = st.dictionaries(
    keys=st.text(
        alphabet=st.sampled_from('abcdefghijklmnopqrstuvwxyz'),
        min_size=1,
        max_size=8,
    ).filter(lambda k: k != '$ref'),
    values=st.one_of(
        st.integers(min_value=-100, max_value=100),
        st.text(min_size=0, max_size=10),
        st.booleans(),
    ),
    min_size=0,
    max_size=3,
)


@st.composite
def _circular_ref_schemas(
    draw: st.DrawFn,
) -> tuple[str, str, dict, dict, dict[str, dict]]:
    """Generate two schemas with a circular $ref chain and a pre-populated cache.

    Returns (uri_a, uri_b, schema_a, schema_b, cache).
    schema_a has a field whose value is ``{'$ref': uri_b}``.
    schema_b has a field whose value is ``{'$ref': uri_a}``.
    """
    suffix_a = draw(_URI_SUFFIX)
    suffix_b = draw(_URI_SUFFIX.filter(lambda s: s != suffix_a))

    uri_a = f'http://example.com/{suffix_a}.json'
    uri_b = f'http://example.com/{suffix_b}.json'

    extra_a = draw(_EXTRA_FIELDS)
    extra_b = draw(_EXTRA_FIELDS)

    schema_a: dict = {**extra_a, 'ref_to_b': {'$ref': uri_b}}
    schema_b: dict = {**extra_b, 'ref_to_a': {'$ref': uri_a}}

    cache: dict[str, dict] = {uri_a: schema_a, uri_b: schema_b}
    return uri_a, uri_b, schema_a, schema_b, cache


# Feature: get-asm-schema, Property 6: Circular reference preservation
@given(data=_circular_ref_schemas())
@settings(max_examples=100)
def test_circular_reference_preservation(
    data: tuple[str, str, dict, dict, dict[str, dict]],
) -> None:
    """Circular $ref chains are preserved and no exception is raised.

    **Validates: Requirements 10.2, 10.4**
    """
    uri_a, uri_b, _schema_a, _schema_b, cache = data

    # Build a wrapper schema that references A.
    wrapper = {'$ref': uri_a}

    # _resolve_refs must complete without error (no infinite loop).
    resolved = _resolve_refs(wrapper, cache, set(), 'http://example.com/root.json')

    # The circular $ref (B → A) should be preserved somewhere in the output.
    remaining_refs = _collect_refs(resolved)
    http_refs = [r for r in remaining_refs if r.startswith('http')]
    assert len(http_refs) >= 1, (
        f'Expected at least one preserved circular $ref, '
        f'but found none in resolved output: {resolved!r}'
    )

    # Specifically, the circular back-reference to uri_a should be preserved.
    assert any(uri_a in r for r in http_refs), (
        f'Expected circular $ref back to {uri_a!r} to be preserved, '
        f'but remaining refs are: {http_refs!r}'
    )


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------


class TestNormalizeSchemaId:
    """Unit tests for _normalize_schema_id."""

    def test_full_uri(self) -> None:
        """Full URI is stripped to json-schemas/ path."""
        uri = 'http://purl.allotrope.org/json-schemas/adm/conductivity/BENCHMARKS/conductivity.schema'
        assert _normalize_schema_id(uri) == 'json-schemas/adm/conductivity/BENCHMARKS/conductivity.schema'

    def test_json_schemas_prefix(self) -> None:
        """Path already starting with json-schemas/ is returned as-is."""
        path = 'json-schemas/adm/conductivity/BENCHMARKS/conductivity.schema'
        assert _normalize_schema_id(path) == path

    def test_bare_path(self) -> None:
        """Bare path gets json-schemas/ prepended."""
        bare = 'adm/conductivity/BENCHMARKS/conductivity.schema'
        assert _normalize_schema_id(bare) == f'json-schemas/{bare}'


class TestGenerateEmbedFilename:
    """Unit tests for _generate_embed_filename."""

    def test_schema_extension(self) -> None:
        """conductivity.schema becomes conductivity.embed.schema.json."""
        assert _generate_embed_filename('conductivity.schema') == 'conductivity.embed.schema.json'

    def test_json_extension(self) -> None:
        """foo.json becomes foo.embed.json (no extra .json appended)."""
        assert _generate_embed_filename('foo.json') == 'foo.embed.json'

    def test_multi_dot_extension(self) -> None:
        """bar.schema.json becomes bar.embed.schema.json (no extra .json)."""
        assert _generate_embed_filename('bar.schema.json') == 'bar.embed.schema.json'


class TestResolveRefs:
    """Unit tests for _resolve_refs."""

    def _mock_urlopen(self, response_data: dict):
        """Create a mock context manager for urllib.request.urlopen."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode('utf-8')
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_resp)
        mock_cm.__exit__ = MagicMock(return_value=False)
        return mock_cm

    def test_successful_resolution_with_mocked_http(self) -> None:
        """External $ref is resolved via mocked HTTP download."""
        remote_schema = {'type': 'string', 'description': 'downloaded'}
        schema = {'$ref': 'http://example.com/type.json'}

        mock_cm = self._mock_urlopen(remote_schema)
        with patch('urllib.request.urlopen', return_value=mock_cm) as mock_open:
            resolved = _resolve_refs(schema, {}, set(), 'http://example.com/root.json')

        mock_open.assert_called_once()
        assert resolved == {'type': 'string', 'description': 'downloaded'}

    def test_circular_reference_logs_warning(self) -> None:
        """Circular $ref triggers a logger.warning call."""
        uri_a = 'http://example.com/a.json'
        uri_b = 'http://example.com/b.json'
        schema_a = {'ref_to_b': {'$ref': uri_b}}
        schema_b = {'ref_to_a': {'$ref': uri_a}}
        cache = {uri_a: schema_a, uri_b: schema_b}

        with patch('awslabs.allotrope_mcp_server.server.logger') as mock_logger:
            _resolve_refs({'$ref': uri_a}, cache, set(), 'http://example.com/root.json')

        mock_logger.warning.assert_called()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert 'Circular $ref detected' in warning_msg

    def test_cache_reuse_no_duplicate_download(self) -> None:
        """Same URI referenced twice only triggers one HTTP download."""
        remote_schema = {'type': 'integer'}
        schema = {
            'field_a': {'$ref': 'http://example.com/shared.json'},
            'field_b': {'$ref': 'http://example.com/shared.json'},
        }

        mock_cm = self._mock_urlopen(remote_schema)
        with patch('urllib.request.urlopen', return_value=mock_cm) as mock_open:
            _resolve_refs(schema, {}, set(), 'http://example.com/root.json')

        mock_open.assert_called_once()

    def test_fragment_navigation(self) -> None:
        """Fragment pointer navigates to the correct nested definition."""
        cached_schema = {
            'definitions': {
                'MyType': {'type': 'boolean', 'description': 'nested'}
            }
        }
        cache = {'http://example.com/defs.json': cached_schema}
        schema = {'$ref': 'http://example.com/defs.json#/definitions/MyType'}

        resolved = _resolve_refs(schema, cache, set(), 'http://example.com/root.json')

        assert resolved == {'type': 'boolean', 'description': 'nested'}

    def test_nested_dict_recursion(self) -> None:
        """Nested dicts without $ref pass through unchanged."""
        schema = {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'age': {'type': 'integer'},
            },
        }

        resolved = _resolve_refs(schema, {}, set(), 'http://example.com/root.json')

        assert resolved == schema

    def test_list_recursion(self) -> None:
        """$ref entries inside list items are resolved."""
        uri = 'http://example.com/item.json'
        cache = {uri: {'type': 'number'}}
        schema = {
            'oneOf': [
                {'$ref': uri},
                {'type': 'string'},
            ]
        }

        resolved = _resolve_refs(schema, cache, set(), 'http://example.com/root.json')

        assert resolved == {
            'oneOf': [
                {'type': 'number'},
                {'type': 'string'},
            ]
        }
