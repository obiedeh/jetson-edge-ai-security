# Public Datasets

The runtime supports two dataset modes:

```text
local CSV path -> replay-csv
known dataset key -> fetch-dataset/replay-dataset
```

`fetch-dataset` only downloads from allowlisted direct URLs. This keeps the runtime predictable and avoids scraping forms, executing downloaded code, or guessing which file to use from opaque portals.

## Supported Auto-Download

| Key | Dataset | Source | Notes |
|---|---|---|---|
| `wustl-iiot-2021` | WUSTL-IIoT-2021 | `https://research.engineering.wustl.edu/~jain/iiot2/index.html` | Official ZIP download; useful IIoT testbed benchmark. |

Example:

```bash
edge-security fetch-dataset wustl-iiot-2021
edge-security replay-dataset wustl-iiot-2021 --limit 1000
```

## Manual Download Recommended

| Key | Dataset | Source | Why Manual |
|---|---|---|---|
| `ciciot2023` | CICIoT2023 | `https://www.unb.ca/cic/datasets/iotdataset-2023.html` | Official download currently uses a CIC form. |
| `ton-iot` | ToN_IoT | `https://research.unsw.edu.au/projects/toniot-datasets` | Official download is hosted through UNSW SharePoint. |
| `bot-iot` | BoT-IoT | `https://research.unsw.edu.au/projects/bot-iot-dataset` | Official download is hosted through UNSW SharePoint. |
| `edge-iiotset` | Edge-IIoTset | `https://ieee-dataport.org/open-access/edge-iiotset-new-comprehensive-realistic-cyber-security-dataset-iot-iiot` | Manual download required — see section below. |

For manual datasets:

```bash
edge-security replay-csv --path data/datasets/<dataset>/<file>.csv --limit 1000
```

## Safety Notes

- Archives are extracted with path traversal checks.
- Downloaded code or notebooks are never executed.
- The runtime chooses the largest CSV by default unless `--csv-glob` is provided.
- Keep large datasets out of git.
- Treat all attack samples as defensive replay/lab telemetry only.

## Leakage Notes

Some datasets include columns that can leak the answer during ML training. WUSTL-IIoT-2021, for example, warns about identifier/time columns on its official page. For runtime replay, these fields can help preserve flow visibility, but model training should use a reviewed feature list that excludes leakage-prone identifiers.


---

## Edge-IIoTset — Manual Download

Edge-IIoTset is a comprehensive IIoT cyber-security dataset containing 15 traffic
classes (Normal + 14 attack families), captured in a realistic testbed including
sensors, IoT gateways, MQTT brokers, and cloud services.

**Citation:** Ferrag et al., "Edge-IIoTset: A New Comprehensive Realistic Cyber
Security Dataset of IoT and IIoT Applications," IEEE Access, 2022.

### Recommended partition

Use the **DNN-EdgeIIoT** partition (≈ 500K rows). The full dataset is 2.1M rows;
use it for final stress tests after the 500K run is clean.

### Download steps

1. Create a free account at [IEEE DataPort](https://ieee-dataport.org/).
2. Navigate to the Edge-IIoTset dataset page:
   `https://ieee-dataport.org/open-access/edge-iiotset-new-comprehensive-realistic-cyber-security-dataset-iot-iiot`
3. Download the `Edge-IIoTset Dataset.zip` (or the DNN-specific archive).
4. Extract to `data/edge-iiotset/` (path is outside git — see `.gitignore`).

```bash
# After manual download and extraction:
edge-security replay-csv --path data/edge-iiotset/DNN-EdgeIIoT-dataset.csv --limit 5000
```

### 15 traffic classes

| Class | Category | Priority |
|---|---|---|
| `Normal` | Benign | — |
| `DDoS_ICMP` | DDoS — ICMP flood | **High (primary)** |
| `DDoS_UDP` | DDoS — UDP flood | Medium |
| `DDoS_TCP` | DDoS — TCP flood | Medium |
| `DDoS_HTTP` | DDoS — HTTP flood | Medium |
| `Uploading` | Exfiltration / staged upload | **High (primary)** |
| `Downloading` | Suspicious download | Medium |
| `SQL_Injection` | SQL injection | Medium |
| `Password` | Password brute-force | Medium |
| `Vulnerability_scanner` | Port / vuln scan | Medium |
| `Backdoor` | Backdoor activity | Medium |
| `Port_Scanning` | Port scanning | Medium |
| `XSS` | Cross-site scripting traffic | Medium |
| `Ransomware` | Ransomware-driven traffic | **High (primary)** |
| `MITM` | Man-in-the-middle | Medium |

The three **primary** classes (DDoS_ICMP, Uploading, Ransomware) drive the
operator dashboard and demo narrative. All 15 appear in model outputs and alerts.

### Column normalization

`datasets/edge_iiotset.py` handles both dot-notation (raw CSV, e.g. `frame.len`)
and underscore-notation (internal, e.g. `frame_len`) column names. Missing columns
are filled with 0. The loader enforces:

- `timestamp` (float, seconds since epoch, from `frame.time_epoch`)
- 56 numeric feature columns (see `NUMERIC_FEATURE_COLS` in `edge_iiotset.py`)
- `attack_label` (int 0/1)
- `attack_type` (str, one of 15 classes)

### Feature fixture

`tests/fixtures/edge_iiotset_sample_5k.csv` is a **deterministic 5,000-row
synthetic subset** generated from seed=42. It uses the raw Edge-IIoTset dot-notation
column names and spans 250 seconds (50 × 5-second bins → 31 sequences of 20 bins).

This fixture is committed for CI use only. It is **not** a real traffic capture.
Do not use it for model evaluation — use the real dataset downloaded above.

### Safety notes

- Keep the full dataset outside git (`data/` is in `.gitignore`).
- Treat all attack samples as defensive replay / lab telemetry only.
- The fixture is synthetic and does not represent real network traffic.
