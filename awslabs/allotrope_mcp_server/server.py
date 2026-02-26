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
import jsonref
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from jsonschema import Draft202012Validator
from loguru import logger
from mcp.server.fastmcp import FastMCP
from pathlib import Path
from typing import Any


HTTP_TIMEOUT_SECONDS = 30

PURL_PREFIX = 'http://purl.allotrope.org/'
JSON_SCHEMAS_PREFIX = 'json-schemas/'

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
    if PURL_PREFIX in path:
        path = path.split(PURL_PREFIX, 1)[1]
    if JSON_SCHEMAS_PREFIX in path:
        path = path[path.index(JSON_SCHEMAS_PREFIX) :]
    else:
        path = JSON_SCHEMAS_PREFIX + path
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


def _asm_json_loader(uri: str, **kwargs: Any) -> Any:
    """Fetch and parse a remote JSON schema for jsonref resolution.

    Args:
        uri: The absolute URI to fetch.
        **kwargs: Additional keyword arguments (unused, required by jsonref loader protocol).

    Returns:
        Parsed JSON object (dict or list).

    Raises:
        urllib.error.HTTPError: On non-2xx HTTP responses.
        urllib.error.URLError: On connection failures.
        TimeoutError: When the request exceeds the timeout.
        json.JSONDecodeError: When the response is not valid JSON.
    """
    req = urllib.request.Request(uri, method='GET')
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
        body = resp.read().decode('utf-8')
        return json.loads(body)




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

        uri = f'{PURL_PREFIX}{normalized_path}'

        try:
            req = urllib.request.Request(uri, method='GET')
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
                body = resp.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            return json.dumps({'error': f'Failed to download {uri}: HTTP {exc.code}'})
        except urllib.error.URLError as exc:
            return json.dumps({'error': f'Failed to connect to {uri}: {exc.reason}'})
        except TimeoutError:
            return json.dumps({'error': f'Request timed out for {uri}'})

        try:
            schema = json.loads(body)
        except json.JSONDecodeError:
            return json.dumps({'error': f'Invalid JSON received from {uri}'})

        try:

            def _deep_resolve(obj: Any) -> Any:
                """Recursively convert jsonref proxy objects to plain Python types.

                When *merge_props* is enabled on ``jsonref.replace_refs``, the
                ``JsonRef`` proxy merges sibling keys (e.g. ``$asm.pattern``)
                from the original ``$ref`` object into the resolved target.
                Those merged keys are visible when iterating the proxy as a
                dict but are **not** present on ``__subject__``.  We therefore
                iterate the proxy directly instead of unwrapping it.
                """
                if isinstance(obj, jsonref.JsonRef):
                    # Iterate the proxy (includes merged sibling keys).
                    return {k: _deep_resolve(v) for k, v in obj.items()}
                if isinstance(obj, dict):
                    return {k: _deep_resolve(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [_deep_resolve(item) for item in obj]
                return obj

            refs_replaced = jsonref.replace_refs(
                schema, loader=_asm_json_loader, lazy_load=False, merge_props=True
            )
            resolved = _deep_resolve(refs_replaced)
        except jsonref.JsonRefError as exc:
            cause = exc.__cause__
            ref_uri = exc.uri
            if isinstance(cause, urllib.error.HTTPError):
                return json.dumps(
                    {'error': f'Failed to resolve $ref {ref_uri}: HTTP {cause.code}'}
                )
            if isinstance(cause, urllib.error.URLError):
                return json.dumps({'error': f'Failed to resolve $ref {ref_uri}: {cause.reason}'})
            if isinstance(cause, TimeoutError):
                return json.dumps({'error': (f'Request timed out while resolving $ref {ref_uri}')})
            if isinstance(cause, json.JSONDecodeError):
                return json.dumps(
                    {'error': (f'Invalid JSON encountered while resolving $ref {ref_uri}')}
                )
            return json.dumps({'error': f'Failed to resolve $ref {ref_uri}: {exc}'})

        try:
            os.makedirs(absolute_path.parent, exist_ok=True)
            with open(absolute_path, 'w') as f:
                json.dump(resolved, f, indent=2)
        except OSError as exc:
            return json.dumps({'error': f'Failed to write schema to {absolute_path}: {exc}'})

        return json.dumps({'path': str(absolute_path)})

    except Exception as exc:
        return json.dumps({'error': str(exc)})


@mcp.tool()
async def list_asms() -> str:
    """List all available Allotrope Simple Models (ASMs).

    Retrieves ASM identifiers and descriptions from the local
    model_reference.json file bundled with the package.

    Returns:
        JSON string with ASM IDs mapped to descriptions, or an
        error key with a description on failure.
    """
    try:
        # Locate model_reference.json in package directory
        package_dir = Path(__file__).parent
        model_ref_path = package_dir / 'model_reference.json'

        # Read file
        try:
            with open(model_ref_path) as f:
                content = f.read()
        except FileNotFoundError:
            logger.error(f'Model reference file not found: {model_ref_path}')
            return json.dumps({'error': f'Model reference file not found: {model_ref_path}'})

        # Parse JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            logger.error(f'Model reference file contains malformed JSON: {model_ref_path}')
            return json.dumps(
                {'error': f'Model reference file contains malformed JSON: {model_ref_path}'}
            )

        # Extract ASM mappings
        asms = {}
        for asm_id, asm_data in data.items():
            if 'description' not in asm_data:
                logger.error(f"ASM '{asm_id}' missing description field")
                return json.dumps({'error': f"ASM '{asm_id}' missing description field"})
            asms[asm_id] = asm_data['description']

        return json.dumps(asms)

    except Exception as exc:
        logger.error(f'Unexpected error in list_asms: {exc}')
        return json.dumps({'error': f'Unexpected error: {exc}'})


def main():
    """Run the MCP server with CLI argument support."""
    logger.info('Starting allotrope MCP server')
    mcp.run()


if __name__ == '__main__':
    main()
