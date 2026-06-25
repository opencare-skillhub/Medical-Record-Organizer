# Map 阶段标准输出 Schema (v1.1)

> 本文档是 Shuffle/Reduce 阶段读取 Map 输出的唯一契约。
> `map_extract.py` 的 `MAP_SCHEMA` 和 `SYSTEM_PROMPT` 必须按此文档生成 JSON。

---

## 根对象

```json
{
  "report_type": "lab_results",          // 必填，enum: lab_results | imaging | pathology | medication | clinical_records | basic_info | invoice | noise
  "document_date": "2025-03-15",         // 必填，ISO 日期字符串 YYYY-MM-DD
  "source_file": "report_01.md"          // 由调用方注入，不在 Schema 中约束
}
```

## 分类枚举 (`report_type`)

| 值 | 说明 | Shuffle 分组 |
|----|------|-------------|
| `lab_results` | 检验报告（血常规/生化/标志物等） | `lab` |
| `imaging` | 影像检查（CT/MRI/超声/内镜等） | `imaging` |
| `pathology` | 病理报告（组织/基因等） | `pathology` |
| `medication` | 用药/处方 | `medication` |
| `clinical_records` | 出院小结/门诊/手术记录等 | `clinical` |
| `basic_info` | 患者基本信息 | `demographics` |
| `invoice` | 发票/收据 | `noise`（跳过） |
| `noise` | 非医疗内容 | `noise`（跳过） |

---

## `demographics`（可选）

```json
{
  "demographics": {
    "name": "string?",
    "gender": "string?",
    "age": 0,
    "medical_record_no": "string?"
  }
}
```

---

## `lab_values`（核心：Shuffle 直接消费）

所有检验指标用**展平数组**输出。每项必须包含：

```json
{
  "lab_values": [
    {
      "name": "CA199",          // 必填，指标名
      "value": 125.0,           // 必填，数值 (number)
      "unit": "U/ml",           // 必填，单位
      "date": "2025-03-15",     // 可选，如缺失则用根 document_date
      "ref_low": 0,             // 可选，参考范围下限
      "ref_high": 37,           // 可选，参考范围上限
      "abnormal": true          // 可选，是否异常
    }
  ]
}
```

**兼容说明**：同时保留 `lab_tests` 嵌套结构供下游按需使用：

```json
{
  "lab_tests": {
    "tumor_markers": [
      {"name": "CA199", "value": 125.0, "unit": "U/ml", "date": "2025-03-15"}
    ],
    "blood_routine": [],
    "liver_kidney": []
  }
}
```

`merge_lab_trends()` 优先读 `lab_values`；如果为空则回退到 `lab_tests` 嵌套结构。

---

## `imaging`（可选）

```json
{
  "imaging": [
    {
      "modality": "CT",
      "date": "2025-03-15",
      "findings": "右肺上叶结节 2.1cm",
      "conclusion": "考虑恶性可能"
    }
  ]
}
```

---

## `medications`（可选）

```json
{
  "medications": [
    {
      "name": "奥希替尼",
      "type": "靶向",
      "start_date": "2025-01-01",
      "dosage": "80mg QD"
    }
  ]
}
```

---

## `diagnoses`（可选）

```json
{
  "diagnoses": [
    {
      "name": "胰腺导管腺癌",
      "stage": "T3N1M0",
      "confirmed_date": "2025-01-15"
    }
  ]
}
```

---

## 完整示例

```json
{
  "report_type": "lab_results",
  "document_date": "2025-03-15",
  "lab_values": [
    {"name": "CA199", "value": 125.0, "unit": "U/ml", "ref_low": 0, "ref_high": 37, "abnormal": true},
    {"name": "CEA", "value": 3.5, "unit": "ng/ml", "ref_low": 0, "ref_high": 5, "abnormal": false},
    {"name": "WBC", "value": 6.2, "unit": "×10^9/L", "ref_low": 3.5, "ref_high": 9.5, "abnormal": false}
  ],
  "lab_tests": {
    "tumor_markers": [
      {"name": "CA199", "value": 125.0, "unit": "U/ml", "date": "2025-03-15"},
      {"name": "CEA", "value": 3.5, "unit": "ng/ml", "date": "2025-03-15"}
    ],
    "blood_routine": [
      {"name": "WBC", "value": 6.2, "unit": "×10^9/L", "date": "2025-03-15"}
    ],
    "liver_kidney": []
  }
}
```

---

## Shuffle 阶段的消费约定

| Shuffle 函数 | 读取字段 | 期望类型 |
|-------------|---------|---------|
| `group_by_type()` | `report_type` | string |
| `merge_lab_trends()` | `lab_values[]` | array of objects（优先）；回退 `lab_tests.*` |
| `cluster_by_indicator()` | `lab_values[]` | array of objects（优先） |

## Reduce 阶段的消费约定

| Reduce 函数 | 读取字段 | 期望类型 |
|------------|---------|---------|
| `reduce_lab_trends()` | `trends: {indicator: {unit, ref_range, trend[]}}` | dict |
| `reduce_medication_history()` | `medications[]` from Map output | array |
| `reduce_imaging_narrative()` | `imaging[]` from Map output | array |
