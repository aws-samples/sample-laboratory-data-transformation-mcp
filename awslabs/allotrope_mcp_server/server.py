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

"""awslabs allotrope MCP Server implementation."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from jsonschema import Draft202012Validator
from loguru import logger
from mcp.server.fastmcp import FastMCP
from pathlib import Path


mcp = FastMCP(
    'awslabs.allotrope-mcp-server',
    instructions=(
        'This MCP server provides tools to convert instrument data files into'
        ' standardized Allotrope Simple Model (ASM) format.'
    ),
    dependencies=[
        'jsonschema',
        'loguru',
        'pydantic',
    ],
)

_GITLAB_TREE_URL = 'https://gitlab.com/api/v4/projects/42714196/repository/tree'
_GITLAB_REF = 'main'
_GITLAB_PATH = 'json-schemas/adm'
_GITLAB_TIMEOUT_SECONDS = 30

_PURL_PREFIX = 'http://purl.allotrope.org/'
_JSON_SCHEMAS_PREFIX = 'json-schemas/'


def _normalize_schema_id(schema_id: str) -> str:
    """Parse a flexible schema identifier into a normalized path.

    Accepts full URIs, ``json-schemas/``-prefixed paths, or bare suffixes
    and returns a path starting with ``json-schemas/``.

    Args:
        schema_id: The user-provided schema identifier.

    Returns:
        Normalized path starting with ``json-schemas/``.
    """
    path = schema_id
    if _PURL_PREFIX in path:
        path = path.split(_PURL_PREFIX, 1)[1]
    if _JSON_SCHEMAS_PREFIX in path:
        path = path[path.index(_JSON_SCHEMAS_PREFIX):]
    else:
        path = _JSON_SCHEMAS_PREFIX + path
    return path


def _generate_embed_filename(filename: str) -> str:
    """Transform a schema filename into its embed variant.

    Inserts ``.embed`` before the extension portion and ensures the result
    ends with ``.json``.

    Args:
        filename: Original schema filename (e.g. ``conductivity.schema``).

    Returns:
        Embed filename (e.g. ``conductivity.embed.schema.json``).
    """
    dot_idx = filename.index('.')
    name_part = filename[:dot_idx]
    ext_part = filename[dot_idx:]
    result = f'{name_part}.embed{ext_part}'
    if not result.endswith('.json'):
        result += '.json'
    return result

def _resolve_refs(
    schema: dict, cache: dict[str, dict], resolving: set[str], current_uri: str
) -> dict:
    """Recursively resolve all external ``$ref`` references in a JSON schema.

    Walks the schema dict and replaces each external ``$ref`` (URI starting
    with ``http``) with the referenced definition downloaded and parsed from
    the remote server.  A per-invocation ``cache`` avoids duplicate downloads
    and a ``resolving`` set detects circular reference chains.

    Args:
        schema: The JSON schema dict to resolve.
        cache: Mutable mapping of URI to parsed JSON, shared across recursion.
        resolving: Mutable set of URIs currently on the resolution stack.
        current_uri: The URI of the schema being resolved (used for logging).

    Returns:
        A new dict with all resolvable ``$ref`` values replaced inline.
    """
    result: dict = {}
    for key, value in schema.items():
        if key == '$ref' and isinstance(value, str) and value.startswith('http'):
            parts = value.split('#', 1)
            base_uri = parts[0]
            fragment = parts[1] if len(parts) > 1 else ''

            if base_uri in resolving:
                logger.warning(
                    f'Circular $ref detected: {base_uri} '
                    f'(while resolving {current_uri})'
                )
                result[key] = value
                continue

            # Download or retrieve from cache
            if base_uri not in cache:
                req = urllib.request.Request(base_uri, method='GET')
                with urllib.request.urlopen(req, timeout=_GITLAB_TIMEOUT_SECONDS) as resp:
                    body = resp.read().decode('utf-8')
                    cache[base_uri] = json.loads(body)

            ref_schema = cache[base_uri]

            # Navigate to fragment path (decode JSON Pointer escapes per RFC 6901)
            if fragment:
                segments = [s for s in fragment.split('/') if s]
                definition = ref_schema
                for segment in segments:
                    segment = segment.replace('~1', '/').replace('~0', '~')
                    definition = definition[segment]
            else:
                definition = ref_schema

            # Recursively resolve the extracted definition
            resolving.add(base_uri)
            if isinstance(definition, dict):
                resolved = _resolve_refs(definition, cache, resolving, base_uri)
            else:
                resolved = definition
            resolving.discard(base_uri)

            # Replace the entire $ref node with the resolved definition
            return resolved

        elif isinstance(value, dict):
            result[key] = _resolve_refs(value, cache, resolving, current_uri)
        elif isinstance(value, list):
            result[key] = [
                _resolve_refs(item, cache, resolving, current_uri)
                if isinstance(item, dict)
                else item
                for item in value
            ]
        else:
            result[key] = value

    return result



def _fetch_asm_techniques() -> list[str]:
    """Fetch ASM technique names from the GitLab repository tree API.

    Queries the Allotrope GitLab repository for subdirectories under
    ``json-schemas/adm/``, following pagination until all pages are consumed.

    Returns:
        Sorted list of technique directory names.

    Raises:
        urllib.error.HTTPError: If the API returns a non-2xx status.
        urllib.error.URLError: If a network/connection error occurs.
        TimeoutError: If an individual request exceeds the timeout.
        json.JSONDecodeError: If the response body is not valid JSON.
    """
    logger.info('Fetching ASM techniques from GitLab repository')
    techniques: list[str] = []
    page = 1

    try:
        while True:
            params = urllib.parse.urlencode(
                {
                    'ref': _GITLAB_REF,
                    'path': _GITLAB_PATH,
                    'page': page,
                }
            )
            url = f'{_GITLAB_TREE_URL}?{params}'
            req = urllib.request.Request(url, method='GET')

            try:
                with urllib.request.urlopen(req, timeout=_GITLAB_TIMEOUT_SECONDS) as resp:
                    body = resp.read().decode('utf-8')
                    entries = json.loads(body)
                    techniques.extend(
                        entry['name'] for entry in entries if entry.get('type') == 'tree'
                    )
                    next_page = resp.headers.get('x-next-page', '').strip()
                    if not next_page:
                        break
                    page = int(next_page)
            except TimeoutError:
                raise
            except urllib.error.HTTPError:
                raise
            except urllib.error.URLError:
                raise

        logger.info(f'Fetched {len(techniques)} ASM techniques')
    except Exception:
        logger.error('Failed to fetch ASM techniques from GitLab')
        raise

    return techniques


@dataclass
class ValidationError:
    """A single validation error from JSON Schema validation."""

    path: str
    message: str
    validator: str


@dataclass
class ValidationResult:
    """Result of validating an ASM document against a schema."""

    is_valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    error_message: str | None = None


def validate_asm_document(document_path: str, schema_path: str) -> ValidationResult:
    """Validate an ASM JSON document against a JSON Schema.

    Reads both files, validates using Draft 2020-12, and returns a
    structured result. Never raises exceptions.
    """
    # Read document
    try:
        with open(document_path) as f:
            document_text = f.read()
    except FileNotFoundError:
        return ValidationResult(
            is_valid=False,
            error_message=f'Document file not found: {document_path}',
        )

    try:
        document = json.loads(document_text)
    except json.JSONDecodeError:
        return ValidationResult(
            is_valid=False,
            error_message=f'Document file contains malformed JSON: {document_path}',
        )

    # Read schema
    try:
        with open(schema_path) as f:
            schema_text = f.read()
    except FileNotFoundError:
        return ValidationResult(
            is_valid=False,
            error_message=f'Schema file not found: {schema_path}',
        )

    try:
        schema = json.loads(schema_text)
    except json.JSONDecodeError:
        return ValidationResult(
            is_valid=False,
            error_message=f'Schema file contains malformed JSON: {schema_path}',
        )

    # Validate
    validator = Draft202012Validator(schema)
    errors = [
        ValidationError(
            path='.'.join(str(p) for p in err.absolute_path) or '(root)',
            message=err.message,
            validator=err.validator,
        )
        for err in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    ]

    return ValidationResult(is_valid=len(errors) == 0, errors=errors)


@mcp.tool()
async def list_asm_techniques() -> str:
    """List all available Allotrope Simple Model (ASM) techniques.

    Retrieves technique names from the official Allotrope GitLab repository
    by querying the repository tree API for subdirectories under
    ``json-schemas/adm/``.

    Returns:
        JSON string with a ``techniques`` key containing a list of technique
        names, or an ``error`` key with a description on failure.
    """
    try:
        techniques = _fetch_asm_techniques()
        return json.dumps({'techniques': techniques})
    except urllib.error.HTTPError as exc:
        return json.dumps({'error': f'GitLab API returned HTTP {exc.code}: {exc.reason}'})
    except urllib.error.URLError as exc:
        return json.dumps({'error': f'Failed to connect to GitLab API: {exc.reason}'})
    except TimeoutError:
        return json.dumps({'error': 'GitLab API request timed out'})
    except json.JSONDecodeError:
        return json.dumps({'error': 'GitLab API returned invalid JSON'})
    except Exception as exc:
        return json.dumps({'error': f'Unexpected error: {exc}'})


@mcp.tool()
def validate_asm(asm_document_path: str, asm_schema_path: str) -> str:
    """Validate an ASM JSON document against an Allotrope JSON Schema.

    Args:
        asm_document_path: File path to the ASM JSON document.
        asm_schema_path: File path to the ASM JSON Schema.

    Returns:
        JSON string with validation result.
    """
    result = validate_asm_document(asm_document_path, asm_schema_path)
    d = asdict(result)
    if d['error_message'] is None:
        del d['error_message']
    return json.dumps(d)


@mcp.tool()
def get_asm_schema(id: str, output_dir: str = '') -> str:
    """Download and resolve an Allotrope ASM JSON schema.

    Downloads the schema identified by ``id`` from the official Allotrope PURL
    repository, resolves all ``$ref`` references inline, and saves the fully
    resolved schema to the local filesystem.  If the resolved file already
    exists locally it is returned immediately without downloading.

    Args:
        id: Schema identifier — accepts a full URI
            (``http://purl.allotrope.org/...``), a ``json-schemas/``-prefixed
            path, or a bare suffix path.
        output_dir: Optional base directory for saving the schema.  Defaults
            to the current working directory when empty.

    Returns:
        JSON string with a ``path`` key containing the absolute path to the
        saved file, or an ``error`` key with a description on failure.
    """
    try:
        normalized_path = _normalize_schema_id(id)
        filename = normalized_path.rsplit('/', 1)[-1]
        embed_filename = _generate_embed_filename(filename)

        base_dir = output_dir if output_dir else os.getcwd()
        dir_part = normalized_path.rsplit('/', 1)[0] if '/' in normalized_path else ''
        absolute_path = Path(base_dir) / dir_part / embed_filename
        absolute_path = absolute_path.resolve()

        if absolute_path.exists():
            return json.dumps({'path': str(absolute_path)})

        uri = f'{_PURL_PREFIX}{normalized_path}'

        try:
            req = urllib.request.Request(uri, method='GET')
            with urllib.request.urlopen(req, timeout=_GITLAB_TIMEOUT_SECONDS) as resp:
                body = resp.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            return json.dumps(
                {'error': f'Failed to download {uri}: HTTP {exc.code}'}
            )
        except urllib.error.URLError as exc:
            return json.dumps(
                {'error': f'Failed to connect to {uri}: {exc.reason}'}
            )
        except TimeoutError:
            return json.dumps({'error': f'Request timed out for {uri}'})

        try:
            schema = json.loads(body)
        except json.JSONDecodeError:
            return json.dumps(
                {'error': f'Invalid JSON received from {uri}'}
            )

        cache: dict[str, dict] = {}
        resolving: set[str] = set()
        resolved = _resolve_refs(schema, cache, resolving, uri)

        try:
            os.makedirs(absolute_path.parent, exist_ok=True)
            with open(absolute_path, 'w') as f:
                json.dump(resolved, f, indent=2)
        except OSError as exc:
            return json.dumps(
                {'error': f'Failed to write schema to {absolute_path}: {exc}'}
            )

        return json.dumps({'path': str(absolute_path)})

    except Exception as exc:
        return json.dumps({'error': str(exc)})


def main():
    """Run the MCP server with CLI argument support."""
    logger.info('Starting allotrope MCP server')
    mcp.run()


if __name__ == '__main__':
    main()
