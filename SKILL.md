---
name: patient-record-organizer
description: >
  智能病案整理助手：将零散的医疗资料（照片、PDF、文本、录音）
  自动分类归档，生成结构化病例档案。
  当用户提到"整理病历"、"整理检查报告"、"归类病情资料"、"生成病例档案"、
  "病情整理"、"病例模板"、"我的检查报告"、"出院小结整理"时触发。
---

# Patient Record Organizer

## 工作流程

### 第一步：接收与扫描

**目标**：接收用户上传的文件或路径，建立 patient_id 并检查增量模式。

**执行**：
1. 如果用户直接上传文件：调用 `scripts/ingest.py:collect([file_path])`
2. 如果用户提供本地目录路径：调用 `scripts/ingest.py:collect([dir_path])`
3. 如果用户上传 zip：同上，`collect()` 会自动解压并递归扫描

**输出**：向用户展示文件清单
```
收到 N 个文件：
- 图片 X 张（化验单 X、处方 X、病历卡 X、其他 X）
- PDF X 份（出院小结 X、CT报告 X、基因检测 X）
- 录音 X 段（约 X 分钟）
- 文本/Word X 份
```

**确认点**：等待用户确认分类是否正确，或有需要调整的地方。

**安全边界**：
- ❌ 不作诊断
- ❌ 不给出治疗建议
- ❌ 不替代医嘱和处方
- ✅ 只做"资料整理与结构化归档"

---

### 第二步：内容提取

**目标**：对每个文件进行 OCR/ASR/解析，提取纯文本。

**执行**：
1. 图片（JPG/PNG/HEIC）：调用 `scripts/route_ocr.py:extract_text()` → 引擎 A（SiliconFlow DeepSeek-OCR）
2. PDF：
   - 文字型且 ≤5页 → 引擎 A 逐页提取
   - 复杂/扫描/含表格 → 引擎 B（MinerU，需配置 `MINERU_API_KEY` 和 `MINERU_API_URL`）
3. 录音（MP3/M4A/WAV）：调用 `scripts/asr_stepfun.py:transcribe()` → 引擎 C（SSE，StepAudio 2.5，默认）
   - 仅当需词级字幕对齐 / 双声道分离 / 本地超长文件已有公网 URL 时，提示用户需走引擎 D（异步，1期接口预留）
4. Word（.docx）：直接读取文本
5. 文本（.txt/.md）：直接读取

**缓存**：提取结果缓存到 `extracted/{sha256}.txt`，避免重复处理。

**失败处理**：任何提取失败，标记 `[OCR失败-需人工确认]` 或 `[ASR失败-需人工确认]`，不中断主流程。

**确认点**：展示提取结果摘要，等待用户确认。

---

### 第三步：自动分类

**目标**：将提取的文本按医疗报告类型分类。

**执行**：
1. 调用 `scripts/classify.py:classify(text)`：
   - 第一层：规则关键词快速匹配（血常规→检验指标、CT→影像检查...）
   - 第二层：LLM 语义兜底（需配置 `DASHSCOPE_API_KEY`，调用 qwen3-flash）
2. 从文本中提取日期（兼容 `2024-03-15`、`2024年3月15日`、`24/03/15`）
3. 回写 `manifest.json` 和 `timeline.json`

**分类体系**（11类）：
```
📂 患者病历
├── 📋 基本信息（主诉/现病史/既往史/过敏史/家族史）
├── 📊 检验指标（血常规/生化/肿瘤标志物/凝血/其他）
├── 🏥 影像检查（CT/MRI/PET-CT/超声/X-ray/内镜）
├── 🔬 病理报告（组织病理/细胞学/分子病理/基因检测）
├── 💊 用药方案（处方/化疗方案/靶向/免疫治疗）
├── 📝 诊疗记录（出院小结/门诊记录/手术记录/治疗小结）
└── 📎 其他资料（医保/费用/营养/护理/健康教育）
```

**确认点**：展示分类结果，等待用户确认/调整。

---

### 第四步：时间线构建

**目标**：按日期排序构建诊疗时间线。

**执行**：
1. 从 `timeline.json` 读取已有时间线（增量模式）
2. 新文件按提取的日期插入正确位置
3. 同日期的按分类分组

**输出**：
```
📅 诊疗时间线：
  ─ 2024-03-15  首诊，肺腺癌确诊（EGFR 19del）
  ─ 2024-03-20  基因检测报告
  ─ 2024-04-01  一线治疗开始：奥希替尼 80mg QD
  ─ 2024-07-10  CT 评估：PR
```

**确认点**：展示时间线，等待用户确认。

---

### 第五步：填充模板与生成报告

**目标**：按 `references/case-report-template.md` 结构生成病例档案。

**执行**：
1. 调用 `scripts/render_report.py:render_md()` 生成 Markdown
2. 调用 `scripts/render_report.py:render_html()` 生成 HTML（需安装 `markdown` 库）
3. 可选：调用外部工具生成 PDF（weasyprint，V2 启用）和 DOCX（pandoc/python-docx，V2 启用）

**输出格式**：
- Markdown（.md）：知识库归档、版本控制
- HTML（.html）：在线查看、分享
- PDF（.pdf）：打印、带去医院复诊（V2）
- Word（.docx）：医院系统导入（V2）

**信息缺口提示**：
- 自动检测缺少的类别（如缺少影像检查、病理报告等）
- 建议补充的信息（如过敏史、最近化疗方案等）

**确认点**：询问用户需要哪些格式，生成后展示文件路径。

---

### 第六步：更新 manifest 与持久化

**目标**：更新患者档案状态，支持跨会话增量更新。

**执行**：
1. 调用 `scripts/manifest.py:write_manifest()` 回写 manifest
2. 更新 `updated_at` 时间戳
3. 文件使用 SHA256 哈希去重，避免重复处理

**输出**：
```
✅ 病例档案已生成：
   - case_report.md
   - report.html

📁 患者档案位置：~/patients/{patient_id}/
   - manifest.json（文件索引与分类记录）
   - sources/（原始文件）
   - extracted/（提取后的文本）
   - output/（生成的病例档案）
   - timeline.json（时间线数据）
```

**后续操作**：
- 用户随时可以追加新文件，Agent 会自动增量更新
- 用户可随时调整分类（"第3张是病理报告不是化验单"）

---

## 安全边界（必须遵守）

- **不作诊断**：本工具仅整理资料，不提供诊断
- **不解读检验结果**：只标注异常值，不做临床解读
- **强制免责声明**：所有输出必须附带免责声明
- **危急值强提醒**：如遇血钾 7.0、血红蛋白极低等危急值，立即提示用户就医
- **隐私保护**：manifest 仅本地存储，不上传任何外部服务
- **日志脱敏**：不记录原始医疗文本/录音原文，只记文件 ID、类别、错误类型

## 执行规范（铁律）

### 技能模板不可变性

技能标准代码模板（`scripts/`、`references/`、`SKILL.md` 本身）是**只读常量**。

**默认规则：严格禁止修改。** 执行任务时，无论出于何种目的，都不得修改技能模板文件。

| 类别 | 示例 | 处理方式 |
|------|------|----------|
| **技能模板（默认只读）** | `scripts/ingest.py`、`references/case-report-template.md` | 仅调用，不修改 |
| **运行时临时产物（可变）** | 为处理某目录生成的辅助脚本、中间文件 | 创建在 `temp/` 或 `output/`，与技能模板隔离 |
| **用户确认后的持久产物** | 最终报告、manifest | 创建在 `output/` 或 `~/patients/{patient_id}/` |

**例外条件（必须同时满足）：**
1. 用户明确授权："可以修改模板" 或类似明确指示
2. 修改目的是修复错误或改善功能
3. 修改范围最小化（仅修改必要部分）
4. 修改后告知用户具体改动内容

**例外流程：**
1. 识别需要修改的模板文件
2. **暂停并告知用户**：发现模板问题，建议修改方案
3. 等待用户明确授权
4. 获得授权后执行最小化修改
5. 报告修改内容

### 临时目录规范

当任务需要生成辅助脚本或中间文件时，必须遵循以下流程：

1. **创建独立临时目录**（不与技能模板混放）
   ```
   temp/{skill_run_id}_{timestamp}/
   ├── working/     ← 处理中的中间文件
   ├── output/      ← 本次运行最终产物
   └── helpers/     ← 本次任务生成的辅助脚本
   ```

2. **辅助脚本放在 `helpers/`**，而非技能 `scripts/` 目录
   - ❌ 禁止：直接修改 `scripts/` 下的技能模板
   - ✅ 允许：在 `temp/.../helpers/` 中创建一次性脚本

3. **清理策略**（取决于用户要求）
   - 用户未指定 → 保留在 `temp/` 中，任务结束后告知用户路径
   - 用户要求清理 → 删除整个 `temp/{skill_run_id}_{timestamp}/` 目录
   - 用户要求保留 → 将 `output/` 移动到持久目录（如 `output/{patient_id}/`）

4. **禁止的行为**
   - ❌ 修改 `scripts/` 下的任何技能模板文件（未获授权时）
   - ❌ 在 `references/` 下添加运行时生成的模板
   - ❌ 将临时产物混入技能标准目录
   - ❌ 删除或重命名技能模板文件（即使备份也不行）

### 为什么必须遵守

| 风险 | 说明 |
|------|------|
| **状态污染** | 模板被修改后，下次调用从"脏"状态开始，结果不可预期 |
| **多会话竞态** | 多个用户/任务同时调用同一技能，互相覆盖修改 |
| **追踪困难** | Bug 无法区分：是模板本身的问题，还是某次运行时修改导致的？ |
| **复现失败** | 同样的输入在不同时间运行，因为模板状态不同而产出不同结果 |

---

## 交互原则

- **每步确认**：每步操作后展示结果，等待用户确认
- **用户可调整**：分类错误时交互式修正，不覆盖用户已调整的内容
- **失败不中断**：OCR/ASR/LLM 调用失败有兜底，不中断主流程
- **透明成本**：告知用户 API 调用成本（日均约 ¥2–6）

---

## 触发词

当用户提到以下关键词时，自动触发本 Skill：
- "整理病历"
- "整理检查报告"
- "归类病情资料"
- "生成病例档案"
- "病情整理"
- "病例模板"
- "我的检查报告"
- "出院小结整理"
- "患者资料归档"

---

## 依赖与配置

### 环境变量（.env）

```bash
# 必需：SiliconFlow（DeepSeek-OCR 主力引擎）
SILICONFLOW_API_KEY=sk-xxxxxxxx

# 必需：MinerU（复杂 PDF 深度解析，可选但推荐）
MINERU_API_KEY=your-mineru-key
# MINERU_API_URL=https://your-mineru-instance.com

# 必需：StepFun（录音 ASR：StepAudio 2.5 SSE 主力）
STEP_API_KEY=sk-xxxxxxxx

# 推荐：DashScope（语义分类 LLM 兜底）
DASHSCOPE_API_KEY=sk-xxxxxxxx
```

### 脚本调用示例

```bash
# 1. 资料收集
python scripts/ingest.py ~/Downloads/病历资料/

# 2. manifest 初始化
python scripts/manifest.py --patient P001 --init --name '张三' --age 62

# 3. OCR 提取
python scripts/route_ocr.py tests/fixtures/blood_test.jpg

# 4. 录音转写（SSE 默认）
python scripts/asr_stepfun.py tests/fixtures/voice_memo.mp3

# 5. 分类
python scripts/classify.py tests/fixtures/extracted_sample.txt

# 6. 生成报告
python scripts/render_report.py --patient P001 --format md
python scripts/render_report.py --patient P001 --format html
```

---

## 路由决策备忘

### OCR 路由

```
图片 → DeepSeek-OCR（SiliconFlow）
文字型 PDF ≤5页 → DeepSeek-OCR 逐页
复杂/扫描 PDF → MinerU
```

### ASR 路由（PRD 6.4）

```
默认全部 → 引擎 C（SSE，StepAudio 2.5，0.15 元/小时，5分钟音频1秒出）
仅当以下任一条件 → 引擎 D（异步，接口预留，1期不调用）：
  1. 需词级时间戳做字幕对齐
  2. 双声道录音需拆分两人对话
  3. 本地超长文件已有公网 URL（>30min）
```

---

## 网盘用户引导话术

> "请从夸克/百度网盘下载文件到本地，然后告诉我文件夹路径，或者直接发给我就行。"

## DICOM 提示语

> "影像分析暂不支持，可帮您整理影像报告文字内容（CT报告PDF等）。"

---

## 附录：开发任务清单（1期 MVP）

| ID | 任务 | 状态 |
|----|------|------|
| T0 | 初始化项目骨架与依赖 | ✅ |
| T1 | 资料收集器 scripts/ingest.py | ✅ |
| T2 | manifest 初始化与增量判定 scripts/manifest.py | ✅ |
| T3 | OCR 双引擎路由 scripts/route_ocr.py | ✅ |
| T4 | 两层分类 + 日期提取 scripts/classify.py | ✅ |
| T8 | ASR 引擎 C (StepAudio 2.5 SSE) scripts/asr_stepfun.py | ✅ |
| T5 | 报告渲染器 scripts/render_report.py | ✅ |
| T6 | 报告模板精修 references/case-report-template.md | ✅ |
| T7 | SKILL.md 工作流串联 | ✅ |
