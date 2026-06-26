[![中文](https://img.shields.io/badge/lang-zh--CN-red)](README.md)
[![English](https://img.shields.io/badge/lang-en-blue)](README.en.md)
[![Русский](https://img.shields.io/badge/lang-ru-lightgrey)](README.ru.md)
[![日本語](https://img.shields.io/badge/lang-ja-green)](README.ja.md)
[![한국어](https://img.shields.io/badge/lang-ko-orange)](README.ko.md)
[![Français](https://img.shields.io/badge/lang-fr-yellow)](README.fr.md)

# Patient Record Organizer

智能型患者記録整理ツール — 散在する医療資料（写真、PDF、Word、テキスト）を自動分類・構造化抽出し、標準化された HTML/Markdown/DOCX/XLSX の病情档案を生成します。

**コアパイプライン**: 生ファイル → OCR (MinerU batch/single + DeepSeek-OCR) → 匿名化 → LLM構造化抽出 → 集約 → レポート生成

❤️ 小胰宝（Xiaoyibao）コミュニティとオープンソースコントリビューターの皆様に感謝します。

---

## クイックスタート

### 1. 依存関係のインストール

```bash
# 方法1: pyproject.toml（推奨 — venv・lockfile 自動管理）
uv sync

# 方法2: pip
pip install -r requirements.txt
```

### 2. パイプラインの実行方法

```bash
# 方法1: uv run（.venv を自動使用、手動アクティベーション不要）
uv run ./xyb process /path/to/records/ --patient P001 --format all

# 方法2: venv をアクティベートしてから実行
source .venv/bin/activate
./xyb process /path/to/records/ --patient P001 --format all

# 方法3: python 直接呼び出し
python3 scripts/v2/pipeline_v2.py \
  --input-dir /path/to/records/ \
  --output-dir /path/to/output/ \
  --patient-id P001 \
  --format all --open
```

> **備考**: `uv sync` は `.venv` 仮想環境を作成し、全依存関係をインストールします。
> その後 `uv run <command>`（手動アクティベーション不要）または手動アクティベーションのいずれかで実行できます。

### 3. APIキーの設定

```bash
cp .env.example .env
```

必須のキー:

| サービス | 用途 | 環境変数 |
|---------|------|---------|
| **MinerU** | 画像/スキャンPDFのOCR（主力） | `MINERU_API_KEY` / `MINERU_TOKEN` |
| **SiliconFlow** | LLM構造化抽出 + DeepSeek-OCR | `OCR_API_KEY` / `OCR_BASE_URL` |
| **StepFun** | LLMフォールバック | `STEP_API_KEY` |

オプション:

- `OPENAI_API_KEY` — 代替LLM（openai）
- `STEP_API_KEY` — ASR文字起こし

### 3. テスト実行

```bash
pytest tests/ -v
```

---

## 使い方

### CLI（ワンクリック）

```bash
./xyb process /path/to/records/ --patient P001 --format all --open
```

パラメーター:

| フラグ | 説明 |
|--------|------|
| `--patient` | 患者ID（デフォルト: P_report_mess） |
| `--format` | 出力形式: `html` / `md` / `docx` / `xlsx` / `all` |
| `--open` | HTMLを自動で開く |
| `--skip-ocr` | OCRをスキップ（既存.mdのみ処理） |
| `--model` | LLMモデル指定、例: `stepfun:step-3.5-flash` |
| `--force` | 警告を無視 |

### パイプライン直接実行

```bash
python3 scripts/v2/pipeline_v2.py \
  --input-dir /path/to/records/ \
  --output-dir /path/to/output/ \
  --patient-id P001 \
  --format all --open
```

### 単一ファイルOCR

```bash
python3 scripts/ocr_single.py report.jpg -o result.md
python3 scripts/ocr_single.py scan.pdf --engine deepseek --retries 5
```

---

## 出力

| ファイル | 形式 | 説明 |
|---------|------|------|
| `report.html` | HTML | インタラクティブレポート |
| `case_report.md` | Markdown | テキストレポート |
| `report.docx` | Word | Office文書 |
| `report.xlsx` | Excel | 多シート表（検査/遺伝子/画像/経過） |
| `profile.json` | JSON | 患者データ |
| `mdt_analysis.json` | JSON | MDT分析 |
| `mappings.json` | JSON | 匿名化マッピング |

---

## レポート構成

```
1頁: カバー + 概要（1分で把握）
2頁: 治療経過（核心）
3頁: 検査値推移（腫瘍マーカー、血算、生化学）
4頁: 病理と遺伝子
5頁: 投薬計画
6頁: 画像診断
7頁: 注目すべき問題点
8頁: コンサルテーション質問
9頁: 添付資料一覧
```

---

## 機能

- **ゼロ設定** — フォルダを指定して実行するだけ
- **マルチフォーマット入力** — 写真、スキャン、テキストPDF、Word、プレーンテキスト
- **スマートOCRルーティング** — ファイル少数→single MinerU（3回リトライ）; 大PDF(>10頁)/多数(>50)→batch MinerU（≤50/バッチ、並列アップロード）; フォールバック: DeepSeek-OCR→PyMuPDF
- **100万コンテキストLLM** — 全文入力、出力 max_tokens=256K
- **二段階分類** — キーワードルール + LLMセマンティック
- **自動匿名化** — 名前→`[NAME_N]`、電話→`[PHONE_N]`（復元可能）
- **インクリメンタルキャッシュ** — SHA256重複排除; OCR+LLM自動キャッシュ
- **マルチフォーマット出力** — HTML + Markdown + DOCX + XLSX

---

## セキュリティとプライバシー

- ❌ 診断や治療推奨は行いません
- ✅ 「資料整理と構造化アーカイブ」のみ
- **自動匿名化**と復元マッピング
- **免責事項**を全ての出力に付記

---

## License

MIT
