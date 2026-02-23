# AWS Labs Allotrope MCP Server

A Model Context Protocol (MCP) server that provides tools for working with Allotrope Simple Model (ASM) data formats. This server enables AI assistants to validate instrument data files against ASM schemas and discover available ASM techniques.

## What is Allotrope?

[Allotrope](https://www.allotrope.org/) is a data standards framework for laboratory and analytical instrument data. The Allotrope Simple Model (ASM) provides a standardized JSON format for representing instrument data, making it easier to integrate, analyze, and share scientific data across different systems and organizations.

## Features

This MCP server provides the following tools:

- **list_asm_techniques**: Discover all available ASM technique types from the official Allotrope GitLab repository
- **validate_asm**: Validate ASM JSON documents against their corresponding JSON schemas to ensure data compliance

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

- "List all available ASM techniques"
- "Validate this ASM document against the plate reader schema"
- "Check if my instrument data file is valid ASM format"

### Example: Validating an ASM Document

```bash
You: Validate tests/testdata/plate_reader_weyland_yutani_valid.json 
     against tests/testdata/plate_reader.embed.schema.json
```

Kiro will use the `validate_asm` tool to check the document and report any validation errors.

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
