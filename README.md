# AWS Labs Allotrope MCP Server

A Model Context Protocol (MCP) server that provides tools for working with Allotrope Simple Model (ASM) data formats. This server enables AI assistants to validate instrument data files against ASM schemas and discover available ASMs.

## What is Allotrope?

[Allotrope](https://www.allotrope.org/) is a data standards framework for laboratory and analytical instrument data. The Allotrope Simple Model (ASM) provides a standardized JSON format for representing instrument data, making it easier to integrate, analyze, and share scientific data across different systems and organizations.

## Features

This MCP server provides the following tools:

- **list_asms**: List all available Allotrope Simple Models (ASMs) with their descriptions from the bundled reference file
- **describe_asm**: Retrieve full metadata for a specific ASM model by name, including its description, manifest URL, JSON schema URL, and data instance example URLs
- **validate_asm**: Validate ASM JSON documents against their corresponding JSON schemas to ensure data compliance
- **fetch_asm_document**: Download a raw ASM JSON document from `purl.allotrope.org` to the local filesystem at a path mirroring the URI structure, without resolving `$ref` references

## Installation

### Prerequisites

- Python 3.10 or higher
- [uv](https://docs.astral.sh/uv/) package manager

### Setup

```bash
# Clone the repository
git clone https://github.com/awslabs/mcp.git
cd mcp/src/allotrope-mcp-server

# Install dependencies
uv sync

# Run the server
uv run awslabs.allotrope-mcp-server
```

## Integration with Kiro

To use this MCP server with Kiro, you need to add it to your MCP configuration file.

### Step 1: Locate Your MCP Configuration

Kiro uses MCP configuration files at different levels:

- **User-level** (global): `~/.kiro/settings/mcp.json`
- **Workspace-level**: `.kiro/settings/mcp.json` (in your project root)

Create the file if it doesn't exist.

### Step 2: Add Server Configuration

Add the following configuration to your `mcp.json` file, replacing `/path/to/allotrope-mcp-server` with the actual path to your local installation:

```json
{
  "mcpServers": {
    "allotrope": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/allotrope-mcp-server",
        "run",
        "awslabs.allotrope-mcp-server"
      ],
      "env": {
        "FASTMCP_LOG_LEVEL": "ERROR"
      },
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

### Step 3: Restart or Reconnect

The server will automatically connect when you restart Kiro, or you can manually reconnect it from the MCP Server view in the Kiro feature panel.

### Configuration Options

- **command**: Use `uv` to run the server from your local installation
- **args**: Specify the directory path and run command
- **env.FASTMCP_LOG_LEVEL**: Control logging verbosity (ERROR, WARNING, INFO, DEBUG)
- **disabled**: Set to `true` to temporarily disable the server
- **autoApprove**: List tool names that don't require approval (e.g., `["list_asms"]`)

## Usage Examples

Once configured in Kiro, you can use natural language to interact with the tools:

- "List all available ASMs"
- "Describe the absorbance ASM model"
- "Validate this ASM document against the plate reader schema"
- "Check if my instrument data file is valid ASM format"
- "Fetch the plate reader embed schema document to my project"

### Example: Validating an ASM Document

```bash
You: Validate tests/testdata/plate_reader_weyland_yutani_valid.json 
     against tests/testdata/plate_reader.embed.schema.json
```

Kiro will use the `validate_asm` tool to check the document and report any validation errors.

### Example: Fetching a Raw ASM Document

```bash
You: Fetch the plate reader embed schema document to my project
```

Kiro will use the `fetch_asm_document` tool to download the raw JSON document from `purl.allotrope.org` and save it locally at a path that mirrors the URI structure.

## Tool Reference

### list_asms

Lists all available Allotrope Simple Models (ASMs) with their descriptions. Reads from the bundled `model_reference.json` file and returns a mapping of ASM IDs to descriptions.

**Parameters:** None

**Returns:** A JSON object mapping ASM identifiers to their descriptions, or an `error` key on failure.

### describe_asm

Returns the full metadata for a specific ASM model by name. Looks up the model in the bundled `model_reference.json` and returns its description, manifest URL, JSON schema URL, and data instance example URLs as a JSON string.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `model_name` | string | Yes | The ASM model identifier to look up (e.g., `"absorbance"`, `"balance"`). Use `list_asms` to discover valid names. |

**Returns:** A JSON object with the model metadata on success, or an object with an `error` key and a `valid_model_names` list if the model name is not recognised.

**Example response (success):**

```json
{
  "description": "...",
  "asm_manifest": "http://purl.allotrope.org/manifests/...",
  "asm_json_schema": "http://purl.allotrope.org/json-schemas/...",
  "asm_data_instance_examples": ["http://purl.allotrope.org/test/..."]
}
```

### fetch_asm_document

Downloads a raw ASM JSON document from the Allotrope PURL repository (`purl.allotrope.org`) and saves it to the local filesystem at a path that mirrors the URI structure. `$ref` references are **not** resolved — the document is saved exactly as received.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `asm_document_uri` | string | Yes | Fully-qualified URI starting with `http://purl.allotrope.org` (case-sensitive). |
| `output_dir` | string | No | Base directory for saving the document. Defaults to the current working directory. |

**Behavior:**

- Rejects URIs that do not start with `http://purl.allotrope.org` (case-sensitive) — no network call is made on rejection
- If the file already exists at the derived local path, returns the path immediately without re-downloading
- Downloads the document and validates it is well-formed JSON before writing
- Creates parent directories as needed and saves the document as UTF-8 JSON with 2-space indentation
- Returns a JSON object with a `path` key on success, or an `error` key on failure

**Example response (success):**

```json
{"path": "/absolute/path/to/json-schemas/adm/plate-reader/REC/2025/12/plate-reader.embed.schema"}
```

### validate_asm

Validates an ASM JSON document against its corresponding JSON schema.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `asm_document_path` | string | Yes | Path to the ASM JSON document to validate |
| `asm_schema_path` | string | Yes | Path to the ASM JSON schema to validate against |

## Development

### Running Tests

```bash
uv run pytest --cov --cov-branch --cov-report=term-missing
```

### Linting and Formatting

```bash
uv run ruff check .
uv run ruff format .
```

### Type Checking

```bash
uv run pyright
```

## Resources

- [Allotrope Foundation](https://www.allotrope.org/)
- [Model Context Protocol Documentation](https://modelcontextprotocol.io/)
- [AWS Labs MCP Servers](https://awslabs.github.io/mcp/)
- [Project Repository](https://github.com/awslabs/mcp)

## License

This project is licensed under the Apache License 2.0. See the [LICENSE](LICENSE) file for details.
