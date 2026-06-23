# PRD v2.0：MapReduce 三层架构升级

> **状态**：重大设计更新（Major Architecture Update）
> **版本**：v1.0（正则/规则） → v2.0（MapReduce + LLM）
> **日期**：2026-06-23
> **作者**：patient-record-organizer team
> **背景**：v1.0 实现完成后，真实数据测试显示输出质量与人工整理差距大，根因是全链路缺少"理解"层。本 PRD 定义 v2.0 架构升级。

---

## 1. 升级背景与动机

### 1.1 v1.0 能力真相（gap 分析）

| 模块 | 名义能力 | 实际表现 | 根因 |
|------|---------|---------|------|
| `extractor.py` | 提取检验/影像/病理/用药 | 18 个正则，只覆盖检验数值；影像/病理/用药几乎提取不到 | 正则无法理解自由文本 |
| `analysis_engine.py` | 危急值+并发症评估 | 固定阈值规则，死板且易误报 | 无上下文判断 |
| `supportive_care.py` | 营养+并发症 | `build_supportive_care` 用 `str(profile.__dict__)` 当文本源 → biochemical_markers 永远为空 | 设计缺陷 |
| `recommendation_engine.py` | 个性化建议 | 5 条 lambda 规则，与真实临床决策差距巨大 | 知识库太薄 |
| 两个 renderer | 双轨输出 | 模板拼接，上游质量低 → 下游必然差 | 数据源问题 |

**一句话**：v1.0 链路几乎没真正用上 LLM。MinerU 把图片变 Markdown 后，后续全是"正则+规则+模板"。人工处理时人在**阅读理解、跨文档关联、医学推理**，而 v1.0 只在做**字符串匹配**——这是"差距很大"的根本原因。

### 1.2 用户核心诉求（3 个担心）

1. **LLM 能力最大化**：让 LLM 提炼核心信息、精细化数据，而非粗粒度正则
2. **隐私不泄露**：数百份真实病历含姓名/身份证/电话/病历号，不能直接送云端 LLM
3. **不一次处理**：即使百万上下文，一次性塞 100+ 文件会丢失关键细节；必须分治

### 1.3 v2.0 目标

- 单文件 LLM 提取质量 ≥ 人工整理的 80%（v1.0 约 30%）
- 零隐私泄露：送 LLM 的文本 100% 脱敏
- 细节不丢：每份文件独立 LLM 处理（Map），再按类聚合（Reduce）
- 性能可控：110 文件全流程 ≤ 30 分钟，成本 ≤ 10 元

---

## 2. v2.0 架构：三层 MapReduce

```
原始 .md (110份)
    │
    ▼ ① 脱敏层（本地、无 LLM）
    │  正则替换：姓名→[NAME]、身份证→[ID]、电话→[PHONE]、病历号→[MRN]
    │  产出：sanitized/*.md（可安全送 LLM）+ mapping.json（本地回填表）
    │
    ▼ ② Map 层（每文件独立 LLM，小上下文、专注、不丢细节）
    │  每份文件单独喂 LLM，function calling 强制输出结构化 JSON：
    │  {report_type, date, diagnosis[], lab_values[], medications[], findings[], noise[]}
    │  每文件一个 extracted/*.json
    │
    ▼ ③ Shuffle（本地、无 LLM）
    │  按 report_type 分类 + 按 date 排序 + 按 indicator 合并趋势
    │
    ▼ ④ Reduce 层（LLM 做跨文档推理）
    │  同类文档 JSON 聚合后喂 LLM：
    │  - 检验组：13 次 CA199 → 趋势判断、与影像一致性
    │  - 用药组：所有处方 → 重建化疗周期时间线
    │  - 影像组：所有 CT → 病灶演变叙事
    │
    ▼ ⑤ Profile 组装 + 渲染（复用 v1.0 renderer）
```

### 2.1 各层职责矩阵

| 层 | 输入 | 处理者 | 输出 | LLM | 隐私 |
|----|------|--------|------|-----|------|
| ① 脱敏 | 原始 .md | 本地正则 | sanitized/*.md + mapping.json | ❌ | 100% 本地 |
| ② Map | sanitized/*.md | LLM（逐文件） | extracted/*.json | ✅ | 已脱敏 |
| ③ Shuffle | extracted/*.json | 本地脚本 | grouped/*.json | ❌ | 已脱敏 |
| ④ Reduce | grouped/*.json | LLM（按类聚合） | merged/*.json | ✅ | 已脱敏 |
| ⑤ Profile | merged/*.json | 本地脚本 | patient_profile.json + 报告 | ❌ | 回填 |

### 2.2 为什么能解决 3 个核心担心

| 用户担心 | v2.0 解法 |
|---------|----------|
| ① LLM 最大化 | Map 层每文件专注提取（细节不丢）+ Reduce 层跨文档推理（全局视角），两次 LLM 各司其职 |
| ② 不泄隐私 | 脱敏层在 LLM **之前**，且只做本地正则；送 LLM 的是 `[NAME]` 占位符，回填在本地完成 |
| ③ 不一次处理 | MapReduce：Map 每文件独立（小上下文），Reduce 按类别聚合（中上下文），永不全量塞 |

---

## 3. 各层详细设计

### 3.1 脱敏层（P0）

**目标**：把含隐私的原始 Markdown 转成可安全送 LLM 的脱敏文本。

**脚本**：`scripts/desensitize.py`

**脱敏规则**（正则，纯本地）：

```python
DESENSITIZE_PATTERNS = [
    # 姓名：紧跟性别的 2-4 字汉字（中文姓名特征）
    (r'[\u4e00-\u9fa5]{2,4}(?=\s*[，,]?\s*(男|女))', '[NAME]'),
    # 身份证
    (r'\d{17}[\dXx]', '[ID]'),
    # 手机号
    (r'1[3-9]\d{9}', '[PHONE]'),
    # 座机
    (r'0\d{2,3}-?\d{7,8}', '[PHONE]'),
    # 病历号（紧跟"号/病/门诊/住院"）
    (r'\d{6,}(?=\s*[号]?\s*(病|门诊|住院))', '[MRN]'),
    # 电子邮箱
    (r'[\w.]+@[\w.]+', '[EMAIL]'),
    # 地址（省市区+路号）
    (r'[\u4e00-\u9fa5]{2,}(省|市|区|县|路|街|号|弄|室)\d*', '[ADDR]'),
    #银行卡号
    (r'\d{16,19}', '[CARD]'),
]
```

**回填机制**：维护 `mapping.json`，渲染阶段反向替换。

```json
{
  "[NAME]_1": "秦晓强",
  "[MRN]_1": "11493391",
  "[PHONE]_1": "138****8888"
}
```

**验收标准**：
- 随机抽样 20 份脱敏后文本，人工检查 0 处隐私残留
- 回填准确率 100%（脱敏-回填往返一致）
- 性能：110 文件 < 30 秒

### 3.2 Map 层（P0）

**目标**：每份脱敏文件单独喂 LLM，用 function calling 输出结构化 JSON。

**脚本**：`scripts/map_extract.py`

#### 3.2.1 Function Calling Schema

```json
{
  "name": "extract_medical_record",
  "description": "从一份医疗文件中提取结构化信息",
  "parameters": {
    "type": "object",
    "properties": {
      "report_type": {
        "type": "string",
        "enum": ["lab", "imaging", "pathology", "medication", "clinical", "other"]
      },
      "report_date": {"type": "string", "description": "YYYY-MM-DD 或空"},
      "confidence": {"type": "number", "description": "0-1"},
      "diagnoses": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "name": {"type": "string"},
            "icd10": {"type": "string"},
            "subtype": {"type": "string"},
            "confirmed_date": {"type": "string"}
          }
        }
      },
      "lab_values": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "name": {"type": "string", "description": "如 CA199 / CEA / 血红蛋白"},
            "value": {"type": "number"},
            "unit": {"type": "string"},
            "ref_low": {"type": "number"},
            "ref_high": {"type": "number"},
            "abnormal": {"type": "boolean"}
          }
        }
      },
      "medications": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "drug": {"type": "string"},
            "dose": {"type": "string"},
            "route": {"type": "string"},
            "frequency": {"type": "string"},
            "cycle": {"type": "string", "description": "如 C15D1"}
          }
        }
      },
      "findings": {
        "type": "array",
        "items": {"type": "string"},
        "description": "影像所见、病理描述、查体等自由文本要点"
      },
      "procedures": {
        "type": "array",
        "items": {"type": "string"},
        "description": "手术/操作名称"
      },
      "noise": {
        "type": "array",
        "items": {"type": "string"},
        "description": "非医疗内容：发票、收据、截图、付款码等（用于过滤）"
      }
    },
    "required": ["report_type", "confidence"]
  }
}
```

#### 3.2.2 System Prompt

```
你是一名资深病案整理员。下面是一份医疗文件（已脱敏）。
请提取其中的结构化信息。注意：
1. report_type 必须准确：检验报告选 lab，CT/MRI/超声选 imaging，病理/基因选 pathology，
   处方/医嘱选 medication，出院/门诊/手术记录选 clinical。
2. 如非医疗文件（发票、收据、聊天截图），report_type=other，noise 字段标明原因。
3. 数值必须带单位和参考范围（如报告自带）。
4. 如某字段在文件中不存在，返回空数组，不要编造。
5. confidence 反映你对该分类的把握。
```

#### 3.2.3 模型与成本

| 文件类型 | 推荐模型 | 单文件 token | 成本估算 |
|---------|---------|-------------|---------|
| 通用 | qwen3-flash | ~2k in + ~1k out | ¥0.002/文件 |
| 复杂（病理/影像） | glm-4-flash | ~3k in + ~1.5k out | ¥0.005/文件 |
| 总计（110 文件） | 混合 | ~250k tokens | **< ¥0.5** |

**验收标准**：
- 110 文件全部成功提取（失败率 < 5%）
- 抽样 20 文件，report_type 准确率 ≥ 90%
- lab_values 提取召回率 ≥ 85%（对比人工标注）
- noise 字段正确过滤发票/收据

### 3.3 Shuffle 层（P1）

**目标**：按 report_type 分组、按 date 排序、按 indicator 合并趋势。

**脚本**：`scripts/shuffle_group.py`

**输出结构**：

```
grouped/
├── lab_group.json        # 所有检验，按 date 排序，指标合并
├── imaging_group.json    # 所有影像，按 date 排序
├── pathology_group.json  # 病理+基因
├── medication_group.json # 处方+医嘱
├── clinical_group.json   # 出院/门诊/手术
└── other_group.json      # 待人工确认（含 noise）
```

**趋势合并逻辑**（lab_group 专用）：

```python
# 把分散在多份报告的同一指标合并成时间序列
{
  "CA199": {
    "unit": "U/ml",
    "ref_range": [0, 37],
    "trend": [
      {"date": "2023-06-01", "value": 342, "source": "report_001"},
      {"date": "2024-12-02", "value": 19.1, "source": "report_045"}
    ]
  }
}
```

**冲突处理**：同一天同一指标有多个值 → 保留所有，标 `conflict: true`，Reduce 层裁决。

### 3.4 Reduce 层（P1）

**目标**：每组聚合数据交给 LLM 做跨文档推理。

**脚本**：`scripts/reduce_merge.py`

#### 3.4.1 各组 Reduce Prompt

**检验组**：
```
以下是患者 CA199 在 13 次随访中的数值（已脱敏）：
{trend_json}

请判断：
1. 整体趋势（持续下降/上升/波动/稳定）
2. 是否有连续 3 次上升（临床预警信号）
3. 与参考范围的关系
4. 治疗反应推断（CR/PR/SD/PD 的可能性）
输出 JSON：{trend_summary, alert_level, clinical_inference}
```

**用药组**：
```
以下是患者所有处方/医嘱记录（已脱敏，按时间排序）：
{medications_json}

请重建完整的化疗时间线：
1. 识别化疗方案（如 AG 方案）
2. 计算完成的周期数
3. 每周期的起止日期、用药、剂量
4. 疗效评估节点（PR/SD/PD）
5. 副作用记录
输出 JSON：{regimens[], cycles[], response_assessments[], toxicities[]}
```

**影像组**：
```
以下是患者所有 CT/MRI/PET-CT 报告（按时间排序）：
{imaging_json}

请生成病灶演变的连贯叙事：
1. 原发灶变化（大小、密度、强化）
2. 转移灶变化（淋巴结、肝、腹膜）
3. 与前片对比的结论
4. 临床意义推断
输出 JSON：{primary_lesion_timeline, metastasis_timeline, overall_response}
```

#### 3.4.2 Reduce 模型选择

| 组 | 模型 | 理由 |
|----|------|------|
| lab | qwen3-flash | 数值趋势，简单推理 |
| imaging | glm-4-flash | 需要医学叙事能力 |
| medication | glm-4-flash | 周期重建复杂 |
| pathology | glm-4-flash | 术语理解 |
| clinical | glm-4-flash | 长文本综合 |

**总成本估算**：5 组 × ~5k tokens ≈ ¥0.05

### 3.5 Profile 组装 + 渲染（P2）

复用 v1.0 的 `render_clinical.py` 和 `render_patient.py`，数据源从正则输出换成 Reduce 输出。

**修复项**：
- 修复 `supportive_care.build_supportive_care` 的 `str(profile.__dict__)` bug → 改为接收 Map 层的 lab_values
- `analysis_engine` 的固定阈值规则保留作为**初筛**，Reduce 层的 LLM 推理作为**精判**

---

## 4. 隐私保护设计（核心要求）

### 4.1 三道防线

| 防线 | 位置 | 机制 |
|------|------|------|
| 第一道 | 脱敏层 | 本地正则替换，LLM 永远看不到原始隐私 |
| 第二道 | 模型选择 | 优先本地部署（Qwen 本地版），次选国内合规云（SiliconFlow 已签 DPA） |
| 第三道 | mapping.json 加密 | 回填表本地存储，文件权限 600，可选 AES 加密 |

### 4.2 mapping.json 管理

```python
# 存储
mapping_path = "~/patients/P_xxx/private/mapping.json"
os.chmod(mapping_path, 0o600)  # 仅 owner 可读

# 可选加密（pyca/cryptography）
from cryptography.fernet import Fernet
key = load_or_generate_key()  # 存 keychain
cipher = Fernet(key)
encrypted = cipher.encrypt(json.dumps(mapping).encode())
```

### 4.3 合规说明

- 脱敏后的文本**不含**任何可识别个人信息（PII）
- 即使 LLM 服务商日志泄露，也无法还原患者身份
- mapping.json 仅本地保存，不出现在任何输出报告中（渲染时回填后即用即弃）

---

## 5. 与 v1.0 的兼容性

### 5.1 保留的 v1.0 模块

| 模块 | v2.0 角色 |
|------|----------|
| `patient_profile.py` | ✅ 保留，作为最终数据模型（schema v1.0 不变） |
| `render_clinical.py` | ✅ 保留，数据源换成 Reduce 输出 |
| `render_patient.py` | ✅ 保留，同上 |
| `batch_ocr.py`（MinerU 批量） | ✅ 保留，作为最前置的 OCR 层 |

### 5.2 替换的 v1.0 模块

| 模块 | v2.0 替代 | 说明 |
|------|----------|------|
| `extractor.py`（正则） | `map_extract.py`（LLM） | 提取质量飞跃 |
| `supportive_care.build_supportive_care` | 修复 bug + 接 Map 输出 | 营养数据不再丢失 |
| `analysis_engine` 固定阈值 | 保留作初筛 + Reduce 精判 | 双层判断 |
| `recommendation_engine` lambda 规则 | Reduce 层 + 规则混合 | 知识库扩充 |

### 5.3 数据流对比

```
v1.0: MinerU .md → [正则提取] → Profile → [模板渲染] → 报告
                              ↑ 质量瓶颈

v2.0: MinerU .md → [脱敏] → [Map: LLM 逐文件] → [Shuffle] → [Reduce: LLM 跨文档] → Profile → [渲染] → 报告
                     ↑防泄露        ↑细节不丢                    ↑全局推理
```

---

## 6. 实施计划

### 6.1 阶段划分

| 阶段 | 任务 | 优先级 | 工时 | 依赖 |
|------|------|--------|------|------|
| **Phase 1** | 脱敏层 `desensitize.py` | P0 | 1 天 | 无 |
| **Phase 2** | Map 层 `map_extract.py` + function calling | P0 | 2-3 天 | Phase 1 |
| **Phase 3** | Shuffle 层 `shuffle_group.py` | P1 | 1 天 | Phase 2 |
| **Phase 4** | Reduce 层 `reduce_merge.py` + prompt 工程 | P1 | 2 天 | Phase 3 |
| **Phase 5** | 修复 supportive_care bug + 接 Reduce 输出 | P1 | 0.5 天 | Phase 4 |
| **Phase 6** | 端到端联调 + 真实数据验收 | P2 | 1 天 | Phase 5 |
| **Phase 7** | 成本/性能优化（本地模型选项） | P2 | 按需 | Phase 6 |

**总工时**：7.5-8.5 天

### 6.2 验收里程碑

| 里程碑 | 标准 |
|--------|------|
| M1（Phase 1 完成） | 110 文件脱敏后 0 处隐私残留 |
| M2（Phase 2 完成） | 110 文件 Map 提取，report_type 准确率 ≥ 90%，发票被过滤 |
| M3（Phase 4 完成） | CA199 趋势、化疗周期、影像演变 3 项 Reduce 输出通过人工抽检 |
| M4（Phase 6 完成） | 患者版报告与人工整理对比，关键信息覆盖率 ≥ 80% |

### 6.3 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| LLM 提取质量不达标 | 中 | 高 | Phase 2 完成后即对比人工，不达标则调 prompt 或换模型 |
| 脱敏规则漏网 | 低 | 高 | 随机抽检 + mapping.json 审计 |
| 成本超预算 | 低 | 中 | qwen3-flash 为主，glm-4-flash 仅复杂文件 |
| LLM 服务不可用 | 中 | 中 | 本地 Qwen 备选 + 失败重试 + 降级到正则 |

---

## 7. 成功指标

### 7.1 质量指标（对比人工标注）

| 指标 | v1.0 基线 | v2.0 目标 | 测量方法 |
|------|----------|----------|---------|
| 检验指标提取召回率 | ~40% | ≥ 85% | 对比人工标注的 20 份抽样 |
| 诊断信息覆盖率 | ~30% | ≥ 80% | 同上 |
| 用药方案完整度 | ~20% | ≥ 75% | 化疗周期数、剂量准确率 |
| 影像叙事连贯性 | N/A | 人工评分 ≥ 4/5 | 医生阅读评分 |
| 发票/噪音过滤率 | 0% | ≥ 95% | noise 字段准确率 |

### 7.2 性能指标

| 指标 | 目标 |
|------|------|
| 110 文件全流程 | ≤ 30 分钟 |
| 总 API 成本 | ≤ ¥10 |
| 脱敏耗时 | < 30 秒 |
| 单文件 Map 耗时 | < 10 秒 |

### 7.3 安全指标

| 指标 | 目标 |
|------|------|
| 送 LLM 文本隐私残留 | 0 处 |
| mapping.json 泄露风险 | 仅本地 + 可选加密 |
| 回填准确率 | 100% |

---

## 8. 文档关联

| 文档 | 说明 |
|------|------|
| `docs/patient-profile-schema-v1.md` | Schema v1.0（v2.0 不变，复用） |
| `docs/plans/2026-06-22-patient-profile-implementation.md` | v1.0 实现计划（已完成） |
| `docs/prd-v2-mapreduce-architecture.md` | **本文档（v2.0 PRD）** |

---

## 9. 决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| LLM 调用方式 | MapReduce 两段式 | 兼顾细节（Map）与全局（Reduce），避免一次塞全量 |
| 脱敏位置 | Map 之前的独立层 | 隔离隐私，便于审计 |
| 脱敏方式 | 正则（非 LLM） | 确定性、可审计、零隐私风险 |
| Reduce 分组维度 | report_type | 医生思维自然分类，上下文聚焦 |
| 模型选择 | qwen3-flash 为主 | 性价比高，国内合规 |
| v1.0 模块复用 | patient_profile + 两个 renderer | 数据模型稳定，渲染层解耦 |

---

## 10. 下一步行动

1. **立即**：基于本 PRD 创建 v2.0 实现计划（writing-plans）
2. **Phase 1 启动**：脱敏层先行，验证隐私保护
3. **Phase 2 原型**：Map 层用 5 份真实文件做 PoC，验证 LLM 提取质量
4. **质量门禁**：Phase 2 完成后对比人工，决定是否全面投入

---

*本 PRD 取代 v1.0 的正则/规则架构，作为 patient-record-organizer 的主设计。*
