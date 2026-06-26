[![中文](https://img.shields.io/badge/lang-zh--CN-red)](README.md)
[![English](https://img.shields.io/badge/lang-en-blue)](README.en.md)
[![Русский](https://img.shields.io/badge/lang-ru-lightgrey)](README.ru.md)
[![日本語](https://img.shields.io/badge/lang-ja-green)](README.ja.md)
[![한국어](https://img.shields.io/badge/lang-ko-orange)](README.ko.md)
[![Français](https://img.shields.io/badge/lang-fr-yellow)](README.fr.md)

# Patient Record Organizer

Intelligent Patient Record Organizer — automatically classifies, extracts, and structures scattered medical documents (photos, PDFs, Word, text) into standardized HTML/Markdown/DOCX/XLSX case reports.

**Core Pipeline**: Raw files → OCR (MinerU batch/single + DeepSeek-OCR fallback) → Desensitization → LLM structured extraction → Aggregation → Report rendering

Special thanks to the ❤️ 小胰宝 (Xiaoyibao) community & open-source contributors.

---

## Quick Start

### 1. Install Dependencies

```bash
# pyproject.toml (recommended)
uv sync

# or pip
pip install -r requirements.txt
```

### 2. Configure API Keys

```bash
cp .env.example .env
```

Required keys:

| Service | Purpose | Env Variable |
|---------|---------|-------------|
| **MinerU** | Image/scanned PDF OCR (primary) | `MINERU_API_KEY` / `MINERU_TOKEN` |
| **SiliconFlow** | LLM structured extraction (Map phase) + DeepSeek-OCR fallback | `OCR_API_KEY` / `OCR_BASE_URL` |
| **StepFun** | LLM fallback (Map phase) | `STEP_API_KEY` |

Optional:

- `OPENAI_API_KEY` — LLM alternative (openai models)
- `STEP_API_KEY` — ASR transcription

### 3. Run Tests

```bash
pytest tests/ -v
```

---

## Usage

### CLI (One-Click)

```bash
# Process a directory of medical records
./xyb process /path/to/records/ --patient P001 --format all --open
```

Parameters:

| Flag | Description |
|------|-------------|
| `--patient` | Patient ID (default: P_report_mess) |
| `--format` | Output format: `html` / `md` / `docx` / `xlsx` / `all` / `doc` / `xls` |
| `--open` | Auto-open HTML report |
| `--skip-ocr` | Skip OCR (process existing .md only) |
| `--model` | LLM model, e.g. `stepfun:step-3.5-flash` |
| `--force` | Ignore dependency warnings |

### Run Pipeline Directly

```bash
python3 scripts/v2/pipeline_v2.py \
  --input-dir /path/to/records/ \
  --output-dir /path/to/output/ \
  --patient-id P001 \
  --format all \
  --open
```

### Single-File OCR

```bash
# Quick text extraction from a single image/PDF
python3 scripts/ocr_single.py report.jpg -o result.md

# Specify engine (auto / mineru / deepseek / pymupdf / batch)
python3 scripts/ocr_single.py scan.pdf --engine deepseek --retries 5
```

---

## Outputs

| File | Format | Description |
|------|--------|-------------|
| `report.html` | HTML | Interactive report (browser) |
| `case_report.md` | Markdown | Text report (printable) |
| `report.docx` | Word | Office document |
| `report.xlsx` | Excel | Multi-sheet spreadsheet (lab/genetics/imaging/timeline) |
| `profile.json` | JSON | Aggregated patient data |
| `mdt_analysis.json` | JSON | MDT analysis |
| `mappings.json` | JSON | Desensitization mapping |

### Report Structure

```
Page 1: Cover + Quick Overview (1-minute summary)
Page 2: Treatment Timeline (core)
Page 3: Lab Trends (tumor markers, blood routine, biochemistry)
Page 4: Pathology & Genetics
Page 5: Medication Regimen
Page 6: Imaging Studies
Page 7: Key Concerns
Page 8: Consultation Questions
Page 9: Attachment Index
```

---

## Project Structure

```
patient-record-organizer/
├── xyb                         # CLI entry
├── pyproject.toml              # Project config & dependency mgmt
├── requirements.txt            # pip deps (synced from pyproject.toml)
├── requirements-ocr.txt        # Optional offline OCR deps
├── .env.example                # Env vars template
├── .gitignore
│
├── scripts/                    # Core code
│   ├── ocr_single.py          # Single-file OCR (standalone)
│   ├── v2/                    # v2 pipeline (current mainline)
│   │   ├── pipeline_v2.py    # End-to-end pipeline orchestration
│   │   ├── route_ocr.py      # OCR routing (MinerU batch/single + DeepSeek-OCR + PyMuPDF)
│   │   ├── desensitize.py    # Patient data redaction
│   │   ├── map_extract.py    # LLM structured extraction (Map phase, max_tokens=256K)
│   │   ├── reduce_merge.py   # Data merging (Reduce phase)
│   │   ├── shuffle_group.py  # Data grouping
│   │   ├── render_html.py    # HTML report renderer
│   │   ├── render_docx.py    # Word document export
│   │   ├── render_xlsx.py    # Excel multi-sheet export
│   │   └── llm_client.py     # LLM client (multi-provider)
│   ├── mdt_analysis.py       # MDT analysis
│   ├── render_md.py          # Markdown report renderer
│   ├── preflight.py          # Dependency checker
│   └── ingest.py             # Data ingestion
│
├── references/                # Templates & rules
│   ├── html-report-template.html      # HTML Jinja2 template
│   ├── html-report-template-2.html
│   ├── case-report-template.md        # Markdown template
│   ├── classification-rules.md        # Classification rules
│   └── report-agent.md                # Agent design doc
│
├── doc/                        # Design documents
│   ├── AGENTS.md              # Agent specification
│   ├── fix-plan.md            # Optimization plan
│   ├── workflow.md            # Workflow guide
│   ├── mineru_batch_api.md    # MinerU batch API docs
│   ├── patient-profile-schema-v1.md  # Patient profile schema
│   ├── data-contract.md       # Data contract
│   └── mdt-analysis-plan.md   # MDT analysis plan
│
└── tests/                      # Unit tests
    ├── test_route_ocr.py
    ├── test_cli.py
    ├── test_preflight.py (stub)
    └── v2/
        ├── test_map_extract.py
        └── test_pipeline_v2.py
```

---

## Features

- **Zero-config** — Point at a directory and run
- **Multi-format input** — Photos, scans, text PDFs, Word (DOCX), plain text
- **Smart OCR routing** — Few small files → single MinerU (3 retries); large PDF (>10 pages) or many files (>50) → batch MinerU (≤50/batch, parallel upload); fallback chain: DeepSeek-OCR → PyMuPDF
- **1M-context LLM** — Full-text input without truncation; output max_tokens=256K ensures 42+ genetic mutations complete
- **Two-tier classification** — Keyword rules (zero cost) + LLM semantic fallback
- **Auto-redaction** — Name→`[NAME_N]`, Phone→`[PHONE_N]`, ID→`[ID_N]`; mapping saved locally for reversal
- **Incremental cache** — SHA256 dedup; OCR + LLM results auto-cached
- **Multi-format output** — HTML (interactive) + Markdown (printable) + DOCX (Word) + XLSX (Excel)

---

## Security & Privacy

- ❌ No diagnosis, no treatment recommendations, not a substitute for medical advice
- ✅ "Data organization & structured archiving" only
- **Auto-redaction**: Name → `[NAME_N]`, Phone → `[PHONE_N]`, ID → `[ID_N]` with reversible mapping
- **Disclaimer**: included with all outputs

---

## License

MIT
