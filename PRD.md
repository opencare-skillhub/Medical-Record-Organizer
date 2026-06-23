# Patient Record Organizer — Skill 设计 PRD

> **版本**: v1.1
> **日期**: 2026-06-21
> **类型**: ZCode Skill
> **作者**: sam123
> **变更说明**: 统一资料接入边界决策（6种方式评估）、明确1期/推迟/不纳入范围、补充开发任务清单与验收标准；6.4 ASR 路由微调为"默认全部 → 引擎 C（SSE/StepAudio 2.5），仅特殊场景 → 引擎 D（异步）"

---

## 1. 产品定位

一个 **Skill 级别的智能病案整理助手**，帮助患者家属、照护者、基层医生将零散的医疗资料（照片、PDF、文本、录音）自动归类、结构化，生成标准化的病情档案。

**不做的事（安全边界）：**
- ❌ 不作诊断
- ❌ 不给出治疗建议
- ❌ 不替代医嘱和处方
- ✅ 只做"资料整理与结构化归档"

---

## 2. 目标用户

| 角色 | 使用场景 |
|------|----------|
| **患者家属/照护者** | 手里一堆化验单照片、出院小结 PDF、录音，想整理成一份清晰病情档案，方便复诊时给医生看 |
| **基层医生** | 接诊转诊患者，需要快速了解既往诊疗全貌，但患者提供的资料零散无序 |
| **科研人员** | 收集病例资料做回顾性研究，需要结构化的病例档案 |

---

## 3. 核心工作流

```
输入阶段                    处理阶段                      输出阶段
─────────                ─────────                    ─────────
文件/录音/文本   →   识别 → 提取 → 分类 → 归档   →   病例模板 + 分类目录 + 摘要
   (多格式)           (多模态)     (AI分类)      (PDF/DOC/MD/HTML)
```

### 3.1 初始建档

```
用户上传第一批文件（图片×N, PDF×N, 文本×N, 录音×N）
  → Agent 扫描全部文件，列出清单
  → 逐一识别/提取内容
  → 按内容关键词自动分类
  → 按时间线排序
  → 填入病例模板
  → 生成结构化病情档案（输出为 PDF/DOC/MD/HTML）
  → 展示分类结果，用户可确认/调整
```

### 3.2 增量更新

```
用户新增文件（"这是今天的新化验单"）
  → Agent 识别新文件内容
  → 自动归入对应分类
  → 更新时间线
  → 重新生成病例档案（用户可指定格式）
```

### 3.3 交互式调整

```
用户: "这张照片不是化验单，是病理报告"
  → Agent 重新分类该文件
  → 更新目录结构和模板
```

---

## 4. 功能详细设计

### 4.1 资料接入方式（边界决策）

**设计原则：Agent 是默认入口，脚本是可选加速器，网盘/飞书是用户自行解决的前置步骤。**

#### 三层接入模型（1期）

```
层级      方式                        小白友好度   开发成本
──────────────────────────────────────────────────────────
Layer 1   直接上传给 Agent              ⭐⭐⭐⭐⭐    极低    ← 默认路径
          (图片/PDF/zip压缩包)
          Agent 自动解压 zip，递归识别所有文件

Layer 2   提供本地绝对路径              ⭐⭐⭐       低     ← 进阶/开发者路径
          "我的资料在 ~/Downloads/张三病历/"
          Agent 递归扫描目录下所有支持格式

Layer 3   约定目录（可选）              ⭐⭐⭐⭐      无     ← 长期用户
          ~/patients/{patient_id}/raw/   原始资料放这里
          Agent 检测到 raw/ 有新文件时自动触发增量
```

#### 各接入方式评估与决策

| 方式 | 1期 | 理由 |
|------|-----|------|
| ① 直接上传（图片/PDF/zip混合） | **✅ 纳入（默认）** | 零门槛，小白首选 |
| ② 本地目录绝对路径 | **✅ 纳入** | 一行即可，进阶用户首选 |
| ③ zip 压缩包（混合文件） | **✅ 纳入（合并到①）** | 解压后走 Layer 1 流程 |
| ④ 网盘（夸克/百度） | **⏳ 推迟** | 各家 API 变动频繁，维护成本高；引导用户先下载到本地 |
| ⑤ 飞书文档 | **⏳ 推迟/按需** | 已有 feishu-drive skill 可编排，但非通用场景，不入核心 |
| ⑥ DICOM 影像链接 | **❌ 不纳入1期** | 见下方专项说明 |

**网盘用户引导话术：**
> "请从夸克/百度网盘下载文件到本地，然后告诉我文件夹路径，或者直接发给我就行。"

#### DICOM 影像专项评估

| 问题 | 现状结论 |
|------|---------|
| DICOM 本地解析 | `pydicom` 可将 DICOM 转为 PNG，再走现有 OCR 流程，技术可行 |
| 影像 AI 分析（开源公共 API） | **基本没有**成熟可用的公共 API；MedGamma-3（Med-Gemini系列）仅研究合作访问，未公开 REST API |
| HuggingFace 医学影像模型 | 有模型（如 BiomedCLIP），但不是即用型推理 API，需自建服务 |
| 结论 | **1期不纳入**；1期遇到 DICOM 文件时提示："影像分析暂不支持，可帮您整理影像报告文字内容（CT报告PDF等）" |
| 后期扩展口 | DICOM 分析作为独立 skill 插件，接口预留在 manifest.json，不影响核心流程 |

### 4.2 输入格式支持

| 格式 | 处理方式 | 说明 |
|------|----------|---------|
| **图片** (JPG/PNG/HEIC) | OCR 识别文字 | 化验单照片、处方照片、病历拍照、影像胶片翻拍 |
| **PDF** | 文本提取 + 表格识别 | 出院小结、影像报告、病理报告、门诊病历 |
| **压缩包** (.zip) | 解压后递归处理 | 混合文件打包上传 |
| **文本** (.txt/.md) | 直接读取 | 医生手写转录、电子病历导出、自述病史 |
| **录音** (.mp3/.m4a/.wav) | StepAudio 2.5 ASR 转写 | 医患对话录音、自述录音（0.15元/小时，5分钟音频1秒出结果） |
| **Word** (.docx) | 文档解析 | 电子病历导出格式 |
| **DICOM** (.dcm) | 暂不支持（提示引导） | 1期仅提示，后期插件化扩展 |

> 文件名仅作辅助参考（如 `CT报告_20240315.pdf` 有参考价值），**分类依据是内容本身**，不依赖文件名。

### 4.3 自动分类体系

分类维度按 **内容关键词 + 语义理解** 判定，不依赖文件名：

```
📂 患者病历
│
├── 📋 基本信息
│   ├── 患者主诉
│   ├── 现病史 / 既往史
│   └── 过敏史 / 家族史
│
├── 📊 检验指标
│   ├── 血常规
│   ├── 生化全套（肝功/肾功/血糖/血脂）
│   ├── 肿瘤标志物
│   ├── 凝血功能
│   └── 其他检验
│
├── 🏥 影像检查
│   ├── CT
│   ├── MRI
│   ├── PET-CT
│   ├── 超声
│   ├── X-ray
│   └── 内镜
│
├── 🔬 病理报告
│   ├── 组织病理
│   ├── 细胞学
│   └── 分子病理 / 基因检测
│
├── 💊 用药方案
│   ├── 处方
│   ├── 化疗方案
│   ├── 靶向/免疫治疗
│   └── 用药调整记录
│
├── 📝 诊疗记录
│   ├── 出院小结
│   ├── 门诊记录
│   ├── 手术记录
│   └── 治疗小结
│
└── 📎 其他资料
    ├── 医保/费用相关
    ├── 营养/护理指导
    └── 健康教育资料
```

**分类规则：**
- 优先级：内容关键词 > 文件名 > 文件类型
- 同一文件可能归属多个分类（如化疗方案既是"用药"也属于"诊疗记录"）→ 主分类 + 交叉引用
- 无法明确分类的 → 归入"其他资料"并标注 `[待人工确认]`

### 4.4 病例模板结构

生成的病例档案按以下模板结构输出：

```
============================================================
         患 病 情 档 案
============================================================

【基本信息】
  患者：XXX
  性别：男/女
  年龄：XX岁
  建档日期：YYYY-MM-DD
  最后更新：YYYY-MM-DD
  主要诊断：XXXXXXXXXX

【诊疗时间线】
  ─ 2024-03-15  首诊，肺腺癌确诊（EGFR 19del）
  ─ 2024-03-20  基因检测报告
  ─ 2024-04-01  一线治疗开始：奥希替尼 80mg QD
  ─ 2024-07-10  CT 评估：PR
  ─ 2024-09-05  进展，二线化疗开始
  ─ ...

【检验指标趋势】（关键指标表格 + 异常标注）
  日期        CEA     CA125    ALT    AST    Cr
  2024-03-15  12.3    35.2     28     24     0.85
  2024-07-10   5.6    28.1     32     26     0.91
  ...

【影像检查摘要】（按时间排列）
  2024-03-15 胸腹部CT：右肺上叶结节 2.1cm，考虑周围型肺癌...
  2024-07-10 胸腹部CT：右肺上叶结节缩小至 1.2cm，评估PR...
  ...

【用药方案】
  当前用药：
    - 奥希替尼 80mg QD（2024-04-01 起始）
  历史用药：
    - ...

【病理报告摘要】
  2024-03-20 组织病理：右肺上叶浸润性腺癌...
  2024-03-25 基因检测：EGFR 19del，TP53 突变...

【完整资料目录】（带页码/链接索引）
  1. 出院小结（2024-03-18） ............... 附件 P.1
  2. 基因检测报告（2024-03-25） ............ 附件 P.3
  3. 胸部CT报告（2024-03-15） .............. 附件 P.5
  ...

【信息缺口提示】
  ⚠️ 缺少 2024-04-01 至今的血常规数据
  ⚠️ 缺少最近一次化疗方案的详细记录
  💡 建议补充：过敏史信息未找到

============================================================
⚠️ 本档案仅为医疗资料整理，不构成任何诊断或治疗建议。
   如有疑问请联系主治医师。
============================================================
```

### 4.5 输出格式

| 格式 | 适用场景 | 说明 |
|------|----------|------|
| **Markdown (.md)** | 知识库归档、版本控制 | 结构化文本，易于阅读和编辑 |
| **HTML (.html)** | 在线查看、分享 | 自带样式，可直接浏览器打开 |
| **PDF (.pdf)** | 打印、带去医院复诊 | 排版固定，适合正式文档 |
| **Word (.docx)** | 医院系统导入、进一步编辑 | 兼容性好，方便医生补充 |

**模板可定制**：用户可提供自己的模板格式，Agent 按照用户模板填充。

---

## 5. 增量更新机制

### 5.1 会话内更新

在同一会话中，用户随时可以追加新文件：

```
用户: "这是今天新出的血常规 [上传图片]"
Agent: 
  ✅ 识别为：血常规检验报告
  ✅ 归类到：检验指标 > 血常规
  ✅ 更新时间线
  ✅ 重新生成病例档案（Markdown 格式）
  ↓ 预览更新后的血常规趋势表 ...
```

### 5.2 跨会话持久化

- 每位患者的数据存储在独立的目录中：`patients/{patient_id}/`
- 内部维护一个 `manifest.json`，记录已处理文件的索引、分类、时间线
- 新会话加载已有 manifest，基于增量更新
- 文件使用 SHA256 哈希去重，避免重复处理

### 5.3 状态文件结构

```
patients/{patient_id}/
├── manifest.json           # 文件索引与分类记录
├── sources/                 # 原始文件存储
│   ├── img/
│   ├── pdf/
│   ├── txt/
│   └── audio/
├── extracted/               # 提取后的文本
│   ├── {hash}.txt
│   └── transcriptions/
├── output/                  # 生成的病例档案
│   ├── case-report.md
│   ├── case-report.html
│   ├── case-report.pdf
│   └── case-report.docx
└── timeline.json            # 时间线数据
```

**manifest.json 示例：**

```json
{
  "patient_id": "P20240315",
  "created_at": "2024-03-15T10:00:00Z",
  "updated_at": "2024-09-10T14:30:00Z",
  "demographics": {
    "name": "张XX",
    "gender": "男",
    "age": 62,
    "primary_diagnosis": "右肺上叶浸润性腺癌"
  },
  "files": [
    {
      "hash": "a1b2c3d4...",
      "original_name": "IMG_20240315.jpg",
      "source_path": "sources/img/IMG_20240315.jpg",
      "extracted_path": "extracted/a1b2c3d4.txt",
      "category": "lab_results.blood_routine",
      "date_detected": "2024-03-15",
      "title": "血常规检验报告",
      "confidence": 0.95,
      "needs_review": false
    }
  ],
  "categories_summary": {
    "lab_results": 12,
    "imaging": 5,
    "pathology": 2,
    "medication": 3,
    "clinical_records": 4,
    "other": 1
  }
}
```

---

## 6. 技术架构

### 6.1 整体架构

```
┌─────────────────────────────────────────────┐
│              ZCode Agent (Skill)             │
│  SKILL.md 定义工作流、分类规则、安全边界      │
└──────────────────────┬──────────────────────┘
                       │ 编排调用
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
┌──────────────┐ ┌──────────┐ ┌──────────────┐
│ 文件解析层    │ │ 分类引擎  │ │ 输出生成器   │
│              │ │          │ │              │
│ - OCR (图片) │ │ LLM 语义  │ │ - Markdown  │
│ - PDF解析    │ │ 分类      │ │ - HTML      │
│ - ASR (录音) │ │ + 规则    │ │ - PDF       │
│ - DOCX解析   │ │ 辅助      │ │ - DOCX      │
└──────────────┘ └──────────┘ └──────────────┘
```

### 6.2 OCR 技术栈：双引擎策略

采用 **SiliconFlow DeepSeek-OCR + MinerU** 双引擎，根据文件类型和复杂度自动路由：

```
                    ┌─────────────────────┐
                    │    文件输入           │
                    └────────┬────────────┘
                             │
                    ┌────────▼────────────┐
                    │   文件类型判断        │
                    └────────┬────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌──────────────┐
        │  单张图片  │  │  PDF文件  │  │ 复杂PDF/扫描件│
        │  简单照片  │  │  文字型   │  │ 含图表/表格   │
        └─────┬────┘  └─────┬────┘  └──────┬───────┘
              │              │               │
              ▼              ▼               ▼
        ┌──────────┐  ┌──────────┐   ┌──────────────┐
        │DeepSeek  │  │DeepSeek  │   │   MinerU     │
        │  OCR     │  │  OCR     │   │ (深度解析)    │
        │(SF API)  │  │(SF API)  │   │(API/MCP)     │
        └──────────┘  └──────────┘   └──────────────┘
              │              │               │
              └──────────────┼───────────────┘
                             ▼
                    ┌─────────────────────┐
                    │   结构化文本输出      │
                    └─────────────────────┘
```

#### 引擎 A：SiliconFlow DeepSeek-OCR（主力引擎）

| 属性 | 说明 |
|------|------|
| **API 端点** | `https://api.siliconflow.cn/v1/images/ocr`（OpenAI 兼容格式） |
| **模型** | `deepseek-ocr` |
| **调用方式** | HTTP POST（image_url / base64） |
| **优势** | 成本极低、速度快、支持中英文混排、化验单识别效果好 |
| **适用场景** | 手机拍照的化验单、处方单、病历卡照片、文字型 PDF 逐页提取 |
| **限制** | 对复杂排版（表格、多栏、手写体）识别率一般 |

```python
# 调用示例（复用现有 SiliconFlow API Key）
import base64, requests

def ocr_via_siliconflow(image_path: str, api_key: str) -> str:
    """调用 SiliconFlow DeepSeek-OCR 识别图片文字"""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    
    resp = requests.post(
        "https://api.siliconflow.cn/v1/images/ocr",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-ocr",
            "image_url": f"data:image/jpeg;base64,{b64}",
        },
        timeout=30,
    )
    return resp.json()["choices"][0]["message"]["content"]
```

#### 引擎 B：MinerU（深度解析引擎）

| 属性 | 说明 |
|------|------|
| **调用方式** | MinerU API（HTTP）或 MinerU MCP Skill（Agent 直接调用） |
| **优势** | 深度 PDF 解析：表格识别、版面还原、公式提取、多栏排版、图片+文字混合 |
| **适用场景** | 复杂 PDF（出院小结、影像报告含图）、扫描件 PDF、含表格的检验报告、学术论文 |
| **限制** | 调用成本较高、速度较慢（复杂文档可能 10-30s） |

```python
# 方式 1：直接 API 调用
def extract_via_mineru_api(pdf_path: str, api_url: str, api_key: str) -> dict:
    """调用 MinerU API 深度解析 PDF"""
    with open(pdf_path, "rb") as f:
        resp = requests.post(
            f"{api_url}/extract",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": f},
            timeout=120,
        )
    return resp.json()  # 返回结构化文本 + 表格 + 图片描述

# 方式 2：通过 MCP Skill 调用（Agent 编排时使用）
# 调用现有 MinerU Document Extractor Skill：
#   MCP 工具名：extract_document
#   参数：file_path
#   返回：结构化 Markdown（含表格、公式、图片描述）
```

#### 路由策略

```python
def route_ocr(file_path: str, file_type: str) -> str:
    """自动选择 OCR 引擎
    
    策略：
    1. 图片文件 (.jpg/.png/.heic) → DeepSeek-OCR（SF）
    2. PDF 且页数 ≤ 5 且为文字型 → DeepSeek-OCR 逐页提取
    3. PDF 且含表格/图片/扫描件 → MinerU 深度解析
    4. PDF 失败兜底 → MinerU 重试
    """
    if file_type in ("jpg", "png", "heic"):
        return "siliconflow_ocr"
    elif file_type == "pdf":
        pdf_info = detect_pdf_type(file_path)  # 检测是否为扫描件/含表格
        if pdf_info["is_text_based"] and pdf_info["page_count"] <= 5:
            return "siliconflow_ocr"  # 简单 PDF 用低成本引擎
        else:
            return "mineru"            # 复杂 PDF 用深度解析
    return "siliconflow_ocr"
```

#### 成本估算

| 引擎 | 单次调用 | 估算日处理量（100张图片+20份PDF） |
|------|----------|-------------------------------|
| DeepSeek-OCR | ~¥0.001/张 | ~¥0.10 |
| MinerU | ~¥0.05-0.2/份（取决于复杂度） | ~¥1-4 |
| **合计** | | **~¥1-5/天** |

### 6.3 文件解析层（完整）

| 输入格式 | 解析方案 | 引擎选择 |
|----------|----------|----------|
| 图片 (JPG/PNG/HEIC) | SiliconFlow DeepSeek-OCR | 引擎 A |
| 文字型 PDF（≤5页） | SiliconFlow DeepSeek-OCR 逐页 | 引擎 A |
| 复杂 PDF（含表格/图表/扫描件） | MinerU 深度解析 | 引擎 B |
| PDF 解析失败兜底 | MinerU 重试 | 引擎 B |
| 录音 (MP3/M4A/WAV) | StepFun ASR（见 6.4） | 引擎 C/D |
| DOCX | python-docx | 标准解析 |
| TXT/MD | 直接读取 | — |

### 6.4 ASR 引擎策略：双路径

录音（医患对话、自述病史）全部走 StepFun 云端 ASR，**不依赖本地 GPU / Whisper**，零额外安装成本。**默认全部走引擎 C（SSE，StepAudio 2.5）**；仅当满足以下任一条件时，才切到引擎 D（异步）：需词级字幕对齐 / 双声道分离 / 本地超长文件已有公网 URL。

| 路径 | API | 模型 | 提交方式 | 适用场景 | 定价 |
|------|-----|------|---------|---------|------|
| **引擎 C：SSE 流式（默认主力）** | `POST /v1/audio/asr/sse` | `stepaudio-2.5-asr` | 本地文件 base64 直传，SSE 流式返回 | **默认全部**：覆盖绝大多数患者录音（本地文件，短/中时长，要求快出结果） | 0.15 元/小时 |
| **引擎 D：异步文件识别（特殊场景，1期接口预留）** | `POST /v1/audio/asr/file/submit` + `/file/query` 轮询 | `step-asr-1.1` | 公网 URL 提交，轮询取结果 | 仅当：需词级字幕对齐 OR 双声道分离 OR 本地超长文件已有公网 URL（<100MB） | 按官网计费 |

#### 路由策略

```python
def route_asr(audio_path: str, duration_sec: float, has_public_url: bool,
              need_word_level_timestamps: bool = False,
              need_channel_split: bool = False) -> str:
    """自动选择 ASR 路径

    默认全部 → 引擎 C（SSE，StepAudio 2.5，5 分钟音频 1 秒出，0.15 元/小时）
    仅当以下任一条件满足时 → 引擎 D（异步，接口预留，1 期不实际调用）：
      1. 需要词级时间戳做字幕/逐句对齐（need_word_level_timestamps）
      2. 双声道录音需拆分两人对话（need_channel_split）
      3. 本地超长文件已有公网 URL（has_public_url and duration_sec > 30min）
    """
    if need_word_level_timestamps or need_channel_split:
        return "async_file"      # 引擎 D（接口预留）
    if has_public_url and duration_sec > 30 * 60:
        return "async_file"      # 引擎 D（接口预留）
    return "sse"                 # 引擎 C（默认，1 期主力）
```

#### 引擎 C：StepAudio 2.5 ASR（SSE，默认主力）

- 端点：`https://api.stepfun.com/v1/audio/asr/sse`
- 模型字符串：`stepaudio-2.5-asr`
- 提交：一次性把音频 base64 放进 `audio.data`，支持 PCM/OGG/MP3/WAV，中英文识别
- 返回：SSE 流，`transcript.text.delta` 增量 → `transcript.text.done` 结束
- 速度：RTF ≈ 0.0053，5 分钟音频 1 秒内出完整结果
- 适配本项目：患者录音多为短/中时长，本地文件可直接 base64 上传，无需公网托管
- 时间戳：支持 `enable_timestamp`（句子级，非词级），分类和时间线提取已足够

#### 引擎 D：异步文件识别（接口预留，1 期不实际调用）

- 提交：`POST /v1/audio/asr/file/submit`，`audio.url` 必须公网可达（<100MB）
- 轮询：`POST /v1/audio/asr/file/query`，建议 1–3s 一次，返回 `RUNNING` 或最终 `result`
- 模型：`step-asr-1.1`
- `show_utterances=true` 可拿到**词级**时间戳（适合做字幕/逐字对齐）
- `enable_channel_split=true` 可拆分双声道为两个识别结果（适合两人对话分离）
- 限制：依赖公网 URL；若用户只有本地大文件，需先上传到对象存储（推迟到 V2）

> **当前实现优先级**：1 期**仅实现引擎 C**（SSE，覆盖 95%+ 患者录音场景）；引擎 D 作为接口预留，待长音频/词级字幕/双声道分离等极端场景出现再接入，不影响主流程。

### 6.5 分类引擎

**两层分类策略：**

```
第一层：规则快速分类（零成本）
  → 正则匹配关键词（"血常规"、"CT"、"出院小结"、"化疗方案"等）
  → 覆盖 80% 的常见报告类型

第二层：LLM 语义分类（成本极低）
  → 对第一层无法匹配的文件，调用 LLM 判断类别
  → Prompt: "以下是一份医疗报告的文本片段，请判断它属于哪个类别..."
  → 使用低成本模型（qwen3-flash / glm-4-flash）
```

### 6.6 模板引擎

- 内置默认模板（上述 4.4 节模板）
- 支持 Jinja2 模板语法，用户可自定义
- 输出格式转换：
  - MD → HTML：markdown-it / Python markdown
  - MD → PDF：weasyprint / markdown2pdf
  - MD → DOCX：pandoc（推荐）或 python-docx

---

## 7. Skill 定义（SKILL.md 概要）

```yaml
---
name: patient-record-organizer
description: >
  智能病案整理助手：将零散的医疗资料（照片、PDF、文本、录音）
  自动分类归档，生成结构化病例档案。
  当用户提到"整理病历"、"整理检查报告"、"归类病情资料"、"生成病例档案"、
  "病情整理"、"病例模板"、"我的检查报告"、"出院小结整理"时触发。
---
```

### Agent 行为指令（SKILL.md 核心内容）

```markdown
# Patient Record Organizer

## 工作流程

### 第一步：接收与扫描
- 接收用户上传的文件（图片/PDF/文本/录音/Word）
- 列出文件清单：文件名、大小、类型
- 检查是否有已有 manifest（增量模式 vs 全新建档）

### 第二步：内容提取
- 图片 → OCR 识别
- PDF → 文本+表格提取
- 录音 → 语音转写
- 文本/Word → 直接读取
- 每个文件提取后生成纯文本缓存

### 第三步：自动分类
- 先用规则关键词快速分类（"血常规"→检验指标、"CT"→影像检查...）
- 规则无法匹配的 → LLM 语义分类
- 展示分类结果，等待用户确认/调整

### 第四步：时间线构建
- 从内容中提取日期（报告日期、就诊日期）
- 按日期排序构建时间线
- 同日期的按分类分组

### 第五步：填充模板
- 提取关键信息填入病例模板
- 生成检验指标趋势表
- 生成信息缺口提示

### 第六步：输出
- 询问用户输出格式（MD/HTML/PDF/DOCX）
- 生成病例档案文件
- 同时更新 manifest.json

## 安全边界（必须遵守）
- 本工具仅整理资料，不提供诊断
- 不对检验结果做临床解读（只标注异常值）
- 所有输出必须附带免责声明
- 如遇紧急信息（如危急值），提示用户立即就医

## 交互原则
- 每步操作后展示结果，等待确认
- 用户可随时调整分类
- 用户可指定自定义模板
- 增量更新时不覆盖用户已调整的内容
```

---

## 8. 用户交互示例

### 场景 1：首次建档

```
用户: 我妈妈肺腺癌，这两周积攒了一堆检查报告和录音，
     帮我整理成一份病历档案。

Agent: 好的，我来帮您整理。请把所有资料发给我。

用户: [上传 15 张照片 + 3 个 PDF + 1 段录音]

Agent: 收到 19 个文件，正在处理...
      
      ✅ 文件扫描完成：
         图片 15 张（化验单 8、处方 2、病历卡 1、其他 4）
         PDF 3 份（出院小结 1、CT报告 1、基因检测 1）
         录音 1 段（约 8 分钟）
      
      正在提取内容...完成

      📋 分类结果：
      ├── 检验指标 (8) ← 血常规×3、生化×2、肿瘤标志物×2、凝血×1
      ├── 影像检查 (1) ← 胸部CT×1
      ├── 病理报告 (1) ← 基因检测×1
      ├── 用药方案 (2) ← 处方×2
      ├── 诊疗记录 (1) ← 出院小结×1
      ├── 基本信息提取 (1) ← 从病历卡
      └── ⚠️ 待确认 (4) ← [查看详情]
      
      时间线：2024-03-15 ~ 2024-09-10
      
      请确认分类是否正确，或有需要调整的地方？

用户: 第4张照片不是化验单，是病理报告的拍照

Agent: 已重新分类：第4张图片 → 病理报告
      
      分类更新后：
      ├── 检验指标 (7)
      ├── 影像检查 (1)
      ├── 病理报告 (2)  ← ✅ 已更新
      ├── 用药方案 (2)
      └── ...
      
      需要我生成病例档案吗？可选格式：Markdown / HTML / PDF / Word

用户: 都生成，方便我打印和线上分享

Agent: 正在生成...
      ✅ case-report.md
      ✅ case-report.html
      ✅ case-report.pdf
      ✅ case-report.docx
      
      📎 病例档案已生成
      
      ⚠️ 信息缺口提示：
         - 缺少过敏史信息
         - 2024-06-01 至 2024-07-10 期间无检验记录
         - 建议补充：最近一次化疗方案详细记录
      
      后续有新资料随时发给我，我会自动更新。
```

### 场景 2：增量更新

```
用户: 今天新做了一个增强CT，结果出来了 [上传图片]

Agent: ✅ 识别为：增强CT检查报告
      ✅ 日期：2024-10-15
      ✅ 归类到：影像检查 > CT
      ✅ 时间线已更新
      
      📊 关键发现（仅提取内容，不作解读）：
      "右肺上叶结节 1.8cm，较前（1.2cm）增大..."
      
      需要重新生成病例档案吗？
```

---

## 9. 里程碑规划

### 1期（MVP）能力边界

```
✅ 纳入
├── 资料接入：直接上传 / zip压缩包 / 本地绝对路径
├── 格式支持：图片 / PDF / Word / TXT / MD / 录音(MP3/M4A/WAV)
├── OCR：DeepSeek-OCR（SiliconFlow）+ MinerU（复杂PDF）
├── ASR：StepAudio 2.5（StepFun，云端SSE，0.15元/小时）
├── 分类：规则层（关键词） + LLM 语义兜底，共11类
├── 时间线：自动从内容提取日期并构建
├── 病例档案：Markdown + HTML 输出
├── 增量更新：manifest.json SHA256 去重
├── 用户调整：分类错误时交互式修正
└── 安全边界：不诊断，危急值强提醒

⏳ 推迟（插件化，不影响核心）
├── PDF 输出（weasyprint）
├── DOCX 输出（pandoc / python-docx）
├── 肿瘤标志物趋势图可视化
├── 网盘对接（夸克/百度 API）
├── 飞书文档拉取（feishu-drive skill 编排）
└── HADS / 营养量表联动（参考 report-genie 设计）

❌ 不纳入（搁置）
└── DICOM 影像 AI 分析（无成熟公共 API，后期独立插件）
```

### skill-report-genie 参考结论

> 来源：`/Users/qinxiaoqiang/Downloads/skill-report-genie`，前期复杂版病情整理助手

| 评估维度 | 结论 |
|---------|------|
| **报告章节结构** | ✅ 参考：基本信息→病理→标志物趋势→基因→诊疗经过→建议→附录 |
| **分类目录结构** | ✅ 参考：imaging/lab_reports/medical_records/nutrition/psychology/complications 多维度 |
| **HADS/营养量表接入约定** | ✅ 参考：JSON 结构标准化，后期推迟纳入 |
| **EdgeOne 发布 HTML** | ✅ 参考思路，后期推迟纳入 |
| **整体架构** | ❌ 不直接复用：三套 API 依赖（StepFun/SiliconFlow/Google）+ retry_queue.db + 自优化节点，太重，与「好用不重」冲突 |
| **行动** | 从报告模板和目录结构中提取精华，更新到 `references/case-report-template.md` |

### V2.0（远期）

| 功能 | 说明 |
|------|------|
| 多患者管理 | 患者目录 + 搜索 |
| 脱敏处理 | 自动去除姓名/身份证等 PHI |
| 多语言 | 英文病例档案 |
| 数据导出 | CSV 格式的检验数据 |
| MCP 子工具暴露 | 供其他 Skill/Agent 调用分类能力 |
| DICOM 插件 | 接入后期开放的影像 AI API |

---

## 10. 风险与约束

| 风险 | 影响 | 缓解 |
|------|------|------|
| OCR 识别错误 | 分类不准、数据错误 | 显示提取结果供用户确认 |
| 医疗隐私泄露 | PHI 安全问题 | manifest 本地存储，输出可脱敏 |
| 用户过度依赖 | 把档案当诊断看 | 强制免责声明，红旗提示 |
| 照片质量差 | OCR 无法识别 | 提示用户重拍，标注失败文件 |
| 分类边界模糊 | 同一文件多分类 | 支持主分类+交叉引用 |

---

## 11. 依赖与资源

### 开发依赖

```
# Python
PyMuPDF>=1.23.0          # PDF 类型检测（判断文字型 vs 扫描件）
python-docx>=1.0.0       # Word 文档解析
Jinja2>=3.1.0             # 模板引擎
markdown>=3.5.0           # Markdown → HTML
requests>=2.31.0          # OCR / ASR / LLM HTTP 调用
pytest>=7.4.0             # 测试
```

> ASR / OCR / PDF 解析全部走云端 API，**不依赖本地 GPU，无需安装 Whisper**。

### 运行时 API

| 用途 | 服务 | API Key 环境变量 | 说明 |
|------|------|-----------------|------|
| 图片/简单 PDF OCR | SiliconFlow DeepSeek-OCR | `SILICONFLOW_API_KEY` | 主力 OCR 引擎，低成本 |
| 复杂 PDF 深度解析 | MinerU API / MinerU MCP Skill | `MINERU_API_KEY` | 表格/图表/扫描件 PDF |
| 录音转写（默认 SSE） | StepFun StepAudio 2.5 ASR | `STEP_API_KEY` | 0.15元/小时，5分钟音频1秒出 |
| 录音转写（长音频备选） | StepFun 异步文件识别 `step-asr-1.1` | `STEP_API_KEY` | 需公网 URL，支持时间戳 |
| 语义分类 + 信息提取 | DashScope qwen3-flash | `DASHSCOPE_API_KEY` | 两层分类 LLM 兜底 |

> **注意**：OCR / PDF 解析 / ASR 全部云端 API，不依赖本地 GPU。
> 整个流程 LLM 调用极少（仅分类和信息提取），核心调用在 OCR 与 ASR 阶段。
> 日均处理 100 张图片 + 20 份 PDF + 几段录音的 API 成本约 ¥2–6。

### API Key 配置（.env）

```bash
# 必需：SiliconFlow（DeepSeek-OCR 主力引擎 + 可选 LLM fallback）
SILICONFLOW_API_KEY=sk-xxxxxxxx

# 必需：MinerU（复杂 PDF 深度解析）
MINERU_API_KEY=your-mineru-key
# MINERU_API_URL=https://your-mineru-instance.com  # 自建实例可覆盖

# 必需：StepFun（录音 ASR：StepAudio 2.5 SSE 主力 + step-asr-1.1 异步备选）
STEP_API_KEY=sk-xxxxxxxx

# 推荐：DashScope（语义分类 LLM，可选作 Enricher）
DASHSCOPE_API_KEY=sk-xxxxxxxx

# 可选：其他 LLM 厂商 fallback（参考 fastgpt-content-processor 模式）
# ZHIPUAI_API_KEY=your-zhipuai-key
```

---

## 附录 A：分类关键词词库（规则层）

```yaml
lab_results:
  - 血常规
  - 白细胞
  - 血红蛋白
  - 血小板
  - 生化
  - 肝功能
  - ALT
  - AST
  - 肾功能
  - 肌酐
  - 尿素氮
  - 血糖
  - 糖化血红蛋白
  - 电解质
  - 肿瘤标志物
  - CEA
  - CA125
  - CA199
  - AFP
  - PSA
  - 凝血
  - INR
  - D-二聚体

imaging:
  - CT
  - MRI
  - 核磁共振
  - 超声
  - B超
  - 彩超
  - X线
  - X-ray
  - PET-CT
  - 骨扫描
  - 内镜
  - 胃镜
  - 肠镜
  - 支气管镜
  - 造影
  - 增强
  - 平扫

pathology:
  - 病理
  - 活检
  - 免疫组化
  - 基因检测
  - 突变
  - EGFR
  - ALK
  - ROS1
  - KRAS
  - HER2
  - PD-L1
  - TMB

medication:
  - 处方
  - 用药
  - 化疗方案
  - 靶向
  - 免疫治疗
  - 奥希替尼
  - 吉非替尼
  - 信迪利单抗
  - 帕博利珠单抗
  - 贝伐珠单抗

clinical_records:
  - 出院小结
  - 出院记录
  - 门诊
  - 住院
  - 手术记录
  - 术中
  - 术后
  - 治疗小结
  - 化疗小结
  - 放疗小结

basic_info:
  - 主诉
  - 现病史
  - 既往史
  - 过敏史
  - 家族史
  - 体格检查
```

---

## 附录 B：免责声明模板

```
⚠️ 免责声明

本病例档案由 AI 辅助工具自动整理生成，仅用于医疗资料的分类归档和结构化呈现，
不代表任何医学诊断或治疗建议。

档案中的所有数据均来源于用户提供的原始资料，整理过程中可能出现识别错误或遗漏，
请务必与原始资料核对。

如有任何健康问题，请咨询专业医疗人员。
紧急情况请拨打 120 或前往最近急诊。
```

---

## 附录 C：开发任务清单（1期 MVP）

> **任务粒度原则**：每个任务 2–5 分钟可完成，明确文件归属、验收命令、禁止修改范围。
> **执行顺序**：T1 → T2 → T3 → T4 → T8 → [T5 ‖ T6] → T7 → 集成验收。前 4 个任务有依赖；T8（ASR）与 T4 之后即可并行；T5/T6 可并行。
> **TDD 要求**：每个脚本任务先写失败测试（`tests/test_<name>.py`），看到 RED，再实现到 GREEN。

### 阶段 0：环境与约定

| ID | 任务 | 产出文件 | 验收方式 |
|----|------|---------|---------|
| T0 | 初始化项目骨架与依赖 | `requirements.txt`、`.env.example`、`tests/` 目录 | `pip install -r requirements.txt` 成功；`pytest tests/ -q` 可运行（即使空） |

**`requirements.txt` 必装项**：`PyMuPDF`、`python-docx`、`Jinja2`、`markdown`、`requests`、`pytest`。
**`.env.example`**：`SILICONFLOW_API_KEY=`、`MINERU_API_KEY=`、`DASHSCOPE_API_KEY=`。

---

### 阶段 1：资料接入层（T1–T2）

| ID | 任务 | 产出文件 | 验收方式 |
|----|------|---------|---------|
| T1 | **资料收集器**：支持三种接入方式（直接上传文件列表 / 本地目录绝对路径递归扫描 / zip 解压后展开）。统一返回 `(path, type)` 列表。忽略不支持的格式（如 `.dcm` → 提示语写入日志而非崩溃）。 | `scripts/ingest.py` + `tests/test_ingest.py` | `pytest tests/test_ingest.py -v` 全绿；测试用例覆盖：① 混合格式目录扫描、② zip 解压、③ 遇到 `.dcm` 不报错只提示、④ 空目录返回空列表 |
| T2 | **manifest 初始化与增量判定**：给定 patient_id，检查 `~/patients/{id}/manifest.json`；不存在则全新建档（询问基本信息），存在则进入增量模式。计算每个文件 SHA256，跳过已处理文件。 | `scripts/manifest.py` + `tests/test_manifest.py` | `pytest tests/test_manifest.py -v` 全绿；测试覆盖：① 新建 manifest 结构正确、② 相同文件哈希跳过、③ `--update` 写回字段完整 |

**验收命令（阶段1）**：
```bash
python -c "from scripts.ingest import collect; print(collect('tests/fixtures/sample_dir'))"
python scripts/manifest.py --patient P001 --init --name '张三' --age 62
```

---

### 阶段 2：内容提取层（T3）

| ID | 任务 | 产出文件 | 验收方式 |
|----|------|---------|---------|
| T3 | **OCR 双引擎路由**：①图片→DeepSeek-OCR（SF）；②文字型 PDF ≤5页→逐页转图走 DeepSeek-OCR；③复杂/扫描 PDF→MinerU。用 PyMuPDF 判定文字层。OCR 失败时标记 `[OCR失败-需人工确认]` 不中断。提取结果缓存到 `extracted/{hash}.txt`。 | `scripts/ocr_siliconflow.py`、`scripts/extract_mineru.py`、`scripts/route_ocr.py` + `tests/test_route_ocr.py` | `pytest tests/test_route_ocr.py -v` 全绿；测试覆盖：① 图片路由到 SF、② 纯文字小PDF路由到 SF、③ 扫描件路由到 MinerU、④ 路由函数不实际发请求（mock） |

**验收命令（阶段2，需真实 API Key）**：
```bash
# 准备 1 张化验单照片 + 1 份复杂 PDF
python scripts/route_ocr.py tests/fixtures/blood_test.jpg
python scripts/route_ocr.py tests/fixtures/complex_report.pdf
# 人工检查：输出 txt 内容可读、化验单数值正确
```

---

### 阶段 3：分类与时间线（T4）

| ID | 任务 | 产出文件 | 验收方式 |
|----|------|---------|---------|
| T4 | **两层分类 + 日期提取**：①规则层用 `references/classification-rules.md` 关键词词库匹配；②未命中取前 500 字发 LLM（qwen3-flash / glm-4-flash）返回类别名；③正则提取日期（兼容 `2024-03-15`/`2024年3月15日`/`24/03/15`）。分类结果回写 manifest，写入 `timeline.json`。 | `scripts/classify.py` + `tests/test_classify.py` | `pytest tests/test_classify.py -v` 全绿；测试覆盖：① "血常规"命中 lab_results、② "CT报告"命中 imaging、③ LLM 兜底分支（mock 返回）、④ 三种日期格式都能提取、⑤ 多分类时主分类正确 |

**验收命令（阶段3）**：
```bash
python scripts/classify.py tests/fixtures/extracted_sample.txt
# 输出：category=lab_results.blood_routine, date=2024-03-15, confidence=0.95
```

---

### 阶段 3.5：录音转写（T8，可与 T4 之后并行）

| ID | 任务 | 产出文件 | 验收方式 |
|----|------|---------|---------|
| T8 | **ASR 引擎 C（StepAudio 2.5 SSE，1 期主力）**：本地录音 base64 → `POST /v1/audio/asr/sse` → SSE 流式解析 `transcript.text.delta` 增量拼接，`done` 结束。转写结果缓存到 `extracted/transcriptions/{hash}.txt`，走与 OCR 相同的分类/时间线流程。转写失败标记 `[ASR失败-需人工确认]` 不中断。引擎 D（异步 `step-asr-1.1`）仅做接口 stub 预留，1 期不实际调用。 | `scripts/asr_stepfun.py` + `tests/test_asr.py` | `pytest tests/test_asr.py -v` 全绿；测试覆盖：① 短/中录音默认路由到 SSE、② SSE 增量文本正确拼接、③ 引擎 D 路由条件触发时返回 `"async_file"`（stub）、④ 失败兜底不抛异常、⑤ base64 体积过大时提前报错 |

**验收命令（阶段 3.5，需真实 STEP_API_KEY）**：
```bash
# 准备 1 段短录音（< 5 分钟）
python scripts/asr_stepfun.py tests/fixtures/voice_memo.mp3
# 人工检查：输出 txt 内容可读、中文识别准确
```

> **依赖说明**：ASR 与 OCR 共享提取层缓存（`extracted/{hash}.txt`）和后续分类/时间线流程，所以 T8 在 T4 完成后即可并入主流程，不需要等 T5/T6。

---

### 阶段 4：报告生成（T5–T6，可并行）

| ID | 任务 | 产出文件 | 验收方式 |
|----|------|---------|---------|
| T5 | **报告渲染器（Markdown + HTML）**：读取 manifest + timeline.json，按 `references/case-report-template.md` 结构填充（含检验趋势表、信息缺口提示、免责声明）。Markdown 用 Jinja2；HTML 用 `markdown` 库转换 + 内嵌 CSS。输出到 `output/`。 | `scripts/render_report.py` + `tests/test_render.py` | `pytest tests/test_render.py -v` 全绿；测试覆盖：① MD 模板字段全部填充、② 危急值触发免责声明、③ 缺口提示正确识别缺失分类、④ HTML 文件可在浏览器打开 |
| T6 | **报告模板精修**：参考 `skill-report-genie` 的章节结构（病理/基因/诊疗经过）优化 `case-report-template.md`，但保持轻量（不引入 StepFun 等额外依赖）。 | `references/case-report-template.md` | 人工 review：模板章节完整、与 1期分类体系一一对应、不含未实现字段 |

**验收命令（阶段4）**：
```bash
python scripts/render_report.py --patient P001 --format md
python scripts/render_report.py --patient P001 --format html
# 人工检查 output/case-report.md 与 .html 内容完整、格式正确
```

---

### 阶段 5：SKILL.md 编排（T7）

| ID | 任务 | 产出文件 | 验收方式 |
|----|------|---------|---------|
| T7 | **SKILL.md 工作流串联**：把 T1–T6 的脚本调用编排进 SKILL.md 的 6 步工作流，明确每步"展示结果→等用户确认"的交互点。加入安全边界、危急值清单、网盘引导话术、DICOM 提示语。 | `SKILL.md` | 人工走查：① 6 步流程闭环、② 每步有用户确认点、③ 安全边界完整、④ 触发词覆盖"整理病历/整理检查报告/新报告出来了"等 |

---

### 阶段 6：集成验收（端到端）

| 场景 | 操作 | 通过标准 |
|------|------|---------|
| **E1 首次建档（小白路径）** | 直接上传 5 张化验单照片 + 1 份 PDF + 1 段录音 | 文件清单正确列出 → OCR/ASR 提取成功 → 分类结果展示且可调整 → 生成 MD+HTML → 含免责声明 |
| **E2 首次建档（开发者路径）** | 提供 `~/Downloads/test_cases/` 绝对路径 | 递归扫描 → 同 E1 后续流程 |
| **E3 zip 压缩包** | 上传一个含混合文件的 zip | 自动解压 → 文件清单正确 → 同 E1 |
| **E4 增量更新** | E1 完成后追加 1 张新化验单 | SHA256 去重 → 仅处理新文件 → 时间线刷新 → 档案重新生成 |
| **E5 分类修正** | 告诉 Agent"第3张是病理报告不是化验单" | 立即重分类 → manifest 更新 → 档案刷新 |
| **E6 OCR 失败容错** | 上传 1 张模糊照片 | 标记 `[OCR失败-需人工确认]` → 不中断 → 其余文件正常处理 |
| **E7 危急值提醒** | 上传含血钾 7.0 的化验单 | 档案中标注异常 + 弹出"请立即联系医生"强提醒 |
| **E8 DICOM 提示** | 上传 `.dcm` 文件 | 不崩溃 → 提示"影像分析暂不支持，可整理影像报告文字" |
| **E9 网盘引导** | 用户说"资料在夸克网盘" | 回复引导话术，不尝试对接 API |
| **E10 录音转写** | 上传 1 段约 3 分钟医患对话录音 | 路由到 SSE → 转写文本可读 → 进入分类（归入"诊疗记录"）→ 写入 timeline |

---

### 任务依赖图

```
T0 ──┬──> T1 ──> T2 ──> T3 ──> T4 ──┬──> T7 ──> 集成验收(E1-E10)
     │              │               │
     │              └──> T8(ASR) ───┤   (T8 在 T4 后并入主流程)
     │                              │
     └──────────────────────────────┴──> T5 ──┐
                                              ├──> (T5/T6 并行后回 T7)
                                       T6 ────┘
```

---

### 成本与风险检查清单（交付前）

- [ ] `.env.example` 不含真实 Key
- [ ] `manifest.json` 只存本地，不上传任何外部服务
- [ ] 所有输出文件含免责声明
- [ ] 危急值清单覆盖（血钾、血红蛋白、血小板等核心项）
- [ ] OCR/ASR/LLM 调用失败有兜底，不中断主流程
- [ ] ASR 默认走 SSE（引擎C）；异步路径（引擎D）接口预留但不实际调用公网托管
- [ ] 录音文件 base64 体积过大时有超限保护（SSE 体积上限参考官方）
- [ ] 日志不记录原始医疗文本/录音原文（只记文件ID、类别、错误类型）
- [ ] 端到端 10 个场景（E1–E10）全部通过
