# Custom Converter Requirements

## 1. Purpose

This document defines the requirements for building custom converters that integrate with the ASM Transformation Service. Any converter submitted for registration must comply with these requirements to ensure data integrity verification, regulatory traceability, and system compatibility.

## 2. Function Signature

### 2.1. Required

```python
def convert(file_content):
    """
    Convert instrument file content to Allotrope Simple Model (ASM) JSON.

    Args:
        file_content (str): Raw file content as a string.

    Returns:
        dict: {
            "success": True/False,
            "asm_output": { ... },          # ASM JSON (required on success)
            "field_mapping": [ ... ],        # Data integrity mappings (required)
            "error": "message"               # Error message (required on failure)
        }
    """
```

### 2.2. Rules

- Function name must be `convert`
- Must accept a single `file_content` string parameter (not a file path)
- Must return a dict with `success`, `asm_output`, and `field_mapping` keys
- Must not read from or write to the filesystem
- Must not make network calls
- Must not use `eval()`, `exec()`, `os.system()`, `subprocess`, or `__import__`

### 2.3. Do NOT use CLI-style signatures

```python
# ❌ WRONG — file path based
def convert(input_path, output_path):
    text = Path(input_path).read_text()
    Path(output_path).write_text(result)

# ✅ CORRECT — content based
def convert(file_content):
    return {"success": True, "asm_output": asm, "field_mapping": mappings}
```

## 3. Return Format

### 3.1. On Success

```python
{
    "success": True,
    "asm_output": { ... },       # Complete ASM JSON document
    "field_mapping": [ ... ]     # Array of source-to-ASM field mappings
}
```

### 3.2. On Failure

```python
{
    "success": False,
    "error": "Human-readable error message describing what went wrong"
}
```

## 4. Field Mapping (Required)

The `field_mapping` array is what powers the Data Integrity Verification report. It proves that every source value was preserved exactly in the ASM output. **Every value from the source file must have a corresponding entry.**

### 4.1. Entry Format

```python
{
    "source_field": "pH",              # Column name or field name in source file
    "source_value": 7.183,             # Exact value from source file
    "asm_field": "pH",                 # Field name in ASM output
    "asm_value": 7.183,                # Exact value written to ASM
    "unit": "pH"                       # Unit of measurement (empty string if unitless)
}
```

### 4.2. Rules

- `source_value` and `asm_value` must be identical — no rounding, no transformation
- Include entries for ALL values: measurements, metadata, calculated data, custom info
- String values are valid (e.g., lot numbers, operator names, sample IDs)
- Use empty string `""` for unit when not applicable
- Only omit fields that are used structurally (e.g., timestamp used as `measurement time`, sample ID used as `sample identifier`) — these are already visible in the ASM structure

### 4.3. Field Mapping Examples

#### 4.3.1. Numeric Example

```python
field_mapping.append({
    "source_field": "PO2",
    "source_value": 94.5,
    "asm_field": "pO2",
    "asm_value": 94.5,
    "unit": "mmHg"
})
```

#### 4.3.2. String Example

```python
field_mapping.append({
    "source_field": "Gas Cartridge Lot Number",
    "source_value": "25175029",
    "asm_field": "Gas Cartridge Lot Number (custom info)",
    "asm_value": "25175029",
    "unit": ""
})
```

#### 4.3.3. Calculated Value Example

```python
field_mapping.append({
    "source_field": "pH @ Temp",
    "source_value": 7.189,
    "asm_field": "temperature corrected pH (calculated)",
    "asm_value": 7.189,
    "unit": "pH"
})
```

## 5. ASM Output Structure

The `asm_output` must follow the Allotrope Simple Model schema for the relevant instrument type.

### 5.1. Handling Non-Tabular Data (Grids, Matrices, Unstructured Formats)

Not all instrument files are simple CSVs with column headers. Plate readers, for example, output grid/matrix layouts with metadata rows, empty rows, and checksums:

```csv
Weyland-Yutani 470 1384,,,,
Recorded,2023-10-26:11:15:40,,,
,,,,
,A,B,C,D
1,3.61,1.45,2.23,3.08
2,4.10,4.58,3.60,1.67
3,3.27,1.40,4.99,2.47
4,2.78,0.72,4.00,0.49
,,,,
Checksum,b855,,,
```

The `field_mapping` still works — use the well position or natural identifier as `source_field`:

```python
field_mapping = [
    # Metadata rows
    {"source_field": "Instrument", "source_value": "Weyland-Yutani 470 1384",
     "asm_field": "device identifier", "asm_value": "Weyland-Yutani 470 1384", "unit": ""},
    {"source_field": "Recorded", "source_value": "2023-10-26:11:15:40",
     "asm_field": "measurement time", "asm_value": "2023-10-26T11:15:40+00:00", "unit": ""},
    {"source_field": "Checksum", "source_value": "b855",
     "asm_field": "Checksum (custom info)", "asm_value": "b855", "unit": ""},

    # Grid values — well position as source_field
    {"source_field": "A1", "source_value": 3.61,
     "asm_field": "absorbance", "asm_value": 3.61, "unit": "mAU"},
    {"source_field": "B1", "source_value": 1.45,
     "asm_field": "absorbance", "asm_value": 1.45, "unit": "mAU"},
    {"source_field": "C1", "source_value": 2.23,
     "asm_field": "absorbance", "asm_value": 2.23, "unit": "mAU"},
    # ... all wells
]
```

### 5.2. Guidelines for non-tabular data:**

| Source Element | How to Handle |
|---------------|---------------|
| Grid/matrix values | Use well position (A1, B2) or row:col as `source_field` |
| Metadata rows (instrument name, date, operator) | Map like any other field |
| Checksums, hashes | Map to custom info — preserves verifiability |
| Empty rows, separators | Structural — no field_mapping entry needed |
| Row/column headers (A, B, C, 1, 2, 3) | Structural — no field_mapping entry needed |
| Timestamps in non-standard format | Normalize to ISO 8601 in `asm_value` — this is the one case where source and ASM values can differ |

### 5.3. Required Elements

| Element | Description |
|---------|-------------|
| `$asm.manifest` | Allotrope manifest URL for the instrument type |
| Aggregate document | Top-level document (e.g., `solution analyzer aggregate document`) |
| `data system document` | Converter name, version, timestamp, file identifier |
| `device system document` | Device identifier, manufacturer, device type |
| `measurement document` | Array of measurements with UUIDs and ISO 8601 timestamps |
| `sample document` | Sample identifier and description per measurement |

### 5.4. Measurement Identifiers

Use UUID v4 for all identifiers:

```python
import uuid
measurement_id = str(uuid.uuid4())
```

### 5.5. Timestamps

Use ISO 8601 with timezone:

```python
from datetime import datetime, timezone
iso_timestamp = dt.replace(tzinfo=timezone.utc).isoformat()
# Example: "2025-11-01T04:46:26+00:00"
```

### 5.6. Calculated Data Traceability

If the source file contains calculated values (e.g., temperature-corrected pH), include a `calculated data aggregate document` that links each calculated value back to its source measurement by `measurement identifier`.

### 5.7. Custom Information

Instrument metadata that doesn't fit standard ASM fields (lot numbers, flow times, dilution ratios, etc.) goes in `custom information aggregate document`.

## 6. Local testing

Include a `__main__` block in the converter file to support local testing. This should accept a single input argument (the raw instrument file path), parse it, call the `convert` function, and then write the `asm_output` and `field_mapping` dicts to json files. The json files should have the same basename as the raw data file, plus a `_asm` suffix for the asm output or a `_map` suffix for the field mapping data.

```python
import csv
import io
import uuid
from datetime import datetime, timezone

def convert(file_content):
    # ... your converter logic ...
    return {"success": True, "asm_output": asm, "field_mapping": mappings}

# This block runs ONLY when you execute the file locally for testing.
# The service ignores it completely.
if __name__ == '__main__':
    import json
    with open('sample_data.csv', 'r') as f:
        result = convert(f.read())
    with open('sample_data_asm.json', 'w') as f:
        json.dump(result.get('asm_output'), f, indent=2)
    with open('sample_data_map.json', 'w') as f:
        json.dump(result.get('field_mapping'), f, indent=2)        
```

The `__main__` block lets you test locally with file I/O, but the service never executes it. The security checks (no `open()`, no `Path()`) apply to the `convert` function and top-level code — not to the `__main__` block.

## 7. How the Service Executes Your Converter

Understanding how the service runs your code helps you write converters correctly.

### 7.1. Execution Model

Your converter file is **not imported as a Python module** and **not run as a standalone script**. Instead, the Custom Converter Service Lambda:

1. Downloads your `.py` file from S3
2. Executes the entire file using `exec()` into an isolated namespace
3. Looks for a function named `convert` in that namespace
4. Calls `convert(file_content)` with the raw instrument file content
5. Returns whatever your function returns

This means:

- **Your `convert` function is the only entry point** — the service calls it directly
- **Top-level code runs during `exec()`** — imports, constants, helper functions are all fine
- **`if __name__ == '__main__'` blocks do NOT run** — `exec()` does not set `__name__` to `'__main__'`, so these blocks are safely skipped

### 7.2. What Runs vs What Doesn't

| Code | Runs in Service? | Runs Locally? |
|------|-----------------|---------------|
| `import csv, uuid, ...` | Yes (during exec) | Yes |
| Helper functions | Yes (during exec) | Yes |
| Top-level constants | Yes (during exec) | Yes |
| `def convert(file_content)` | Yes (called by service) | Yes (called by main) |
| `if __name__ == '__main__'` | **No** (skipped) | Yes |

## 8. Complete Example

```python
import csv
import io
import uuid
from datetime import datetime, timezone


def convert(file_content):
    try:
        reader = csv.DictReader(io.StringIO(file_content))
        rows = list(reader)

        if not rows:
            return {"success": False, "error": "No data rows found"}

        row = rows[0]
        field_mapping = []
        measurements = []

        # Parse a measurement value
        absorbance = float(row.get("Absorbance", "0"))
        well = row.get("Well", "A1")

        m_id = str(uuid.uuid4())
        measurements.append({
            "measurement identifier": m_id,
            "measurement time": datetime.now(timezone.utc).isoformat(),
            "absorbance": {"value": absorbance, "unit": "mAU"},
            "sample document": {
                "sample identifier": well,
                "location identifier": well
            }
        })

        field_mapping.append({
            "source_field": "Absorbance",
            "source_value": absorbance,
            "asm_field": "absorbance",
            "asm_value": absorbance,
            "unit": "mAU"
        })

        # Parse a metadata value
        lot = row.get("Cartridge Lot", "").strip()
        custom_info = []
        if lot:
            custom_info.append({"datum label": "Cartridge Lot", "scalar string datum": lot})
            field_mapping.append({
                "source_field": "Cartridge Lot",
                "source_value": lot,
                "asm_field": "Cartridge Lot (custom info)",
                "asm_value": lot,
                "unit": ""
            })

        asm = {
            "$asm.manifest": "http://purl.allotrope.org/manifests/plate-reader/REC/2025/12/plate-reader.manifest",
            "plate reader aggregate document": {
                "plate reader document": [{
                    "device system document": {
                        "device identifier": "READER-001",
                        "product manufacturer": "Agilent",
                        "device document": [{"device type": "plate reader"}]
                    },
                    "measurement aggregate document": {
                        "measurement document": measurements
                    }
                }]
            }
        }

        if custom_info:
            asm["plate reader aggregate document"]["plate reader document"][0][
                "measurement aggregate document"
            ]["custom information aggregate document"] = {
                "custom information document": custom_info
            }

        return {"success": True, "asm_output": asm, "field_mapping": field_mapping}

    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == '__main__':
    import json
    with open('plate_reader_data.csv', 'r') as f:
        result = convert(f.read())
    with open('plate_reader_data_asm.json', 'w') as f:
        json.dump(result.get('asm_output'), f, indent=2)
    with open('plate_reader_data_map.json', 'w') as f:
        json.dump(result.get('field_mapping'), f, indent=2)        
```
