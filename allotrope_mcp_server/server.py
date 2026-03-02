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

"""allotrope MCP Server implementation."""

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from jsonschema import Draft202012Validator
from mcp.server.fastmcp import FastMCP
from pathlib import Path


logger = logging.getLogger(__name__)


HTTP_TIMEOUT_SECONDS = 30

PURL_ORIGIN = "https://purl.allotrope.org"

mcp = FastMCP(
    "allotrope-mcp-server",
    instructions=(
        "This MCP server provides tools to convert instrument data files into"
        " standardized Allotrope Simple Model (ASM) format."
    ),
    dependencies=[
        "jsonschema",
        "pydantic",
    ],
)


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
        with open(document_path, encoding='utf-8') as f:
            document_text = f.read()
    except FileNotFoundError:
        return ValidationResult(
            is_valid=False,
            error_message=f"Document file not found: {document_path}",
        )

    try:
        document = json.loads(document_text)
    except json.JSONDecodeError:
        return ValidationResult(
            is_valid=False,
            error_message=f"Document file contains malformed JSON: {document_path}",
        )

    # Read schema
    try:
        with open(schema_path, encoding='utf-8') as f:
            schema_text = f.read()
    except FileNotFoundError:
        return ValidationResult(
            is_valid=False,
            error_message=f"Schema file not found: {schema_path}",
        )

    try:
        schema = json.loads(schema_text)
    except json.JSONDecodeError:
        return ValidationResult(
            is_valid=False,
            error_message=f"Schema file contains malformed JSON: {schema_path}",
        )

    # Validate
    validator = Draft202012Validator(schema)
    errors = [
        ValidationError(
            path=".".join(str(p) for p in err.absolute_path) or "(root)",
            message=err.message,
            validator=err.validator,
        )
        for err in sorted(
            validator.iter_errors(document), key=lambda e: list(e.absolute_path)
        )
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
    if d["error_message"] is None:
        del d["error_message"]
    return json.dumps(d)


@mcp.tool()
async def fetch_asm_document(asm_document_uri: str, output_dir: str = "") -> str:
    """Fetch a raw ASM JSON document from purl.allotrope.org.

    Downloads the document identified by ``asm_document_uri`` from the Allotrope
    PURL repository and saves it to the local filesystem at a path that mirrors
    the URI structure.  If the file already exists it is returned immediately
    without re-downloading.  Unlike ``get_asm_schema``, ``$ref`` references are
    NOT resolved — the document is saved exactly as received.

    Args:
        asm_document_uri: Fully-qualified URI starting with
            ``http://purl.allotrope.org``.
        output_dir: Base directory for saving the document.  Defaults to the
            current working directory when empty.

    Returns:
        JSON string with a ``path`` key containing the absolute path to the
        saved file, or an ``error`` key with a description on failure.
    """
    try:
        if not asm_document_uri.startswith(PURL_ORIGIN):
            return json.dumps(
                {
                    "error": f"Invalid URI: {asm_document_uri!r} must start with {PURL_ORIGIN!r}"
                }
            )

        base_dir = output_dir if output_dir else os.getcwd()
        mirror_path = asm_document_uri[len(PURL_ORIGIN) :].lstrip("/")
        dest = Path(base_dir) / mirror_path

        if dest.exists():
            return json.dumps({"path": str(dest.resolve())})

        # Downloader
        loop = asyncio.get_event_loop()
        try:

            def _fetch() -> bytes:
                with urllib.request.urlopen(
                    asm_document_uri, timeout=HTTP_TIMEOUT_SECONDS
                ) as resp:
                    return resp.read()

            body = await loop.run_in_executor(None, _fetch)
        except urllib.error.HTTPError as exc:
            return json.dumps(
                {"error": f"Failed to download {asm_document_uri}: HTTP {exc.code}"}
            )
        except urllib.error.URLError as exc:
            return json.dumps(
                {"error": f"Failed to connect to {asm_document_uri}: {exc.reason}"}
            )
        except TimeoutError:
            return json.dumps({"error": f"Request timed out for {asm_document_uri}"})

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return json.dumps(
                {"error": f"Invalid JSON received from {asm_document_uri}"}
            )

        # Writer
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            return json.dumps({"error": f"Failed to write document to {dest}: {exc}"})

        return json.dumps({"path": str(dest.resolve())})

    except Exception as exc:
        return json.dumps({"error": str(exc)})


def _load_model_reference() -> dict | None:
    """Load and parse model_reference.json bundled with the package.

    Returns:
        Parsed dict on success, or None if the file is missing or malformed.
    """
    model_ref_path = Path(__file__).parent / "model_reference.json"

    try:
        with open(model_ref_path, encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        logger.error(f"Model reference file not found: {model_ref_path}")
        return None

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.error(f"Model reference file contains malformed JSON: {model_ref_path}")
        return None


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
        model_ref_path = Path(__file__).parent / "model_reference.json"

        data = _load_model_reference()
        if data is None:
            try:
                with open(model_ref_path, encoding='utf-8') as f:
                    f.read()
                # File opened fine — must be malformed JSON
                return json.dumps(
                    {
                        "error": f"Model reference file contains malformed JSON: {model_ref_path}"
                    }
                )
            except FileNotFoundError:
                return json.dumps(
                    {"error": f"Model reference file not found: {model_ref_path}"}
                )

        # Extract ASM mappings
        asms = {}
        for asm_id, asm_data in data.items():
            if "description" not in asm_data:
                logger.error(f"ASM '{asm_id}' missing description field")
                return json.dumps(
                    {"error": f"ASM '{asm_id}' missing description field"}
                )
            asms[asm_id] = asm_data["description"]

        return json.dumps(asms)

    except Exception as exc:
        logger.error(f"Unexpected error in list_asms: {exc}")
        return json.dumps({"error": f"Unexpected error: {exc}"})


@mcp.tool()
async def describe_asm(model_name: str) -> str:
    """Return the metadata for a specific ASM model by name.

    Args:
        model_name: The key identifying the ASM model (e.g. 'automated-reactors').

    Returns:
        JSON string containing the model metadata on success, or an error object
        with the unrecognized name and a list of valid model names on failure.
    """
    try:
        reference = _load_model_reference()
        if reference is None:
            model_ref_path = Path(__file__).parent / "model_reference.json"
            try:
                with open(model_ref_path, encoding='utf-8') as f:
                    f.read()
                return json.dumps(
                    {
                        "error": f"Model reference file contains malformed JSON: {model_ref_path}"
                    }
                )
            except FileNotFoundError:
                return json.dumps(
                    {"error": f"Model reference file not found: {model_ref_path}"}
                )

        if model_name in reference:
            return json.dumps(reference[model_name])

        return json.dumps(
            {
                "error": (
                    f"Unknown model name: '{model_name}'."
                    " See valid_model_names for available options."
                ),
                "valid_model_names": sorted(reference.keys()),
            }
        )

    except Exception as exc:
        logger.error(f"Unexpected error in describe_asm: {exc}")
        return json.dumps({"error": f"Unexpected error: {exc}"})


def main():
    """Run the MCP server with CLI argument support."""
    logger.info("Starting allotrope MCP server")
    mcp.run()


if __name__ == "__main__":
    main()
