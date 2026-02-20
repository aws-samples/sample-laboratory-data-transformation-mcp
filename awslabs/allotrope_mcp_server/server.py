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
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from jsonschema import Draft202012Validator
from loguru import logger
from mcp.server.fastmcp import FastMCP


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
            params = urllib.parse.urlencode({
                'ref': _GITLAB_REF,
                'path': _GITLAB_PATH,
                'page': page,
            })
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


def main():
    """Run the MCP server with CLI argument support."""
    logger.info('Starting allotrope MCP server')
    mcp.run()


if __name__ == '__main__':
    main()
