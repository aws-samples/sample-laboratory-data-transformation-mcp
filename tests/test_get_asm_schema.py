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

from awslabs.allotrope_mcp_server.server import (
    _generate_embed_filename,
    _normalize_schema_id,
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
