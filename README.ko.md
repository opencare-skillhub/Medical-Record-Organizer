[![中文](https://img.shields.io/badge/lang-zh--CN-red)](README.md)
[![English](https://img.shields.io/badge/lang-en-blue)](README.en.md)
[![Русский](https://img.shields.io/badge/lang-ru-lightgrey)](README.ru.md)
[![日本語](https://img.shields.io/badge/lang-ja-green)](README.ja.md)
[![한국어](https://img.shields.io/badge/lang-ko-orange)](README.ko.md)
[![Français](https://img.shields.io/badge/lang-fr-yellow)](README.fr.md)

# Patient Record Organizer

지능형 환자 기록 정리 도구 — 흩어진 의료 자료(사진, PDF, Word, 텍스트)를 자동으로 분류·구조화하여 표준화된 HTML/Markdown/DOCX/XLSX 보고서를 생성합니다.

**핵심 파이프라인**: 원본 파일 → OCR (MinerU batch/single + DeepSeek-OCR) → 비식별화 → LLM 구조화 추출 → 집계 → 보고서 생성

❤️ 小胰宝(Xiaoyibao) 커뮤니티와 오픈소스 기여자분들께 감사드립니다.

---

## 빠른 시작

### 1. 의존성 설치

```bash
# 방법 1: pyproject.toml (권장 — venv + lockfile 자동 관리)
uv sync

# 방법 2: pip
pip install -r requirements.txt
```

### 2. 파이프라인 실행 방법

```bash
# 방법 1: uv run (.venv 자동 사용, 수동 활성화 불필요)
uv run ./xyb process /path/to/records/ --patient P001 --format all

# 방법 2: venv 활성화 후 실행
source .venv/bin/activate
./xyb process /path/to/records/ --patient P001 --format all

# 방법 3: python 직접 호출
python3 scripts/v2/pipeline_v2.py \
  --input-dir /path/to/records/ \
  --output-dir /path/to/output/ \
  --patient-id P001 \
  --format all --open
```

> **참고**: `uv sync`는 `.venv` 가상 환경을 생성하고 모든 의존성을 설치합니다.
> 이후 `uv run <command>`(수동 활성화 불필요) 또는 수동 활성화 후 실행할 수 있습니다.

### 3. API 키 설정

```bash
cp .env.example .env
```

필수 키:

| 서비스 | 용도 | 환경 변수 |
|--------|------|----------|
| **MinerU** | 이미지/스캔 PDF OCR (주력) | `MINERU_API_KEY` / `MINERU_TOKEN` |
| **SiliconFlow** | LLM 구조화 추출 + DeepSeek-OCR | `OCR_API_KEY` / `OCR_BASE_URL` |
| **StepFun** | LLM 폴백 | `STEP_API_KEY` |

선택 사항:

- `OPENAI_API_KEY` — 대체 LLM (openai)
- `STEP_API_KEY` — ASR 전사

### 3. 테스트 실행

```bash
pytest tests/ -v
```

---

## 사용 방법

### CLI (원클릭)

```bash
./xyb process /path/to/records/ --patient P001 --format all --open
```

매개변수:

| 플래그 | 설명 |
|--------|------|
| `--patient` | 환자 ID (기본값: P_report_mess) |
| `--format` | 출력 형식: `html` / `md` / `docx` / `xlsx` / `all` |
| `--open` | HTML 자동 열기 |
| `--skip-ocr` | OCR 건너뛰기 (기존 .md만 처리) |
| `--model` | LLM 모델 지정, 예: `stepfun:step-3.5-flash` |
| `--force` | 경고 무시 |

### 파이프라인 직접 실행

```bash
python3 scripts/v2/pipeline_v2.py \
  --input-dir /path/to/records/ \
  --output-dir /path/to/output/ \
  --patient-id P001 \
  --format all --open
```

### 단일 파일 OCR

```bash
python3 scripts/ocr_single.py report.jpg -o result.md
python3 scripts/ocr_single.py scan.pdf --engine deepseek --retries 5
```

---

## 출력

| 파일 | 형식 | 설명 |
|------|------|------|
| `report.html` | HTML | 대화형 보고서 |
| `case_report.md` | Markdown | 텍스트 보고서 |
| `report.docx` | Word | Office 문서 |
| `report.xlsx` | Excel | 다중 시트 표 (검사/유전자/영상/경과) |
| `profile.json` | JSON | 환자 데이터 |
| `mdt_analysis.json` | JSON | MDT 분석 |
| `mappings.json` | JSON | 비식별화 매핑 |

---

## 보고서 구조

```
1페이지: 표지 + 개요 (1분 파악)
2페이지: 치료 타임라인 (핵심)
3페이지: 검사치 추이 (종양표지자, 혈액, 생화학)
4페이지: 병리와 유전자
5페이지: 투약 계획
6페이지: 영상 검사
7페이지: 주요 관심 사항
8페이지: 진료 상담 질문
9페이지: 첨부 자료 목록
```

---

## 기능

- **제로 설정** — 폴더만 지정하고 실행
- **다중 형식 입력** — 사진, 스캔, 텍스트 PDF, Word, 일반 텍스트
- **스마트 OCR 라우팅** — 소수 파일 → single MinerU (3회 재시도); 대형 PDF(>10쪽)/다수 파일(>50) → batch MinerU (≤50/배치, 병렬 업로드); 폴백 체인: DeepSeek-OCR → PyMuPDF
- **100만 컨텍스트 LLM** — 전체 텍스트 입력, 출력 max_tokens=256K
- **이중 분류** — 키워드 규칙 + LLM 의미 기반
- **자동 비식별화** — 이름→`[NAME_N]`, 전화→`[PHONE_N]` (복원 가능)
- **증분 캐시** — SHA256 중복 제거; OCR+LLM 자동 캐시
- **다중 형식 출력** — HTML + Markdown + DOCX + XLSX

---

## 보안 및 개인정보

- ❌ 진단이나 치료 권고를 하지 않습니다
- ✅ "자료 정리 및 구조화"만 수행
- **자동 비식별화** 및 복원 매핑
- **면책 조항**을 모든 출력에 포함

---

## License

MIT
