# Patient Record Organizer

智能病案整理助手：将零散的医疗资料（照片、PDF、Word、文本、录音）自动归类、结构化，生成标准化的病情档案。

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，填入以下环境变量：
# - OCR_API_KEY / OCR_BASE_URL / OCR_MODEL：SiliconFlow DeepSeek-OCR fallback（可选）
# - MINERU_API_KEY 或 MINERU_TOKEN：复杂/扫描 PDF、图片深度解析（可选）
# - STEP_API_KEY：录音转写（必填，如需 ASR）
# - EDGEONE_PAGES_API_TOKEN：发布到 EdgeOne Pages（可选）

# 3. 运行测试
pytest tests/ -v
```

## 使用方式

### 命令行（xyb）

```bash
# 直接运行（开发模式）
./xyb --help

# 或通过 pip 安装后全局使用
pip install -e .
xyb --help
```

**常用命令**：

```bash
# 收集资料
./xyb ingest ~/Downloads/病历资料/

# 初始化患者档案
./xyb manifest --init --patient P001 --name '张三' --age 62

# 一键处理（OCR/ASR + 分类 + 报告）
./xyb process ~/Downloads/病历资料/ --patient P001 --format both

# 查看版本历史
./xyb history P001

# 对比两个版本差异
./xyb diff P001 v001 v002

# 回滚到指定版本
./xyb rollback P001 v001

# OCR 提取
./xyb ocr blood_test.jpg

# 录音转写
./xyb asr voice_memo.mp3

# 文本分类
./xyb classify extracted_text.txt

# 生成报告
./xyb render --patient P001 --format both
```

### 直接上传文件

将化验单照片、PDF、录音等直接发给 Agent，Agent 会自动：
1. 扫描文件清单
2. OCR/ASR 提取内容
3. 自动分类（血常规 → 检验指标、CT → 影像检查...）
4. 生成 Markdown + HTML 病例档案

### 提供本地目录

```
"我的病历资料在 ~/Downloads/张三病历/"
```

Agent 会递归扫描目录下所有支持格式。

### 上传 zip 压缩包

直接上传包含混合文件的 zip，Agent 自动解压后处理。

## 输出示例

```
📋 分类结果：
├── 检验指标 (8) ← 血常规×3、生化×2、肿瘤标志物×2、凝血×1
├── 影像检查 (1) ← 胸部CT×1
├── 病理报告 (1) ← 基因检测×1
├── 用药方案 (2) ← 处方×2
├── 诊疗记录 (1) ← 出院小结×1
└── ⚠️ 待确认 (4)

📅 诊疗时间线：
  ─ 2024-03-15  首诊，肺腺癌确诊
  ─ 2024-03-20  基因检测报告
  ─ 2024-04-01  一线治疗开始

✅ 病例档案已生成：
   - output/case-report.md
   - output/case-report.html
```

## 项目结构

```
patient-record-organizer/
├── xyb                      # CLI 入口（直接运行）
├── scripts/
│   ├── ingest.py          # 资料接入层（三种方式）
│   ├── manifest.py        # 患者档案管理（SHA256 去重）
│   ├── route_ocr.py       # 文档解析路由（PyMuPDF + MinerU + DS-OCR fallback）
│   ├── classify.py        # 两层分类 + 日期提取
│   ├── asr_stepfun.py     # ASR 引擎 C（SSE，StepAudio 2.5）
│   ├── render_report.py   # 报告渲染器（MD + HTML + PDF + DOCX）
│   └── desensitize.py     # 患者数据脱敏工具
├── references/
│   ├── case-report-template.md  # 病例档案 Jinja2 模板
│   └── classification-rules.md  # 分类关键词词库
├── tests/                 # 单元测试（114 passed）
├── PRD.md                 # 产品需求文档
├── SKILL.md               # Agent 工作流编排
├── requirements.txt       # Python 依赖
└── .env.example           # 环境变量配置示例
```

## 脚本调用示例

```bash
# 1. 资料收集
./xyb ingest ~/Downloads/病历资料/

# 2. manifest 初始化
./xyb manifest --init --patient P001 --name '张三' --age 62

# 3. OCR 提取
./xyb ocr blood_test.jpg

# 4. 录音转写（SSE 默认）
./xyb asr voice_memo.mp3

# 5. 分类
./xyb classify extracted_text.txt

# 6. 生成报告
./xyb render --patient P001 --format both
```

## 核心特性

- **零门槛接入**：直接上传文件，或提供目录路径，或上传 zip
- **多格式支持**：照片、PDF、Word（DOCX）、文本、录音
- **统一解析路由**：文字型 PDF 用 PyMuPDF 本地提取；扫描/复杂 PDF 与图片用 MinerU；DS-OCR 作为最终 fallback
- **极速 ASR**：StepAudio 2.5 SSE，5 分钟音频 1 秒出，0.15 元/小时
- **两层分类**：关键词规则（零成本）+ LLM 语义兜底
- **增量更新**：SHA256 去重，跨会话持久化，分析结果自动缓存复用
- **多格式输出**：Markdown + HTML + PDF + DOCX
- **记忆系统**：版本快照、差异对比、一键回滚
- **公网发布**：一键部署到 EdgeOne Pages（需配置 Token）

## 安全边界

- ❌ 不作诊断
- ❌ 不给出治疗建议
- ❌ 不替代医嘱和处方
- ✅ 只做"资料整理与结构化归档"

所有输出附带免责声明，不构成医学诊断或治疗建议。

## API 成本估算

日均处理 100 张图片 + 20 份 PDF + 几段录音：
- OCR：~¥1-4/天
- ASR：~¥0.15/小时
- LLM（分类）：极低
- **合计约 ¥2–6/天**

## License

MIT
