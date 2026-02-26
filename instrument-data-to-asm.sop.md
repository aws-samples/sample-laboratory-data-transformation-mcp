# Convert Instrument Data to ASM Data Instance

## Overview

Converts raw instrument data into a valid Allotrope Simple Model (ASM) JSON data instance
that conforms to the target ASM schema. Covers schema discovery, data parsing, JSON generation,
and schema validation using the Allotrope MCP server tools.

## Parameters

- **input_path** (required): Path to the instrument data file to convert
- **asm_model** (required): Name of the ASM model to target (e.g. `plate-reader`)
- **output_path** (optional, default: `<input_path>.asm.json`): Destination path for the generated ASM JSON file
- **schema_output_dir** (optional, default: current working directory): Directory to save the downloaded schema

## Steps

### 1. Discover the Target ASM Model

Use the `describe_asm` MCP tool to retrieve the model's schema URI, manifest URI, and example
data instance URIs.

**Constraints:**

- You MUST call `describe_asm` with the **asm_model** parameter before fetching any schema
- You MUST record the `asm_json_schema` URI for use in subsequent steps
- You SHOULD review the `asm_data_instance_examples` URIs to understand expected document shape
- If the model name is unclear or `describe_asm` returns an error, you SHOULD call `list_asms` first to identify the correct model name

### 2. Download the ASM Schema

Use the `fetch_asm_document` MCP tool to download the JSON schema identified in Step 1.

**Constraints:**

- You MUST pass the `asm_json_schema` URI from Step 1 as `asm_document_uri`
- You MUST record the local path returned by the tool for use in Step 5
- You SHOULD set `output_dir` to keep schemas organised under a `testdata/json-schemas` directory

### 3. Inspect an Existing Valid Data Instance

Use `fetch_asm_document` to download one of the `asm_data_instance_examples` URIs recorded in
Step 1, then read the file to understand the required top-level structure, field names, and nesting.

**Constraints:**

- You MUST call `fetch_asm_document` with one of the `asm_data_instance_examples` URIs before writing any converter code
- You MUST identify the `$asm.manifest` value, top-level aggregate document key, and the
  structure of `measurement document` items from the downloaded example
- You SHOULD cross-reference the example with the schema to confirm required vs optional fields

### 4. Parse the Source Data

Read the instrument data file and extract all metadata and measurement values needed to populate
the ASM document.

**Constraints:**

- You MUST extract: instrument brand, model number, device identifier, and recording timestamp
- You MUST parse all well readings into `(row_label, column_label, absorbance_value)` tuples
- You MUST normalise the timestamp to ISO 8601 format with UTC timezone offset (`+00:00`)
- You MUST NOT silently drop records — skip only blank lines and known footer entries (e.g. `Checksum`)

### 5. Write the Converter Script

Implement a Python script that reads the source data (Step 4) and writes a conformant ASM JSON file.

**Constraints:**

- You MUST include the Apache-2.0 license header at the top of the file
- You MUST generate a fresh UUID for `ASM file identifier` on each run
- You MUST map well positions to `<column><row>` identifiers (e.g. column `A`, row `1` → `A1`)
- You SHOULD accept `input_path` and `output_path` as optional CLI arguments with sensible defaults
- You SHOULD include Google-style docstrings on all public functions
- You MUST NOT hard-code instrument metadata — derive it from the source data header

### 6. Run the Converter

Execute the script against the source data to produce the ASM JSON output file.

**Constraints:**

- You MUST verify the script exits with code 0
- You MUST confirm the output file exists and contains well-formed JSON before proceeding

### 7. Validate Against the Schema

Use the `validate_asm` MCP tool to validate the generated JSON against the downloaded schema.

**Constraints:**

- You MUST pass the output file path as `asm_document_path`
- You MUST pass the schema path from Step 2 as `asm_schema_path`
- You MUST confirm `is_valid` is `true` and `errors` is empty before considering the task complete
- If validation fails, you MUST inspect each error, correct the converter script, re-run it,
  and re-validate until the document is valid

## Examples

### Plate Reader → ASM JSON

```text
input_path:  tests/testdata/plate_reader_weyland_yutani_instrument_data.csv
asm_model:   plate-reader
output_path: tests/testdata/plate_reader_weyland_yutani_instrument_data.asm.json
```

Expected outcome:

- Schema downloaded to `tests/testdata/json-schemas/...plate-reader.embed.schema`
- Converter script written to `convert_plate_reader_csv.py`
- Output JSON contains 16 measurement documents (4 columns × 4 rows)
- `validate_asm` returns `{"is_valid": true, "errors": []}`

## Troubleshooting

**Timestamp parse error**
Some instruments write timestamps as `YYYY-MM-DD:HH:MM:SS` (colon separator between date and
time). Normalise with a regex substitution before calling `datetime.fromisoformat`.

**Well identifier ordering**
Source data may be laid out with columns as headers and rows as the first cell of each data row.
Ensure the well ID is assembled as `<column_letter><row_number>` (e.g. `A1`), not the reverse.

**Schema validation errors on `unit`**
The plate-reader schema requires absorbance values to use unit `mAU`. Using `AU` or omitting
the unit field will cause a validation failure.

**`fetch_asm_document` saves to a nested path**
The tool mirrors the URI path under `output_dir`, which can produce a double-nested directory
(e.g. `json-schemas/json-schemas/...`). Record the exact path returned by the tool and use
that path verbatim in the `validate_asm` call.
