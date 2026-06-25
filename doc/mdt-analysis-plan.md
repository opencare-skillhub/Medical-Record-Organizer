# AI-MDT 关注问题分析模块 — 实施计划

> 版本：v1.0
> 创建日期：2026-06-24
> 状态：已批准（待实施）
> 关联文档：[data-contract.md](./data-contract.md)、[template-context.md](./template-context.md)

---

## 1. 核心问题

当前 `key_concerns` 只是 `critical_alerts[].message` 的机械聚合（如"CEA: 14.65 ng/mL（异常）"这种数据罗列），存在以下问题：

- **无分析含金量**：只罗列异常数值，没有跨学科整合、没有临床推理
- **内容重叠**：同一问题被多个异常指标重复表达
- **未利用 AI 能力**：现有 reduce 层已产出 `lab_analysis` / `imaging_narrative` / `medication_timeline` 等结构化分析结果，但 `key_concerns` 完全没有消费它们

**用户诉求**：模拟真实 MDT（多学科会诊）流程，输出不重叠、有分析价值的关键关注要点，体现 AI 的分析能力而非数据堆积。

---

## 2. 架构设计

### 2.1 在 Pipeline 中的位置

在 **Reduce 层之后新增 Phase 4.5 MDT 阶段**，采用 **多专科分别分析再整合** 模式：

```
Phase 4 (现有 Reduce)
  ├─ reduce_lab_trends      → lab_analysis
  ├─ reduce_medication      → medication_timeline
  └─ reduce_imaging         → imaging_narrative
         │
Phase 4.5 (新增 MDT)        ← 接收以上 3 个结构化结果作为输入
  ├─ mdt_oncology           肿瘤内科视角（综合病情走势/疗效/进展）
  ├─ mdt_radiology          影像视角（病灶演变/转移/疗效评估）
  ├─ mdt_pathology          病理视角（组织学/基因/免疫组化/药物毒性）
  ├─ mdt_pharmacy           药学视角（方案/剂量/毒副/药物相互作用）
  ├─ mdt_nursing            护理视角（症状管理/生活质量/依从性）
  └─ mdt_synthesis          MDT 整合主席（去重/排序/跨学科关联）
         │
         ▼
Phase 5: profile['mdt_analysis'] → 渲染层 key_concerns
```

共 **6 次 LLM 调用**（5 专科可并行，1 次整合串行）。

### 2.2 数据流（每个专科看到什么）

| 专科 | 输入数据（已结构化，非原始文本） |
|------|-----|
| 肿瘤内科 | `lab_trends`（标志物趋势）+ `imaging overall_response` + `response_assessments` + `demographics` |
| 影像 | `imaging_summary`（逐条发现）+ `imaging_narrative`（primary/metastasis timeline） |
| 病理 | `pathology test_items`（基因/IHC）+ `genetic_highlights` + UGT1A1 |
| 药学 | `medication_timeline`（方案/毒副）+ `response_assessments` + 药物代谢基因 |
| 护理 | `toxicities` + `gaps` + 关键异常指标 + 用药副作用 |
| 整合 | 以上 5 个专科的 JSON 输出 |

---

## 3. 新建文件

### 3.1 `scripts/mdt_analysis.py` — MDT 分析核心模块

**5 个专科提示词 + 1 个整合提示词**，每个提示词遵循高质量医学提示词工程原则：

- 明确角色定位 + 学科边界
- 注入完整结构化数据（不是原始文本）
- 要求基于数据做推理，标注证据来源
- 强制输出 schema（优先级/学科标签/跨学科关联）
- 安全边界：只做病情整理分析，不给出诊断结论

**关键函数签名：**

```python
def run_mdt_analysis(profile, groups, *, model=None) -> Dict[str, Any]:
    """执行完整 MDT 分析流程"""
    # 1. 并行调用 5 个专科分析
    # 2. 串行调用整合分析
    # 3. 返回 {specialties: {...}, concerns: [...]}

def mdt_oncology_analysis(data_bundle) -> Dict   # 肿瘤内科
def mdt_radiology_analysis(data_bundle) -> Dict  # 影像
def mdt_pathology_analysis(data_bundle) -> Dict  # 病理/基因
def mdt_pharmacy_analysis(data_bundle) -> Dict   # 药学
def mdt_nursing_analysis(data_bundle) -> Dict    # 护理/支持
def mdt_synthesis_analysis(specialty_reports, ...) -> Dict  # 整合
```

**数据包（data_bundle）构建**：从 profile + groups 抽取各专科所需的结构化数据，而非原始文本。

### 3.2 提示词设计（核心含金量所在）

每个专科提示词结构（以肿瘤内科为例的骨架）：

```
【角色】你是一位资深肿瘤内科 MDT 专家（主治医师以上），参加多学科会诊。
你只负责从【肿瘤内科】视角分析病情，不涉及影像读片、病理诊断、具体用药调整
（那是其他专科的职责）。

【患者概要】{demographics + diagnosis}

【检验指标趋势（已结构化）】
{lab_trends: 各标志物趋势/变化率/异常状态}

【影像总体评估】{imaging_narrative.overall_response}

【治疗疗效评估】{medication response_assessments: PR/SD/PD 时间点}

【你的任务】从肿瘤内科视角，识别本患者当前最需要关注的临床问题：
1. 基于【肿瘤标志物趋势】判断疾病活动度（活跃/稳定/缓解），结合影像评估一致性
2. 基于【疗效评估时间线】判断当前治疗方案是否仍有效，有无耐药迹象
3. 基于【标志物变化速率】预警潜在进展风险（如连续 N 次上升）
4. 识别肿瘤内科视角的【未解决疑问】

输出 2-3 条关注要点，每条必须包含：
- concern: 问题陈述（一句话，聚焦一个点，不要数据罗列）
- analysis: 跨数据关联分析（为什么这是问题，证据是什么）
- priority: high/medium/low
- discipline: oncology
```

**整合提示词（mdt_synthesis）** — 这是去重和提升含金量的关键：

```
【角色】你是 MDT 会诊主席（首席专家）。5 个专科已提交各自的关注要点。
你的任务是整合所有专科意见，输出一份【不重叠、有优先级、有跨学科关联】的
关注要点清单。

【各专科报告】
{5 个专科的 JSON 输出}

【整合原则】
1. 去重：不同专科可能关注同一问题（如药学看到 UGT1A1 毒性，病理也提到），
   合并为一条，标注涉及的学科
2. 跨学科关联：找出 A 学科发现 + B 学科发现共同指向的风险（如"标志物上升"
   + "影像腹膜转移" → 病情进展风险）
3. 优先级：威胁生命的 > 影响治疗决策的 > 需长期监测的
4. 每条必须有分析含金量（问题识别 + 证据链 + 建议【方向】），不是数据堆积
5. 输出 5-8 条，按优先级排序

输出 JSON: {concerns: [{title, analysis, priority, disciplines: [],
             suggested_direction, evidence: []}]}
```

---

## 4. 修改现有文件

### 4.1 `scripts/render_html.py`（及 render_md.py / render_report.py / v2/render_html.py）

在 `compute_report_context()` 中，优先使用 `profile['mdt_analysis']['concerns']`：

```python
# key_concerns 优先使用 MDT 分析结果
mdt_concerns = (profile.get('mdt_analysis') or {}).get('concerns', [])
if mdt_concerns:
    key_concerns = [_format_mdt_concern(c) for c in mdt_concerns]
else:
    # 降级：原有逻辑（critical_alerts message 聚合）
    key_concerns = [a['message'] for a in critical_alerts]
```

同步修改 `scripts/render_md.py`、`scripts/render_report.py`、`scripts/v2/render_html.py` 保持一致。

### 4.2 `references/html-report-template.html`

升级"关注问题要点"卡片，支持新的 MDT 结构化输出：

```html
<section class="card red">
  <h2>关注问题要点 <small style="font-size:11px;color:#888">（AI-MDT 多学科分析）</small></h2>
  {% for c in key_concerns %}
  <div class="mdt-concern {{ c.priority }}">
    <span class="priority-badge {{ c.priority }}">{{ priority_label }}</span>
    <div class="concern-title">{{ c.title }}</div>
    <div class="concern-analysis">{{ c.analysis }}</div>
    {% if c.disciplines %}
    <div class="discipline-tags">
      {% for d in disciplines %}<span class="tag">{{ d }}</span>{% endfor %}
    </div>
    {% endif %}
    {% if c.suggested_direction %}
    <div class="suggestion">💡 {{ c.suggested_direction }}</div>
    {% endif %}
  </div>
  {% endfor %}
</section>
```

新增 CSS：
- 优先级颜色：high=红、medium=橙、low=蓝
- 学科 tag 样式
- 建议方向蓝底提示框

### 4.3 `scripts/pipeline.py` 和 `scripts/v2/pipeline_v2.py`

在 Phase 5（Profile 组装）之前插入 MDT 阶段：

```python
# Phase 4.5: MDT 多学科分析
from scripts.mdt_analysis import run_mdt_analysis
mdt_analysis = run_mdt_analysis(profile_draft, groups, model=model)

profile['mdt_analysis'] = mdt_analysis
```

### 4.4 `scripts/test_render_from_case_data.py`

补充 demographics 传入（修复上次的 P0 问题：患者基础信息为空），让 MDT 有完整数据可分析。

---

## 5. 降级策略（LLM 失败兜底）

1. **单专科失败** → 该专科返回空报告，整合层跳过它，日志告警
2. **整合层失败** → 直接拼接 5 个专科的 concerns（不去重），日志告警
3. **全部失败** → 降级为原有的 `critical_alerts[].message` 逻辑（保证报告仍能生成）
4. **环境无 API key** → 跳过 MDT，走降级逻辑，不报错

降级由 `run_mdt_analysis()` 内部 try/except 包裹，**永不抛出中断 pipeline**。

---

## 6. 验证方式

运行 `python3 scripts/test_render_from_case_data.py`，确认 `key_concerns` 从数据罗列变为分析性结论。

**预期输出对比：**

| | 改前 | 改后 |
|---|------|------|
| 内容性质 | 数据罗列 | 跨学科分析 |
| 示例 | `CEA: 14.65 ng/mL（异常）` | `CEA 在 2025-09-23 升至 10.2 后回落至 5.79，提示疾病处于低活动度但需警惕反弹；与影像"持续 SD"一致，目前治疗仍有效` |
| 条数 | 6 条（每个异常指标一条） | 5-8 条（按问题整合，不重叠） |
| 结构 | 纯文本 | 含优先级/学科标签/建议方向 |

---

## 7. 安全边界（始终遵守）

- 所有 MDT 输出附带"仅供参考，不构成诊断/治疗建议"
- 提示词中明确禁止给出具体用药剂量调整、具体诊断结论
- 分析基于数据推理，标注证据来源，不编造

---

## 8. 涉及文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `scripts/mdt_analysis.py` | **新建** | MDT 核心（6 个提示词 + 调度） |
| `scripts/render_html.py` | 修改 | key_concerns 优先用 MDT 结果 |
| `scripts/render_md.py` | 修改 | 同上 |
| `scripts/render_report.py` | 修改 | 同上 |
| `scripts/v2/render_html.py` | 修改 | 同上 |
| `scripts/pipeline.py` | 修改 | 插入 Phase 4.5 |
| `scripts/v2/pipeline_v2.py` | 修改 | 插入 Phase 4.5 |
| `references/html-report-template.html` | 修改 | 升级 key_concerns 卡片 |
| `scripts/test_render_from_case_data.py` | 修改 | 补充 demographics + 验证 |

---

## 9. 实施顺序

1. 先建 `mdt_analysis.py`（可独立测试）
2. 接入 pipeline（pipeline.py + v2/pipeline_v2.py）
3. 改渲染层（4 个 render 文件）
4. 改 HTML 模板
5. 用测试数据验证（test_render_from_case_data.py）
