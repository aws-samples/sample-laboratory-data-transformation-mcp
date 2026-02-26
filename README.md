# AWS Labs Allotrope MCP Server

A Model Context Protocol (MCP) server that provides tools for working with Allotrope Simple Model (ASM) data formats. This server enables AI assistants to validate instrument data files against ASM schemas and discover available ASM techniques.

## What is Allotrope?

[Allotrope](https://www.allotrope.org/) is a data standards framework for laboratory and analytical instrument data. The Allotrope Simple Model (ASM) provides a standardized JSON format for representing instrument data, making it easier to integrate, analyze, and share scientific data across different systems and organizations.

## Features

This MCP server provides the following tools:

- **list_asms**: List all available Allotrope Simple Models (ASMs) with their descriptions from the bundled reference file
- **list_asm_techniques**: Discover all available ASM technique types from the official Allotrope GitLab repository
- **validate_asm**: Validate ASM JSON documents against their corresponding JSON schemas to ensure data compliance
- **get_asm_schema**: Download and resolve Allotrope ASM JSON schemas with all `$ref` references embedded inline for offline use

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
- **autoApprove**: List tool names that don't require approval (e.g., `["list_asm_techniques"]`)

## Usage Examples

Once configured in Kiro, you can use natural language to interact with the tools:

- "List all available ASMs"
- "List all available ASM techniques"
- "Validate this ASM document against the plate reader schema"
- "Check if my instrument data file is valid ASM format"
- "Download the plate reader ASM schema and resolve all references"

### Example: Validating an ASM Document

```bash
You: Validate tests/testdata/plate_reader_weyland_yutani_valid.json 
     against tests/testdata/plate_reader.embed.schema.json
```

Kiro will use the `validate_asm` tool to check the document and report any validation errors.

### Example: Downloading an ASM Schema

```bash
You: Download the conductivity ASM schema to my project
```

Kiro will use the `get_asm_schema` tool to download the schema, resolve all `$ref` references inline, and save the self-contained schema locally.

## Tool Reference

### list_asms

Lists all available Allotrope Simple Models (ASMs) with their descriptions. Reads from the bundled `model_reference.json` file and returns a mapping of ASM IDs to descriptions.

**Parameters:** None

**Returns:** A JSON object mapping ASM identifiers to their descriptions, or an `error` key on failure.

### get_asm_schema

Downloads an Allotrope ASM JSON schema from the official PURL repository, resolves all `$ref` references by embedding them inline, and saves the fully resolved schema to the local filesystem.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | string | Yes | Schema identifier. Accepts a full URI (`http://purl.allotrope.org/json-schemas/...`), a `json-schemas/`-prefixed path, or a bare suffix path. |
| `output_dir` | string | No | Base directory for saving the schema. Defaults to the current working directory. |

**Schema ID formats:**

All of the following are equivalent:
- Full URI: `http://purl.allotrope.org/json-schemas/adm/conductivity/REC/2021/12/conductivity.schema`
- Path with prefix: `json-schemas/adm/conductivity/REC/2021/12/conductivity.schema`
- Bare path: `adm/conductivity/REC/2021/12/conductivity.schema`

**Behavior:**

- If the resolved schema file already exists locally, returns the path without re-downloading
- Downloads the schema from `http://purl.allotrope.org/` and resolves all external `$ref` references inline
- Generates an embed filename (e.g., `conductivity.schema` → `conductivity.embed.schema.json`)
- Creates parent directories as needed and saves the formatted JSON
- Returns a JSON object with a `path` key on success, or an `error` key on failure
- Uses the `jsonref` library for `$ref` resolution; circular `$ref` chains are handled safely without hanging

### list_asm_techniques

Discovers all available ASM technique types from the official Allotrope GitLab repository.

**Parameters:** None

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
