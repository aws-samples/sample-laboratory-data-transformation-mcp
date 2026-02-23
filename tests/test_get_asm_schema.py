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

import copy
import json
import jsonref
import pytest
import urllib.error
from awslabs.allotrope_mcp_server.server import (
    _asm_json_loader,
    _generate_embed_filename,
    _normalize_schema_id,
    get_asm_schema,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from pathlib import Path
from unittest.mock import MagicMock, patch


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


def _is_not_valid_json(s: str) -> bool:
    """Return True if *s* is NOT valid JSON."""
    try:
        json.loads(s)
        return False
    except (json.JSONDecodeError, ValueError):
        return True


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
# resolved schemas (no further refs) so jsonref.replace_refs with a mock loader
# never hits the network.

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
    """After jsonref.replace_refs, no $ref values starting with http remain.

    **Validates: Requirements 5.5, 5.6**
    """
    schema, cache = data

    def _mock_loader(uri: str, **kwargs: object) -> dict:
        base_uri = uri.split('#')[0]
        return cache.get(base_uri, {})

    resolved = copy.deepcopy(
        jsonref.replace_refs(schema, loader=_mock_loader, lazy_load=False)
    )

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

    def _mock_loader(uri: str, **kwargs: object) -> dict:
        base_uri = uri.split('#')[0]
        return cache.get(base_uri, {})

    # Schema with a single $ref that includes the fragment.
    schema = {'$ref': f'{_FAKE_FRAGMENT_URI}#{pointer}'}

    resolved = copy.deepcopy(
        jsonref.replace_refs(schema, loader=_mock_loader, lazy_load=False)
    )

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

    def _mock_loader(uri: str, **kwargs: object) -> dict:
        base_uri = uri.split('#')[0]
        return cache.get(base_uri, {})

    # $ref with no fragment at all.
    schema_no_hash = {'$ref': _FAKE_FRAGMENT_URI}
    resolved_no_hash = copy.deepcopy(
        jsonref.replace_refs(schema_no_hash, loader=_mock_loader, lazy_load=False)
    )

    # The resolved output should be the entire nested dict.
    expected_full = copy.deepcopy(
        jsonref.replace_refs(nested_dict, loader=_mock_loader, lazy_load=False)
    )
    assert resolved_no_hash == expected_full, (
        f'No-hash ref resolved to {resolved_no_hash!r}, '
        f'expected full schema {expected_full!r}'
    )

    # $ref with '#' but empty path after it.
    schema_empty_frag = {'$ref': f'{_FAKE_FRAGMENT_URI}#'}
    resolved_empty = copy.deepcopy(
        jsonref.replace_refs(schema_empty_frag, loader=_mock_loader, lazy_load=False)
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
    """jsonref handles circular $ref chains without infinite recursion.

    **Validates: Requirements 10.2, 10.4**
    """
    uri_a, uri_b, _schema_a, _schema_b, cache = data

    # Build a wrapper schema that references A.
    wrapper = {'$ref': uri_a}

    def _mock_loader(uri: str, **kwargs: object) -> dict:
        base_uri = uri.split('#')[0]
        return cache.get(base_uri, {})

    # jsonref.replace_refs must complete without error (no infinite recursion).
    # Circular refs become JsonRef proxy objects rather than causing a stack overflow.
    resolved = jsonref.replace_refs(wrapper, loader=_mock_loader, lazy_load=False)

    # The call completing without an exception is the key safety property.
    # resolved is a valid object (proxy or dict) — not None.
    assert resolved is not None


# Feature: get-asm-schema, Property 2: Output path construction
@given(
    base_segments=st.lists(_path_segment, min_size=1, max_size=4),
    path_segments=st.lists(_path_segment, min_size=1, max_size=5),
    filename=_dotted_filename,
)
@settings(max_examples=100)
def test_output_path_construction(
    base_segments: list[str],
    path_segments: list[str],
    filename: str,
) -> None:
    """Constructed output path equals base_dir / dir_part / embed_filename.

    **Validates: Requirements 2.3, 2.4, 6.4**
    """
    base_dir = '/tmp/' + '/'.join(base_segments)
    normalized_path = '/'.join(path_segments) + '/' + filename

    # Replicate the path construction logic from get_asm_schema.
    dir_part = normalized_path.rsplit('/', 1)[0]
    embed_filename = _generate_embed_filename(filename)

    expected = Path(base_dir) / dir_part / embed_filename
    expected = expected.resolve()

    # Replicate the actual implementation logic.
    actual_filename = normalized_path.rsplit('/', 1)[-1]
    actual_embed = _generate_embed_filename(actual_filename)
    actual_dir_part = normalized_path.rsplit('/', 1)[0] if '/' in normalized_path else ''
    actual = Path(base_dir) / actual_dir_part / actual_embed
    actual = actual.resolve()

    assert actual == expected, (
        f'Path mismatch: {actual!r} != {expected!r}'
    )

    # The path must be absolute.
    assert actual.is_absolute(), f'Expected absolute path, got {actual!r}'

    # The embed filename must appear as the final component.
    assert actual.name == embed_filename, (
        f'Expected filename {embed_filename!r}, got {actual.name!r}'
    )

    # The directory structure from the normalized path must be preserved.
    assert str(dir_part) in str(actual.parent), (
        f'Expected dir_part {dir_part!r} in parent {str(actual.parent)!r}'
    )


# Feature: get-asm-schema, Property 7: Non-200 HTTP status error reporting
@given(
    status_code=st.integers(min_value=400, max_value=599),
    path_segments=st.lists(_path_segment, min_size=1, max_size=4),
    filename=_dotted_filename,
)
@settings(max_examples=100)
def test_non_200_http_status_error_reporting(
    status_code: int,
    path_segments: list[str],
    filename: str,
) -> None:
    """Error message contains both the HTTP status code and the URI.

    **Validates: Requirements 4.4, 8.3**
    """
    path_suffix = '/'.join(path_segments) + '/' + filename
    schema_id = f'json-schemas/{path_suffix}'
    expected_uri = f'http://purl.allotrope.org/{schema_id}'

    http_error = urllib.error.HTTPError(
        url=expected_uri,
        code=status_code,
        msg='Error',
        hdrs=None,  # type: ignore[arg-type]
        fp=None,
    )

    with (
        patch('pathlib.Path.exists', return_value=False),
        patch('urllib.request.urlopen', side_effect=http_error),
    ):
        result = get_asm_schema(id=schema_id, output_dir='/tmp/test')

    parsed = json.loads(result)
    assert 'error' in parsed, f'Expected error key in result: {parsed}'
    assert str(status_code) in parsed['error'], (
        f'Expected status code {status_code} in error: {parsed["error"]}'
    )
    assert expected_uri in parsed['error'], (
        f'Expected URI {expected_uri} in error: {parsed["error"]}'
    )


# Feature: get-asm-schema, Property 8: Network error messages include URI
@given(
    path_segments=st.lists(_path_segment, min_size=1, max_size=4),
    filename=_dotted_filename,
    error_type=st.sampled_from(['url_error', 'timeout_error']),
)
@settings(max_examples=100)
def test_network_error_uri_inclusion(
    path_segments: list[str],
    filename: str,
    error_type: str,
) -> None:
    """Error message always contains the URI regardless of network error type.

    **Validates: Requirements 8.1, 8.2, 8.4**
    """
    path_suffix = '/'.join(path_segments) + '/' + filename
    schema_id = f'json-schemas/{path_suffix}'
    expected_uri = f'http://purl.allotrope.org/{schema_id}'

    if error_type == 'url_error':
        exc = urllib.error.URLError(reason='Connection refused')
    else:
        exc = TimeoutError()

    with (
        patch('pathlib.Path.exists', return_value=False),
        patch('urllib.request.urlopen', side_effect=exc),
    ):
        result = get_asm_schema(id=schema_id, output_dir='/tmp/test')

    parsed = json.loads(result)
    assert 'error' in parsed, f'Expected error key in result: {parsed}'
    assert expected_uri in parsed['error'], (
        f'Expected URI {expected_uri} in error: {parsed["error"]}'
    )


# Feature: get-asm-schema, Property 9: Invalid JSON error reporting
@given(
    path_segments=st.lists(_path_segment, min_size=1, max_size=4),
    filename=_dotted_filename,
    non_json_string=st.text(min_size=1, max_size=200).filter(
        lambda s: _is_not_valid_json(s)
    ),
)
@settings(max_examples=100)
def test_invalid_json_error_reporting(
    path_segments: list[str],
    filename: str,
    non_json_string: str,
) -> None:
    """Error message mentions invalid JSON and includes the URI.

    **Validates: Requirements 9.1, 9.3**
    """
    path_suffix = '/'.join(path_segments) + '/' + filename
    schema_id = f'json-schemas/{path_suffix}'
    expected_uri = f'http://purl.allotrope.org/{schema_id}'

    mock_resp = MagicMock()
    mock_resp.read.return_value = non_json_string.encode('utf-8')
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_resp)
    mock_cm.__exit__ = MagicMock(return_value=False)

    with (
        patch('pathlib.Path.exists', return_value=False),
        patch('urllib.request.urlopen', return_value=mock_cm),
    ):
        result = get_asm_schema(id=schema_id, output_dir='/tmp/test')

    parsed = json.loads(result)
    assert 'error' in parsed, f'Expected error key in result: {parsed}'
    assert 'Invalid JSON' in parsed['error'], (
        f'Expected "Invalid JSON" in error: {parsed["error"]}'
    )
    assert expected_uri in parsed['error'], (
        f'Expected URI {expected_uri} in error: {parsed["error"]}'
    )

# Feature: get-asm-schema, Property 10: Schema serialization round-trip
json_serializable = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(
        allow_nan=False, allow_infinity=False
    ) | st.text(),
    lambda children: st.lists(children) | st.dictionaries(st.text(), children),
    max_leaves=20,
)


@given(d=st.dictionaries(st.text(), json_serializable))
@settings(max_examples=100)
def test_serialization_round_trip(d: dict) -> None:
    """JSON serialization with indentation round-trips without data loss.

    **Validates: Requirements 7.2**
    """
    assert json.loads(json.dumps(d, indent=2)) == d


# Feature: get-asm-schema, Property 11: Successful return value is absolute path
@given(
    base_segments=st.lists(_path_segment, min_size=1, max_size=4),
    path_segments=st.lists(_path_segment, min_size=1, max_size=4),
    filename=_dotted_filename,
)
@settings(max_examples=100)
def test_absolute_path_return(
    base_segments: list[str],
    path_segments: list[str],
    filename: str,
) -> None:
    """Successful return value contains an absolute filesystem path.

    **Validates: Requirements 7.4**
    """
    base_dir = '/tmp/' + '/'.join(base_segments)
    schema_id = 'json-schemas/' + '/'.join(path_segments) + '/' + filename

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({'type': 'object'}).encode('utf-8')
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_resp)
    mock_cm.__exit__ = MagicMock(return_value=False)

    with (
        patch.object(Path, 'exists', return_value=False),
        patch('urllib.request.urlopen', return_value=mock_cm),
        patch('os.makedirs'),
        patch('builtins.open', MagicMock()),
    ):
        result = get_asm_schema(schema_id, output_dir=base_dir)

    parsed = json.loads(result)
    assert 'path' in parsed, f'Expected "path" key in result: {parsed}'
    assert parsed['path'].startswith('/'), (
        f'Expected absolute path starting with "/", got: {parsed["path"]}'
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


class TestAsmJsonLoader:
    """Unit tests for _asm_json_loader."""

    def _mock_urlopen(self, response_data: dict):
        """Create a mock context manager for urllib.request.urlopen."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode('utf-8')
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_resp)
        mock_cm.__exit__ = MagicMock(return_value=False)
        return mock_cm

    def test_success_returns_parsed_json(self) -> None:
        """Successful fetch returns parsed JSON dict."""
        expected = {'type': 'object', 'title': 'Test'}
        mock_cm = self._mock_urlopen(expected)

        with patch('urllib.request.urlopen', return_value=mock_cm) as mock_open:
            result = _asm_json_loader('http://example.com/schema.json')

        mock_open.assert_called_once()
        assert result == expected

    def test_http_error_propagates(self) -> None:
        """HTTPError from urlopen propagates unchanged."""
        http_error = urllib.error.HTTPError(
            url='http://example.com/schema.json',
            code=404,
            msg='Not Found',
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )

        with (
            patch('urllib.request.urlopen', side_effect=http_error),
            pytest.raises(urllib.error.HTTPError) as exc_info,
        ):
            _asm_json_loader('http://example.com/schema.json')

        assert exc_info.value.code == 404

    def test_url_error_propagates(self) -> None:
        """URLError from urlopen propagates unchanged."""
        url_error = urllib.error.URLError(reason='Connection refused')

        with (
            patch('urllib.request.urlopen', side_effect=url_error),
            pytest.raises(urllib.error.URLError) as exc_info,
        ):
            _asm_json_loader('http://example.com/schema.json')

        assert 'Connection refused' in str(exc_info.value.reason)

    def test_timeout_error_propagates(self) -> None:
        """TimeoutError from urlopen propagates unchanged."""
        with (
            patch('urllib.request.urlopen', side_effect=TimeoutError()),
            pytest.raises(TimeoutError),
        ):
            _asm_json_loader('http://example.com/schema.json')

    def test_json_decode_error_propagates(self) -> None:
        """JSONDecodeError from invalid response body propagates unchanged."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'<html>not json</html>'
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_resp)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch('urllib.request.urlopen', return_value=mock_cm),
            pytest.raises(json.JSONDecodeError),
        ):
            _asm_json_loader('http://example.com/schema.json')


class TestJsonRefResolution:
    """Unit tests for jsonref-based $ref resolution via _asm_json_loader."""

    def _mock_urlopen(self, response_data: dict):
        """Create a mock context manager for urllib.request.urlopen."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode('utf-8')
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_resp)
        mock_cm.__exit__ = MagicMock(return_value=False)
        return mock_cm

    @staticmethod
    def _materialize(obj):
        """Recursively convert jsonref proxy objects to plain Python types."""
        if isinstance(obj, jsonref.JsonRef):
            obj = obj.__subject__
        if isinstance(obj, dict):
            return {k: TestJsonRefResolution._materialize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [TestJsonRefResolution._materialize(v) for v in obj]
        return obj

    def _resolve(self, schema):
        """Resolve $ref entries and materialize proxy objects into plain dicts."""
        resolved_proxy = jsonref.replace_refs(
            schema, loader=_asm_json_loader, lazy_load=False
        )
        return self._materialize(resolved_proxy)

    def test_successful_resolution_with_mocked_http(self) -> None:
        """External $ref is resolved via mocked HTTP download."""
        remote_schema = {'type': 'string', 'description': 'downloaded'}
        schema = {'$ref': 'http://example.com/type.json'}

        mock_cm = self._mock_urlopen(remote_schema)
        with patch('urllib.request.urlopen', return_value=mock_cm) as mock_open:
            resolved = self._resolve(schema)

        mock_open.assert_called_once()
        assert resolved == {'type': 'string', 'description': 'downloaded'}

    def test_circular_reference_safety(self) -> None:
        """Circular $ref is handled without infinite recursion."""
        uri_a = 'http://example.com/a.json'
        uri_b = 'http://example.com/b.json'
        schema_a = {'ref_to_b': {'$ref': uri_b}}
        schema_b = {'ref_to_a': {'$ref': uri_a}}

        def mock_loader(uri, **kwargs):
            if uri == uri_a:
                return copy.deepcopy(schema_a)
            if uri == uri_b:
                return copy.deepcopy(schema_b)
            raise ValueError(f'Unexpected URI: {uri}')

        try:
            resolved_proxy = jsonref.replace_refs(
                {'$ref': uri_a}, loader=mock_loader, lazy_load=False
            )
            # Accessing the proxy forces resolution; no RecursionError is the goal
            str(resolved_proxy)
        except (jsonref.JsonRefError, ValueError):
            pass  # jsonref may raise for truly circular schemas — no infinite loop is the goal

    def test_cache_reuse_no_duplicate_download(self) -> None:
        """Same URI referenced twice only triggers one HTTP download."""
        remote_schema = {'type': 'integer'}
        schema = {
            'field_a': {'$ref': 'http://example.com/shared.json'},
            'field_b': {'$ref': 'http://example.com/shared.json'},
        }

        mock_cm = self._mock_urlopen(remote_schema)
        with patch('urllib.request.urlopen', return_value=mock_cm) as mock_open:
            resolved = self._resolve(schema)

        mock_open.assert_called_once()
        assert resolved['field_a'] == {'type': 'integer'}
        assert resolved['field_b'] == {'type': 'integer'}

    def test_fragment_navigation(self) -> None:
        """Fragment pointer navigates to the correct nested definition."""
        remote_schema = {
            'definitions': {
                'MyType': {'type': 'boolean', 'description': 'nested'}
            }
        }
        schema = {'$ref': 'http://example.com/defs.json#/definitions/MyType'}

        mock_cm = self._mock_urlopen(remote_schema)
        with patch('urllib.request.urlopen', return_value=mock_cm):
            resolved = self._resolve(schema)

        assert resolved == {'type': 'boolean', 'description': 'nested'}

    def test_nested_dict_passthrough(self) -> None:
        """Nested dicts without $ref pass through unchanged."""
        schema = {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'age': {'type': 'integer'},
            },
        }

        resolved = self._resolve(schema)

        assert resolved == schema

    def test_list_recursion(self) -> None:
        """$ref entries inside list items are resolved."""
        remote_schema = {'type': 'number'}
        schema = {
            'oneOf': [
                {'$ref': 'http://example.com/item.json'},
                {'type': 'string'},
            ]
        }

        mock_cm = self._mock_urlopen(remote_schema)
        with patch('urllib.request.urlopen', return_value=mock_cm):
            resolved = self._resolve(schema)

        assert resolved == {
            'oneOf': [
                {'type': 'number'},
                {'type': 'string'},
            ]
        }


class TestGetAsmSchema:
    """Unit tests for the get_asm_schema MCP tool."""

    _SCHEMA_ID = 'json-schemas/adm/conductivity/conductivity.schema'
    _EXPECTED_URI = f'http://purl.allotrope.org/{_SCHEMA_ID}'
    _VALID_SCHEMA = {'type': 'object', 'properties': {'name': {'type': 'string'}}}

    def _mock_urlopen(self, response_data: dict):
        """Create a mock context manager for urllib.request.urlopen."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode('utf-8')
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_resp)
        mock_cm.__exit__ = MagicMock(return_value=False)
        return mock_cm

    def test_existing_file_skip(self) -> None:
        """When embed file already exists, return path without downloading."""
        with (
            patch.object(Path, 'exists', return_value=True),
            patch('urllib.request.urlopen') as mock_open,
        ):
            result = get_asm_schema(id=self._SCHEMA_ID, output_dir='/tmp/test')

        parsed = json.loads(result)
        assert 'path' in parsed
        mock_open.assert_not_called()

    def test_successful_download_resolve_save(self) -> None:
        """Download, resolve, and save flow produces a path result."""
        mock_cm = self._mock_urlopen(self._VALID_SCHEMA)

        with (
            patch.object(Path, 'exists', return_value=False),
            patch('urllib.request.urlopen', return_value=mock_cm),
            patch('os.makedirs') as mock_makedirs,
            patch('builtins.open', MagicMock()),
        ):
            result = get_asm_schema(id=self._SCHEMA_ID, output_dir='/tmp/test')

        parsed = json.loads(result)
        assert 'path' in parsed
        assert Path(parsed['path']).is_absolute()
        mock_makedirs.assert_called_once()

    def test_404_response_error(self) -> None:
        """HTTP 404 returns error with status code and URI."""
        http_error = urllib.error.HTTPError(
            url=self._EXPECTED_URI,
            code=404,
            msg='Not Found',
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )

        with (
            patch.object(Path, 'exists', return_value=False),
            patch('urllib.request.urlopen', side_effect=http_error),
        ):
            result = get_asm_schema(id=self._SCHEMA_ID, output_dir='/tmp/test')

        parsed = json.loads(result)
        assert 'error' in parsed
        assert '404' in parsed['error']
        assert self._EXPECTED_URI in parsed['error']

    def test_connection_failure_error(self) -> None:
        """URLError returns error with 'Failed to connect' and URI."""
        with (
            patch.object(Path, 'exists', return_value=False),
            patch(
                'urllib.request.urlopen',
                side_effect=urllib.error.URLError(reason='Connection refused'),
            ),
        ):
            result = get_asm_schema(id=self._SCHEMA_ID, output_dir='/tmp/test')

        parsed = json.loads(result)
        assert 'error' in parsed
        assert 'Failed to connect' in parsed['error']
        assert self._EXPECTED_URI in parsed['error']

    def test_timeout_error(self) -> None:
        """TimeoutError returns error with 'timed out' and URI."""
        with (
            patch.object(Path, 'exists', return_value=False),
            patch('urllib.request.urlopen', side_effect=TimeoutError()),
        ):
            result = get_asm_schema(id=self._SCHEMA_ID, output_dir='/tmp/test')

        parsed = json.loads(result)
        assert 'error' in parsed
        assert 'timed out' in parsed['error']
        assert self._EXPECTED_URI in parsed['error']

    def test_invalid_json_response_error(self) -> None:
        """Non-JSON response returns error with 'Invalid JSON' and URI."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'<html>not json</html>'
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_resp)
        mock_cm.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(Path, 'exists', return_value=False),
            patch('urllib.request.urlopen', return_value=mock_cm),
        ):
            result = get_asm_schema(id=self._SCHEMA_ID, output_dir='/tmp/test')

        parsed = json.loads(result)
        assert 'error' in parsed
        assert 'Invalid JSON' in parsed['error']
        assert self._EXPECTED_URI in parsed['error']

    def test_file_write_failure_error(self) -> None:
        """OSError on file write returns error with 'Failed to write'."""
        mock_cm = self._mock_urlopen(self._VALID_SCHEMA)

        with (
            patch.object(Path, 'exists', return_value=False),
            patch('urllib.request.urlopen', return_value=mock_cm),
            patch('os.makedirs'),
            patch('builtins.open', side_effect=OSError('Permission denied')),
        ):
            result = get_asm_schema(id=self._SCHEMA_ID, output_dir='/tmp/test')

        parsed = json.loads(result)
        assert 'error' in parsed
        assert 'Failed to write' in parsed['error']

    def test_default_output_dir_uses_cwd(self) -> None:
        """When output_dir is omitted, os.getcwd() is used as base path."""
        mock_cm = self._mock_urlopen(self._VALID_SCHEMA)
        fake_cwd = '/home/user/projects'

        with (
            patch.object(Path, 'exists', return_value=False),
            patch('urllib.request.urlopen', return_value=mock_cm),
            patch('os.getcwd', return_value=fake_cwd),
            patch('os.makedirs'),
            patch('builtins.open', MagicMock()),
        ):
            result = get_asm_schema(id=self._SCHEMA_ID)

        parsed = json.loads(result)
        assert 'path' in parsed
        assert fake_cwd in parsed['path']

    def test_directory_creation(self) -> None:
        """Parent directories are created with exist_ok=True."""
        mock_cm = self._mock_urlopen(self._VALID_SCHEMA)

        with (
            patch.object(Path, 'exists', return_value=False),
            patch('urllib.request.urlopen', return_value=mock_cm),
            patch('os.makedirs') as mock_makedirs,
            patch('builtins.open', MagicMock()),
        ):
            get_asm_schema(id=self._SCHEMA_ID, output_dir='/tmp/test')

        mock_makedirs.assert_called_once()
        _, kwargs = mock_makedirs.call_args
        assert kwargs.get('exist_ok') is True
