---
name: instrument-data-to-allotrope
description: Creates Python converter code to transform laboratory instrument data into Allotrope Simple Model (ASM) JSON format. Use when a user asks to convert instrument data to ASM, generate an ASM data instance, write a plate reader converter, map instrument CSV to Allotrope, or validate ASM output. Requires the awslabs.allotrope-mcp-server MCP server to be connected.
license: Apache-2.0
metadata:
  author: AWS Labs
  version: 1.0.0
  mcp-server: awslabs.allotrope-mcp-server
---

# Instrument Data to Allotrope

Converts raw laboratory instrument data into a valid Allotrope Simple Model (ASM) JSON data
instance that conforms to the target ASM schema. Covers schema discovery, data parsing, JSON
generation, schema validation, and field mapping documentation.

## ASM Document Structure

ASM organises experimental data as a hierarchy of modular documents. The generated JSON must
mirror this structure exactly.

```bash
Technique Aggregate Document          ← top-level container (e.g. "plate reader aggregate document")
├── Device System Document            ← instrument hardware metadata (model, manufacturer, serial)
├── Data System Document              ← software / data-processing metadata (version, file paths)
└── Technique Document[]              ← one entry per execution of the technique (e.g. one plate run)
    ├── Measurement Aggregate Document
    │   └── Measurement Document[]    ← one entry per individual measurement (e.g. one well)
    ├── Processed Data Document       ← derived results (peak lists, spectra, …)
    ├── Sample Document               ← sample identity and provenance
    ├── Device Control Document       ← acquisition settings and parameters
    └── Calculated Data Document      ← values computed across measurements or samples
```

Key points:

- The root JSON key matches the technique aggregate document name from the schema (e.g. `plate reader aggregate document`)
- `$asm.manifest` at the root declares the schema — copy this value verbatim from a valid example instance; the URI must end in `.manifest`
- Technique Document is an array — even a single run must be wrapped in a list
- Measurement Aggregate Document is a container; individual readings live inside its `measurement document` array

## Parameters

- **input_path** (required): Path to the instrument data file to convert
- **asm_model** (required): Name of the ASM model to target (e.g. `plate-reader`)
- **output_path** (optional, default: `<input_path>.asm.json`): Destination for the generated ASM JSON
- **schema_output_dir** (optional, default: current working directory): Directory to save the downloaded schema

## Workflow

### Step 1: Discover the Target ASM Model

Call the `describe_asm` MCP tool with the **asm_model** parameter.

Constraints:

- MUST call `describe_asm` before fetching any schema
- MUST record the `asm_json_schema` URI for subsequent steps
- SHOULD review `asm_data_instance_examples` URIs to understand expected document shape
- If the model name is unclear or `describe_asm` errors, call `list_asms` first to find the correct name

### Step 2: Download the ASM Schema

Call `fetch_asm_document` with the `asm_json_schema` URI from Step 1.

Constraints:

- MUST pass the `asm_json_schema` URI as `asm_document_uri`
- MUST record the local path returned by the tool for use in Step 7
- SHOULD set `output_dir` to a `testdata/json-schemas` directory to keep schemas organised

### Step 3: Inspect a Valid Data Instance

Call `fetch_asm_document` with one of the `asm_data_instance_examples` URIs, then read the file.

Constraints:

- MUST download an example before writing any converter code
- MUST identify the `$asm.manifest` value, top-level aggregate document key, and `measurement document` structure
- SHOULD cross-reference the example with the schema to confirm required vs optional fields

### Step 4: Parse the Source Data

Read the instrument data file and extract all metadata and measurement values.

Constraints:

- MUST extract: instrument brand, model number, device identifier, and recording timestamp
- MUST parse all well readings into `(row_label, column_label, value)` tuples
- MUST normalise the timestamp to ISO 8601 format with UTC timezone offset (`+00:00`)
- MUST NOT silently drop records — skip only blank lines and known footer entries (e.g. `Checksum`)

### Step 5: Standardize the Source Data

Convert the parsed source data into a generic intermediate JSON representation and save it to
`<input_path>.intermediate.json`. This file provides a format-agnostic snapshot of the raw data
that can be used for auditing, debugging, and downstream validation independent of any ASM schema.

The intermediate JSON must be as generic as possible so it can represent data from any instrument
type or file format (CSV, TSV, XML, proprietary binary exports, etc.).

Use the following top-level structure:

```json
{
  "source_file": "<original input file path>",
  "format": "<detected format, e.g. csv, tsv, xml>",
  "metadata": {
    "<key>": "<value>"
  },
  "data": [
    {
      "<field_name>": "<value>"
    }
  ]
}
```

Field definitions:

- `source_file`: The absolute or relative path to the original instrument data file.
- `format`: A short lowercase string identifying the detected file format (e.g. `csv`, `tsv`, `xml`, `txt`).
- `metadata`: A flat key/value object containing all header-level or file-level fields extracted in Step 4
  (e.g. instrument brand, model, serial number, timestamp). Values MUST be strings.
- `data`: An array of objects, one per discrete measurement or data record. Each object uses flat
  key/value pairs with string keys and scalar values (string, number, or null). Do not nest objects
  inside `data` entries — flatten any hierarchical source structure.

Constraints:

- MAY skip this step if the source file is already in JSON format (i.e. `input_path` ends in `.json` or file content parses as valid JSON) — proceed directly to Step 6
- MUST write the intermediate JSON to `<input_path>.intermediate.json` unless an explicit path is provided
- MUST include every field extracted in Step 4 — do not omit or summarise records
- MUST ensure no data from the raw source file is lost — every value, including headers, metadata, and all measurement records, MUST appear in the intermediate JSON
- MUST use only generic field names derived from the source data (e.g. `row`, `column`, `value`);
  do NOT use ASM-specific terminology in this file
- MUST ensure all values in `metadata` are strings; cast numbers and dates as needed
- MUST ensure the file is valid, pretty-printed JSON (indent = 2)
- SHOULD preserve the original field names from the source data where they are meaningful
- MUST NOT include any ASM-specific keys or structure in this file

### Step 6: Write the Converter Script

Implement a Python script that reads the source data and writes a conformant ASM JSON file.

Constraints:

- MUST include the Apache-2.0 license header at the top of the file
- MUST generate a fresh UUID for `ASM file identifier` on each run
- MUST map well positions to `<column><row>` identifiers (e.g. column `A`, row `1` → `A1`)
- SHOULD accept `input_path` and `output_path` as optional CLI arguments with sensible defaults
- SHOULD include Google-style docstrings on all public functions
- MUST NOT hard-code instrument metadata — derive it from the source data header

### Step 7: Run the Converter

Execute the script against the source data to produce the ASM JSON output file.

Constraints:

- MUST verify the script exits with code 0
- MUST confirm the output file exists and contains well-formed JSON before proceeding

### Step 8: Validate Against the Schema

Call `validate_asm` with the generated JSON and the schema path from Step 2.

Constraints:

- MUST pass the output file path as `asm_document_path`
- MUST pass the schema path from Step 2 as `asm_schema_path`
- MUST confirm `is_valid` is `true` and `errors` is empty before considering the task complete
- If validation fails, MUST inspect each error, correct the converter, re-run, and re-validate until valid

### Step 9: Generate Field Mapping Document

Produce a markdown document mapping every source field to its ASM destination.

Constraints:

- MUST create the mapping at `<output_path>.field-map.md` unless an explicit path is provided
- MUST include a table with columns: `Source Field`, `Source Location`, `ASM Destination Path`, `Transformation`, `Required`
- MUST cover all fields extracted in Step 4 and standardized in Step 5 (metadata and per-measurement)
- MUST describe any transformation applied (timestamp normalisation, unit conversion, UUID generation, well ID assembly)
- MUST NOT omit discarded fields without explaining why they were excluded
- SHOULD add a brief prose introduction naming the source format, target ASM model, and schema URI

Table format:

```markdown
| Source Field | Source Location | ASM Destination Path | Transformation | Required |
|---|---|---|---|---|
| Instrument Brand | Header row, column 1 | `device system document > brand name` | None | Yes |
| Timestamp | Header row, `Date` key | `measurement document > measurement time` | Normalise to ISO 8601 UTC | Yes |
| Well Absorbance | Data grid cell | `measurement document > absorbance > value` | Cast to float | Yes |
```

## Examples

### Plate Reader CSV → ASM JSON

```bash
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
Some instruments write timestamps as `YYYY-MM-DD:HH:MM:SS` (colon between date and time).
Normalise with a regex substitution before calling `datetime.fromisoformat`.

**Well identifier ordering**
Source data may lay out columns as headers and rows as the first cell of each data row.
Assemble the well ID as `<column_letter><row_number>` (e.g. `A1`), not the reverse.

**Schema validation errors on `unit`**
The plate-reader schema requires absorbance values to use unit `mAU`. Using `AU` or omitting
the unit field will cause a validation failure.

**`fetch_asm_document` saves to a nested path**
The tool mirrors the URI path under `output_dir`, which can produce a double-nested directory
(e.g. `json-schemas/json-schemas/...`). Record the exact path returned by the tool and use
that path verbatim in the `validate_asm` call.
