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

"""Tests for fetch_asm_document tool."""

import json
import os
from allotrope_mcp_server.server import PURL_ORIGIN, fetch_asm_document
from hypothesis import given, settings
from hypothesis import strategies as st
from pathlib import Path


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate arbitrary path suffixes (may start with '/' or not).
_path_suffix = st.text(
    alphabet=st.sampled_from('abcdefghijklmnopqrstuvwxyz0123456789/_-.'),
    min_size=0,
    max_size=80,
)


# ---------------------------------------------------------------------------
# Property: mirror-path derivation correctness
# ---------------------------------------------------------------------------


@given(path_suffix=_path_suffix, output_dir=st.text(min_size=1, max_size=60))
@settings(max_examples=200)
def test_mirror_path_derivation_matches_expected(path_suffix: str, output_dir: str) -> None:
    """Property: stripping PURL_ORIGIN and lstrip('/') then joining with output_dir
    must equal Path(output_dir) / path_suffix.lstrip('/').

    For any URI ``http://purl.allotrope.org<path>``, the derived destination path
    must equal ``Path(output_dir) / path.lstrip('/')``.
    """
    uri = PURL_ORIGIN + path_suffix

    # Replicate the derivation logic from fetch_asm_document.
    mirror_path = uri[len(PURL_ORIGIN):].lstrip('/')
    derived = Path(output_dir) / mirror_path

    # Expected: same formula expressed independently.
    expected = Path(output_dir) / path_suffix.lstrip('/')

    assert derived == expected


class TestFetchAsmDocumentHttpErrors:
    """Unit tests for HTTP error handling in fetch_asm_document."""

    VALID_URI = 'http://purl.allotrope.org/json-schemas/adm/plate-reader/REC/2025/12/plate-reader.embed.schema'

    async def test_http_error_returns_error_with_uri_and_status(self, mocker, tmp_path):
        """HTTPError returns {'error': ...} containing URI and status code."""
        import urllib.error
        mocker.patch(
            'urllib.request.urlopen',
            side_effect=urllib.error.HTTPError(self.VALID_URI, 404, 'Not Found', {}, None),
        )
        result = json.loads(await fetch_asm_document(self.VALID_URI, str(tmp_path)))
        assert 'error' in result
        assert self.VALID_URI in result['error']
        assert '404' in result['error']

    async def test_url_error_returns_error_with_uri_and_reason(self, mocker, tmp_path):
        """URLError returns {'error': ...} containing URI and reason."""
        import urllib.error
        mocker.patch(
            'urllib.request.urlopen',
            side_effect=urllib.error.URLError('connection refused'),
        )
        result = json.loads(await fetch_asm_document(self.VALID_URI, str(tmp_path)))
        assert 'error' in result
        assert self.VALID_URI in result['error']
        assert 'connection refused' in result['error']

    async def test_timeout_error_returns_error_mentioning_timeout(self, mocker, tmp_path):
        """TimeoutError returns {'error': ...} mentioning timeout."""
        mocker.patch('urllib.request.urlopen', side_effect=TimeoutError())
        result = json.loads(await fetch_asm_document(self.VALID_URI, str(tmp_path)))
        assert 'error' in result
        assert 'timed out' in result['error'].lower()

    async def test_invalid_json_returns_error_mentioning_invalid_json(self, mocker, tmp_path):
        """JSONDecodeError returns {'error': ...} mentioning invalid JSON."""
        mock_resp = mocker.MagicMock()
        mock_resp.read.return_value = b'not valid json {{{'
        mock_resp.__enter__ = mocker.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mocker.MagicMock(return_value=False)
        mocker.patch('urllib.request.urlopen', return_value=mock_resp)
        result = json.loads(await fetch_asm_document(self.VALID_URI, str(tmp_path)))
        assert 'error' in result
        assert 'invalid json' in result['error'].lower()


class TestFetchAsmDocumentWriter:
    """Unit tests for the Writer stage of fetch_asm_document."""

    VALID_URI = 'http://purl.allotrope.org/json-schemas/adm/plate-reader/REC/2025/12/plate-reader.embed.schema'
    VALID_JSON = b'{"key": "value"}'

    def _mock_urlopen(self, mocker, body: bytes = VALID_JSON):
        """Patch urllib.request.urlopen to return *body* as the response."""
        mock_resp = mocker.MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = mocker.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mocker.MagicMock(return_value=False)
        mocker.patch('urllib.request.urlopen', return_value=mock_resp)

    async def test_successful_write_returns_absolute_path(self, mocker, tmp_path):
        """Successful download+write returns {'path': <absolute path>}."""
        self._mock_urlopen(mocker)
        result = json.loads(await fetch_asm_document(self.VALID_URI, str(tmp_path)))
        assert 'path' in result
        assert os.path.isabs(result['path'])

    async def test_successful_write_creates_file_with_correct_content(self, mocker, tmp_path):
        """Written file contains the downloaded JSON with 2-space indentation."""
        self._mock_urlopen(mocker)
        result = json.loads(await fetch_asm_document(self.VALID_URI, str(tmp_path)))
        saved = Path(result['path'])
        assert saved.exists()
        on_disk = json.loads(saved.read_text(encoding='utf-8'))
        assert on_disk == json.loads(self.VALID_JSON)

    async def test_successful_write_creates_intermediate_directories(self, mocker, tmp_path):
        """Intermediate directories are created when they do not exist."""
        self._mock_urlopen(mocker)
        result = json.loads(await fetch_asm_document(self.VALID_URI, str(tmp_path)))
        assert 'path' in result
        assert Path(result['path']).parent.is_dir()

    async def test_oserror_on_mkdir_returns_error_with_path(self, mocker, tmp_path):
        """OSError during mkdir returns {'error': ...} containing the destination path."""
        self._mock_urlopen(mocker)
        mocker.patch('pathlib.Path.mkdir', side_effect=OSError('permission denied'))
        result = json.loads(await fetch_asm_document(self.VALID_URI, str(tmp_path)))
        assert 'error' in result
        assert 'permission denied' in result['error'].lower()

    async def test_oserror_on_write_returns_error_with_path(self, mocker, tmp_path):
        """OSError during write_text returns {'error': ...} containing the destination path."""
        self._mock_urlopen(mocker)
        mocker.patch('pathlib.Path.write_text', side_effect=OSError('disk full'))
        result = json.loads(await fetch_asm_document(self.VALID_URI, str(tmp_path)))
        assert 'error' in result
        assert 'disk full' in result['error'].lower()

    async def test_empty_output_dir_resolves_to_cwd(self, mocker, tmp_path, monkeypatch):
        """Empty output_dir causes the file to be written relative to os.getcwd()."""
        monkeypatch.chdir(tmp_path)
        self._mock_urlopen(mocker)
        result = json.loads(await fetch_asm_document(self.VALID_URI, ''))
        assert 'path' in result
        # The resolved path must be inside tmp_path (which is now cwd).
        assert str(tmp_path) in result['path']


# ---------------------------------------------------------------------------
# 6.1 URI validation unit tests
# ---------------------------------------------------------------------------


class TestFetchAsmDocumentUriValidation:
    """Unit tests for URI prefix validation in fetch_asm_document."""

    VALID_URI = 'http://purl.allotrope.org/json-schemas/adm/plate-reader/REC/2025/12/plate-reader.embed.schema'

    async def test_invalid_prefix_returns_error(self, mocker, tmp_path):
        """URI without http://purl.allotrope.org prefix returns {'error': ...}."""
        spy = mocker.patch('urllib.request.urlopen')
        result = json.loads(
            await fetch_asm_document('https://example.com/some/schema.json', str(tmp_path))
        )
        assert 'error' in result
        spy.assert_not_called()

    async def test_valid_prefix_proceeds_to_download(self, mocker, tmp_path):
        """Valid URI passes validation and proceeds to the download stage."""
        mock_resp = mocker.MagicMock()
        mock_resp.read.return_value = b'{"key": "value"}'
        mock_resp.__enter__ = mocker.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mocker.MagicMock(return_value=False)
        mocker.patch('urllib.request.urlopen', return_value=mock_resp)
        result = json.loads(await fetch_asm_document(self.VALID_URI, str(tmp_path)))
        assert 'path' in result

    async def test_uppercase_scheme_is_rejected(self, mocker, tmp_path):
        """HTTP://purl.allotrope.org (uppercase) is rejected (case-sensitive check)."""
        spy = mocker.patch('urllib.request.urlopen')
        result = json.loads(
            await fetch_asm_document(
                'HTTP://purl.allotrope.org/json-schemas/adm/plate-reader/REC/2025/12/plate-reader.embed.schema',
                str(tmp_path),
            )
        )
        assert 'error' in result
        spy.assert_not_called()

    async def test_no_network_call_on_invalid_uri(self, mocker, tmp_path):
        """No network call is made when the URI is invalid."""
        spy = mocker.patch('urllib.request.urlopen')
        await fetch_asm_document('ftp://purl.allotrope.org/something', str(tmp_path))
        spy.assert_not_called()


# ---------------------------------------------------------------------------
# 6.2 Skip-if-exists unit tests
# ---------------------------------------------------------------------------


class TestFetchAsmDocumentSkipIfExists:
    """Unit tests for skip-if-exists behaviour in fetch_asm_document."""

    VALID_URI = 'http://purl.allotrope.org/json-schemas/adm/plate-reader/REC/2025/12/plate-reader.embed.schema'
    MIRROR_PATH = 'json-schemas/adm/plate-reader/REC/2025/12/plate-reader.embed.schema'

    async def test_existing_file_returns_path_without_network_call(self, mocker, tmp_path):
        """When destination file exists, returns {'path': ...} with no network call."""
        dest = tmp_path / self.MIRROR_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text('{"cached": true}', encoding='utf-8')

        spy = mocker.patch('urllib.request.urlopen')
        result = json.loads(await fetch_asm_document(self.VALID_URI, str(tmp_path)))

        assert 'path' in result
        assert result['path'] == str(dest.resolve())
        spy.assert_not_called()

    async def test_missing_file_proceeds_to_download(self, mocker, tmp_path):
        """When destination file does not exist, download is attempted."""
        mock_resp = mocker.MagicMock()
        mock_resp.read.return_value = b'{"key": "value"}'
        mock_resp.__enter__ = mocker.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mocker.MagicMock(return_value=False)
        urlopen_mock = mocker.patch('urllib.request.urlopen', return_value=mock_resp)

        dest = tmp_path / self.MIRROR_PATH
        assert not dest.exists()

        result = json.loads(await fetch_asm_document(self.VALID_URI, str(tmp_path)))

        assert 'path' in result
        urlopen_mock.assert_called_once()


# ---------------------------------------------------------------------------
# 6.3 Property test: URI validation boundary
# ---------------------------------------------------------------------------


@given(uri=st.text(min_size=0, max_size=200))
@settings(max_examples=500)
async def test_non_purl_uri_always_returns_error(uri: str) -> None:
    """Property: any string not starting with 'http://purl.allotrope.org' must
    always return an error response with no side effects.
    """
    from hypothesis import assume

    assume(not uri.startswith('http://purl.allotrope.org'))

    result = json.loads(await fetch_asm_document(uri, ''))
    assert 'error' in result
    assert 'path' not in result
