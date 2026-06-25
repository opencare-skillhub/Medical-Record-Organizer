# HTML 模板 Context 数据模型

> 定义 `html-report-template.html` 中所有 Jinja2 变量的来源与转换逻辑。
> `compute_report_context()` 函数（`scripts/v2/render_html.py`）必须按本文档产出 context dict。

---

## 模板变量清单

| 模板变量 | 类型 | 来源 (PatientProfile 路径) | 转换逻辑 |
|----------|------|---------------------------|---------|
| `demographics` | `dict` | `profile.demographics` | 转换为模板期望的 flat dict（见下方） |
| `has_critical` | `bool` | `any(a.level == "critical" for a in profile.alerts)` | 直接映射 |
| `critical_alerts` | `list[dict]` | `[a for a in profile.alerts if a.level == "critical"]` | 添加 `emoji` 字段（根据 category 映射） |
| `timeline` | `list[dict]` | 从 manifest `timeline` + profile `diagnoses` + `surgeries` + `medications` 综合构建 | 每项含 `dates`, `title`, `category`, `note` |
| `pathology` | `list[dict]` | `profile.pathology` | 转换为 `{label, type, date, summary, findings, value, is_critical}` |
| `pathology_tag` | `string?` | 无直接来源 | 暂设 `None` |
| `genetic_highlights` | `list[dict]` | `profile.genetic_profile.tests` + `profile.pathology[].ihc` | 合并；每项含 `category`, `gene`/`marker`, `result`/`mutation`, `pathogenic`, `is_critical`, `tags` |
| `ihc_note` | `string?` | 无直接来源 | 暂设 `None`，后续可由 LLM 生成 |
| `medication_summary` | `list[dict]` | `profile.medications` (current=True) | 转换为 `{label, value, is_critical}` |
| `medication_table` | `list[dict]` | `profile.medications` | 转换为 `{name, dose, route, purpose}` |
| `medication_prescription_date` | `string` | `profile.medications[0].start_date` | 取最近处方日期 |
| `medication` | `dict` | `profile.medications` | `{current: [str], history: [str]}` |
| `imaging_summary` | `list[dict]` | `profile.imaging` | 转换为 `{date, modality, findings}` |
| `tumor_marker_tables` | `dict[str, dict]` | `profile.lab_tests.tumor_markers` | `{marker_name: {unit, ref_range, rows[{date, value, change, note, is_abnormal}]}}` |
| `lab_trend` | `list[dict]` | 同上（旧格式兜底） | `[{date, ca199, cea, ca125}]` |
| `chart_svg_ca199` | `string` (raw HTML) | 由 `tumor_marker_tables["CA199"]` 计算生成 | SVG 折线图，用 `matplotlib` 或字符串模板 |
| `chart_svg` | `string` (raw HTML) | 同 `chart_svg_ca199` | 兜底 |
| `key_concerns` | `list[str]` | `profile.alerts` (level in warning/critical) 的 `message` | 直接映射 |
| `consultation_questions` | `list[str]` | `profile.recommendations` 中 `priority="high"` 的 `message` | 直接映射 |
| `files` | `list[dict]` | `profile.data_sources.file_registry` | 转换为 `{title, date}` |
| `gaps` | `list[str]` | 手动配置或从 manifest 加载 | 直接映射 |
| `updated_at` | `string` | `profile.data_sources.last_updated` | 直接映射 |
| `report_title` | `string` | `profile.diagnoses[0].name` if exists | 默认 `"患者病情概览"` (通用化) |

---

## `demographics` 转换详情

```python
# PatientProfile.demographics → 模板期望的 flat dict
{
    "name": demo.name or "患者",
    "gender": demo.gender or "",
    "age": demo.age or "XX",
    "height": demo.height_cm,        # int → 保留原值，模板单位 cm
    "weight": demo.weight_kg,        # float → 保留原值，模板单位 kg
    "past_history": None,            # 无来源，暂空
    "primary_diagnosis": profile.diagnoses[0].name if profile.diagnoses else None,
    "icd_code": profile.diagnoses[0].icd10 if profile.diagnoses else None,
}
```

**注意**：模板使用 `.get('height')` / `.get('weight')` 不带 `_cm`/`_kg` 后缀，但 `Demographics` 模型字段是 `height_cm` / `weight_kg`。转换时需要做字段名映射。

---

## `genetic_highlights` 转换详情

合并两个来源：

1. **`profile.genetic_profile.tests`**（`List[Dict]`）：
   - 每项的 `gene`、`mutation`、`result` 字段直接映射
   - `category` 设为 `"gene"`
   - `pathogenic` 根据 mutation 描述判断（含 "致病"/"pathogenic" → True）

2. **`profile.pathology[].ihc`**（`List[Dict]`）：
   - 每项的 `marker`、`result` 字段直接映射
   - `category` 设为 `"ihc"`（模板据此分栏展示）
   - 无 `is_critical`/`tags` 字段，默认空

---

## `tumor_marker_tables` 转换详情

```python
# 输入: profile.lab_tests.tumor_markers
# {"CA199": {"unit": "U/ml", "trend": [{"date": "2025-01-01", "value": 100, ...}, ...]}, ...}

# 输出:
{
    "CA199": {
        "unit": "U/ml",
        "ref_range": "0–37 U/mL",
        "rows": [
            {
                "date": "2025-01-01",
                "value": 100,
                "change": "—",           # 第一条无变化
                "note": "",
                "is_abnormal": True
            },
            {
                "date": "2025-02-01",
                "value": 150,
                "change": "↑ 50 (50%)",   # 相对于前一条
                "note": "",
                "is_abnormal": True
            }
        ]
    }
}
```

变化计算：`change = value - prev_value`，格式化为 `↑/↓ abs (pct%)`。无前值的首条显示 `"—"`。

---

## SVG 折线图生成 (`chart_svg_ca199`)

- 从 `tumor_marker_tables["CA199"].rows` 取 date（X 轴）和 value（Y 轴）
- Y 轴范围：0 到 max(value) * 1.2
- 参考范围线：水平虚线标记在 ref_high 处
- 使用纯字符串模板生成（无需 matplotlib 依赖）：
  - SVG `polyline` 元素连接数据点
  - 圆点标记每个数据点
  - 异常值点用红色填充

---

## 缺失字段（模板引用但无数据源）

| 模板变量 | 现状 | 建议 |
|----------|------|------|
| `pathology_tag` | 无来源 | 设为 `None`，模板 `{% if %}` 自动跳过 |
| `ihc_note` | 无来源 | 后续用 LLM 从 IHC 结果生成一段分析文本 |
| `demographics.past_history` | `Demographics` 无此字段 | 考虑在 Demographics 模型中增加 `past_history: Optional[str]` |
| `demographics.icd_code` | `Diagnosis.icd10` 可映射 | 已在转换中处理 |

---

## 模板通用化标记

以下模板中硬编码的胰腺癌特定文本需要改为变量注入：

| 位置 | 当前文本 | 建议 |
|------|---------|------|
| `<title>` L20 | `胰腺肿瘤患者病情概览` | `{{ report_title \| e }}` |
| `<h1>` L217 | `胰腺肿瘤患者病情概览` | `{{ report_title \| e }}` |
| CSS `tr.latest` L163 | `#1c5ca8` (蓝色) | 保留（通用样式） |

`report_title` 默认值：`"{{ primary_diagnosis }}患者病情概览"`（如有诊断），否则 `"患者病情概览"`。
