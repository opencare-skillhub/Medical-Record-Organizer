[![中文](https://img.shields.io/badge/lang-zh--CN-red)](README.md)
[![English](https://img.shields.io/badge/lang-en-blue)](README.en.md)
[![Русский](https://img.shields.io/badge/lang-ru-lightgrey)](README.ru.md)
[![日本語](https://img.shields.io/badge/lang-ja-green)](README.ja.md)
[![한국어](https://img.shields.io/badge/lang-ko-orange)](README.ko.md)
[![Français](https://img.shields.io/badge/lang-fr-yellow)](README.fr.md)

# Patient Record Organizer

智能病案整理助手：将零散的医疗资料（照片、PDF、Word、文本）自动归类、结构化提取，生成标准化的 HTML/Markdown/DOCX/XLSX 病情档案。

**核心链路**: 原始文件 → OCR (MinerU batch/single + DeepSeek-OCR fallback) → 脱敏 → LLM 结构化提取 → 聚合 → 报告渲染

感谢小胰宝社区 / 小x宝社区开源开发者的 ❤️ 贡献

---

## 快速开始

### 1. 安装依赖

```bash
# pyproject.toml 方式（推荐）
uv sync

# 或 pip 方式
pip install -r requirements.txt
```

### 2. 配置 API Key

```bash
cp .env.example .env
```

必需配置的密钥：

| 服务 | 用途 | 环境变量 |
|------|------|---------|
| **MinerU** | 图片/扫描 PDF OCR（主链路） | `MINERU_API_KEY` / `MINERU_TOKEN` |
| **SiliconFlow** | LLM 结构化提取（Map 阶段）+ DeepSeek-OCR fallback | `OCR_API_KEY` / `OCR_BASE_URL` |
| **StepFun** | LLM 备选（Map 阶段 fallback） | `STEP_API_KEY` |

可选配置：

- `OPENAI_API_KEY` — LLM 备选（openai 模型）
- `STEP_API_KEY` — ASR 录音转写

### 3. 运行测试

```bash
pytest tests/ -v
```

---

## 使用方式

### 命令行（一键处理）

```bash
# 处理一个目录下的病历资料
./xyb process /path/to/病历/ --patient P001 --format all --open
```

参数说明：

| 参数 | 说明 |
|------|------|
| `--patient` | 患者 ID（默认 P_report_mess） |
| `--format` | 输出格式：`html` / `md` / `docx` / `xlsx` / `all` / `doc` / `xls` |
| `--open` | 生成后自动打开 HTML |
| `--skip-ocr` | 跳过 OCR（仅处理已有 .md） |
| `--model` | 指定 LLM 模型，如 `stepfun:step-3.5-flash` |
| `--force` | 忽略依赖缺失警告 |

### 直接运行流水线

```bash
python3 scripts/v2/pipeline_v2.py \
  --input-dir /path/to/病历/ \
  --output-dir /path/to/output/ \
  --patient-id P001 \
  --format all \
  --open
```

### 单文件 OCR 提取

```bash
# 快速提取单张图片/PDF
python3 scripts/ocr_single.py report.jpg -o result.md

# 指定引擎（auto / mineru / deepseek / pymupdf / batch）
python3 scripts/ocr_single.py scan.pdf --engine deepseek --retries 5
```

---

## 输出说明

| 文件 | 格式 | 说明 |
|------|------|------|
| `report.html` | HTML | 交互式报告（浏览器查看） |
| `case_report.md` | Markdown | 文本报告（可打印/分享） |
| `report.docx` | Word | Office 文档（医生工作站） |
| `report.xlsx` | Excel | 多工作表数据表（检验/基因/影像/时间线） |
| `profile.json` | JSON | 聚合后的病情档案数据 |
| `mdt_analysis.json` | JSON | MDT 多学科分析 |
| `mappings.json` | JSON | 脱敏映射表 |

### 报告结构

```
第1页: 封面 + 病情速览（1分钟掌握）
第2页: 诊疗时间线（核心）
第3页: 检查指标趋势（肿瘤标志物、血常规、生化）
第4页: 病理与基因
第5页: 用药方案
第6页: 影像检查
第7页: 关注问题要点
第8页: 问诊咨询建议
第9页: 附件目录
```

---

## 项目结构

```
patient-record-organizer/
├── xyb                         # CLI 入口
├── pyproject.toml              # 项目配置与依赖管理
├── requirements.txt            # pip 依赖（同步自 pyproject.toml）
├── requirements-ocr.txt        # 可选离线 OCR 依赖
├── .env.example                # 环境变量示例
├── .gitignore
│
├── scripts/                    # 核心代码
│   ├── ocr_single.py          # 单文件 OCR 提取（独立脚本）
│   ├── v2/                    # v2 流水线（当前主链路）
│   │   ├── pipeline_v2.py    # 端到端流水线编排
│   │   ├── route_ocr.py      # OCR 路由（MinerU batch/single + DeepSeek-OCR + PyMuPDF）
│   │   ├── desensitize.py    # 患者数据脱敏
│   │   ├── map_extract.py    # LLM 结构化提取（Map 阶段，max_tokens=256K）
│   │   ├── reduce_merge.py   # 同类数据合并（Reduce 阶段）
│   │   ├── shuffle_group.py  # 数据分组归类
│   │   ├── render_html.py    # HTML 报告渲染
│   │   ├── render_docx.py    # Word 文档导出
│   │   ├── render_xlsx.py    # Excel 多工作表导出
│   │   └── llm_client.py     # LLM 调用封装（多 provider 支持）
│   ├── mdt_analysis.py       # MDT 多学科分析
│   ├── render_md.py          # Markdown 报告渲染
│   ├── preflight.py          # 依赖自检
│   └── ingest.py             # 资料接入
│
├── references/                # 模板与规则
│   ├── html-report-template.html      # HTML 报告 Jinja2 模板
│   ├── html-report-template-2.html
│   ├── case-report-template.md        # Markdown 报告模板
│   ├── classification-rules.md        # 分类关键词
│   └── report-agent.md                # Agent 设计文档
│
├── doc/                        # 设计文档
│   ├── AGENTS.md              # 报告生成 Agent 规范
│   ├── fix-plan.md            # 优化/修复计划
│   ├── workflow.md            # 工作流说明
│   ├── mineru_batch_api.md    # MinerU 批量 API 文档
│   ├── patient-profile-schema-v1.md  # 患者档案 Schema
│   ├── data-contract.md       # 数据契约
│   └── mdt-analysis-plan.md   # MDT 分析方案
│
└── tests/                      # 单元测试
    ├── test_route_ocr.py
    ├── test_cli.py
    ├── test_preflight.py (stub)
    └── v2/
        ├── test_map_extract.py
        └── test_pipeline_v2.py
```

---

## 核心特性

- **零门槛接入** — 直接上传文件或提供目录路径
- **多格式支持** — 照片、扫描件、文字 PDF、Word（DOCX）、文本
- **智能 OCR 路由** — 少量文件 → single MinerU（带 3 次重试）；大 PDF(>10页)或多文件(>50) → batch MinerU（≤50/批并行）；失败时 DeepSeek-OCR → PyMuPDF 逐级托底
- **百万上下文 LLM** — 全量发送无需截断，输出端 max_tokens=256K，基因报告等 42+ 条突变完整提取
- **两级分类** — 关键词规则（零成本）+ LLM 语义兜底
- **自动脱敏** — 姓名→`[NAME_N]`、电话→`[PHONE_N]`、身份证→`[ID_N]`，映射本地保存可回填
- **增量缓存** — SHA256 去重，OCR+LLM 结果自动缓存复用
- **多格式输出** — HTML（交互式）+ Markdown（可打印）+ DOCX（Word 文档）+ XLSX（Excel 多工作表）

---

## 安全与隐私

- ❌ 不作诊断，不出治疗建议，不替代医嘱
- ✅ 只做"资料整理与结构化归档"
- **自动脱敏**：姓名 → `[NAME_N]`，电话 → `[PHONE_N]`，身份证 → `[ID_N]`，含映射回填
- **免责声明**：所有输出附带，不构成医学建议

---

## License

MIT
