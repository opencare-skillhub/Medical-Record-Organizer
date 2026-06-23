# PatientProfile 全链路实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从 MinerU 解析的 .md 文件自动提取结构化病情档案（PatientProfile），生成医护版 JSON + 患者版 Markdown，并运行分析引擎生成警示和建议。

**Architecture:** 
1. `patient_profile.py` — PatientProfile 数据类（Pydantic），定义 schema v1.0 的所有字段
2. `extractor.py` — 从 MinerU .md 提取实体，填充 PatientProfile
3. `analysis_engine.py` — 趋势分析、危急值检测、并发症风险评估
4. `recommendation_engine.py` — 基于知识库生成就医建议
5. `render_clinical.py` — 医护版输出（JSON + 摘要）
6. `render_patient.py` — 患者版输出（自然语言 + 可视化）

**Tech Stack:** Python 3.10+, Pydantic v2, MinerU API, DeepSeek-OCR, regex规则 + LLM兜底

## Global Constraints

- Python 3.10+，使用标准库 + Pydantic v2（已安装）
- 所有脚本放在 `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/scripts/`
- 输出目录：`~/patients/P_report_mess/output/` 和 `data/extracted/`
- 保持与现有 batch_ocr.py、manifest.json 的兼容性
- 不修改原始报告文件（只读）
- 每个模块独立可测试

---

## 文件结构

```
patient-record-organizer/
├── scripts/
│   ├── patient_profile.py      # PatientProfile Schema + Pydantic 模型
│   ├── extractor.py             # 实体提取器（MinerU .md → PatientProfile）
│   ├── analysis_engine.py       # 分析引擎（趋势、警示、并发症）
│   ├── recommendation_engine.py # 建议引擎
│   ├── render_clinical.py       # 医护版渲染器
│   └── render_patient.py        # 患者版渲染器
├── references/
│   ├── patient-profile-schema-v1.md  # Schema 定义（已存在）
│   ├── classification-rules.md       # 分类规则
│   └── case-report-template.md       # 患者版模板
└── docs/
    └── plans/
        └── 2026-06-22-patient-profile-implementation.md  # 本计划
```

---

### Task 1: PatientProfile Schema 实现

**Files:**
- Create: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/scripts/patient_profile.py`
- Test: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/tests/test_patient_profile.py`

**Interfaces:**
- Consumes: 无（顶层 schema）
- Produces: `PatientProfile` Pydantic 模型，供 extractor 使用

- [ ] **Step 1: 写失败的测试**

```python
# tests/test_patient_profile.py
import json
from pathlib import Path
from scripts.patient_profile import PatientProfile, Demographics, Diagnosis

def test_minimal_profile():
    profile = PatientProfile(
        patient_id="P_TEST",
        demographics=Demographics(name="测试", age=50, gender="男"),
        diagnoses=[],
    )
    assert profile.patient_id == "P_TEST"
    assert profile.demographics.name == "测试"
    assert profile.schema_version == "1.0"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/qinxiaoqiang/.agents/skills/patient-record-organizer
python -m pytest tests/test_patient_profile.py -v
# Expected: FAIL with "module not found"
```

- [ ] **Step 3: 实现 PatientProfile 模型**

```python
# scripts/patient_profile.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class Demographics(BaseModel):
    name: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    bmi: Optional[float] = None
    phone: Optional[str] = None
    medical_record_no: Optional[str] = None

class Diagnosis(BaseModel):
    id: str
    name: str
    subtype: Optional[str] = None
    icd10: Optional[str] = None
    grade: Optional[str] = None
    stage: Optional[Dict[str, Any]] = None
    confirmed_date: Optional[str] = None
    confirmed_by: Optional[str] = None
    hospital: Optional[str] = None
    status: str = "active"
    source_files: List[str] = []

class GeneticProfile(BaseModel):
    tests: List[Dict[str, Any]] = []

class LabTests(BaseModel):
    tumor_markers: Dict[str, Any] = {}
    blood_routine: Dict[str, Any] = {}
    liver_kidney: Dict[str, Any] = {}
    coagulation: Dict[str, Any] = {}
    thyroid: Dict[str, Any] = {}

class Imaging(BaseModel):
    id: str
    date: Optional[str] = None
    modality: str
    facility: Optional[str] = None
    findings: List[str] = []
    conclusion: Optional[str] = None
    comparison: Optional[str] = None
    source_files: List[str] = []

class Pathology(BaseModel):
    id: str
    date: Optional[str] = None
    procedure: Optional[str] = None
    diagnosis: Optional[str] = None
    ihc: List[Dict[str, str]] = []
    source_files: List[str] = []

class Medication(BaseModel):
    id: str
    name: str
    generic_name: Optional[str] = None
    type: str  # 化疗/靶向/免疫/支持
    start_date: Optional[str] = None
    current: bool = False
    cycles_completed: int = 0
    regimen: List[Dict[str, Any]] = []
    toxicities: List[Dict[str, Any]] = []
    source_files: List[str] = []

class Surgery(BaseModel):
    id: str
    date: Optional[str] = None
    procedure: str
    approach: Optional[str] = None
    findings: Optional[str] = None
    source_files: List[str] = []

class Alert(BaseModel):
    id: str
    level: str  # critical / warning / info
    category: str
    message: str
    date: Optional[str] = None
    action: Optional[str] = None
    source_data: List[str] = []

class Recommendation(BaseModel):
    priority: str  # high / medium / low
    category: str
    message: str
    based_on: str

class NutritionAssessment(BaseModel):
    weight_kg: Optional[float] = None
    height_cm: Optional[float] = None
    bmi: Optional[float] = None
    weight_change_6m_kg: Optional[float] = None
    albumin: Optional[Dict[str, Any]] = None
    prealbumin: Optional[Dict[str, Any]] = None
    trends: List[Dict[str, Any]] = []

class Complication(BaseModel):
    name: str
    risk_level: str  # low / medium / high / critical
    monitoring_indicators: Dict[str, Any] = {}
    symptoms: List[str] = []
    last_assessment: Optional[str] = None
    source_files: List[str] = []

class Psychological(BaseModel):
    screenings: List[Dict[str, Any]] = []
    tools: Dict[str, Any] = {}
    concerns: List[str] = []
    recommendations: List[str] = []

class SupportiveCare(BaseModel):
    nutrition: Optional[NutritionAssessment] = None
    complications: Dict[str, Complication] = {}
    psychological: Optional[Psychological] = None

class DataSources(BaseModel):
    total_files: int = 0
    extracted_files: int = 0
    failed_files: int = 0
    last_updated: Optional[str] = None
    mineru_batches: List[Dict[str, Any]] = []
    file_registry: List[Dict[str, Any]] = []

class PatientProfile(BaseModel):
    schema_version: str = "1.0"
    patient_id: str
    demographics: Demographics
    chief_complaint: Dict[str, Any] = {}
    diagnoses: List[Diagnosis] = []
    genetic_profile: GeneticProfile = GeneticProfile()
    lab_tests: LabTests = LabTests()
    imaging: List[Imaging] = []
    pathology: List[Pathology] = []
    medications: List[Medication] = []
    surgeries: List[Surgery] = []
    treatment_history: List[Dict[str, Any]] = []
    follow_up: List[Dict[str, Any]] = []
    supportive_care: SupportiveCare = SupportiveCare()
    alerts: List[Alert] = []
    recommendations: Dict[str, List[Recommendation]] = {"immediate": [], "next_visit": [], "lifestyle": []}
    data_sources: DataSources = DataSources()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /Users/qinxiaoqiang/.agents/skills/patient-record-organizer
python -m pytest tests/test_patient_profile.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add scripts/patient_profile.py tests/test_patient_profile.py
git commit -m "feat: add PatientProfile schema v1.0"
```

---

### Task 2: 实体提取器（Extractor）

**Files:**
- Create: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/scripts/extractor.py`
- Test: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/tests/test_extractor.py`

**Interfaces:**
- Consumes: `PatientProfile` from Task 1
- Produces: `ExtractionResult(profile, confidence, errors)`

- [ ] **Step 1: 写失败的测试**

```python
def test_extract_lab_values():
    from scripts.extractor import extract_lab_tests
    text = "CEA: 14.65 ng/ml (参考值 0-5)\nCA199: 342 U/ml (参考值 0-37)"
    result = extract_lab_tests(text, "test.png")
    assert len(result) == 2
    assert result[0]["name"] == "CEA"
    assert result[0]["value"] == 14.65
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/test_extractor.py::test_extract_lab_values -v
# Expected: FAIL
```

- [ ] **Step 3: 实现提取器**

```python
# scripts/extractor.py
import re
from typing import List, Dict, Any
from .patient_profile import PatientProfile, LabTests, Imaging, Pathology

# 检验指标正则库
LAB_PATTERNS = {
    "CEA": (r"癌胚抗原[^\d]*(\d+\.?\d*)\s*(ng/ml|U/ml)?", "ng/ml", 0, 5),
    "CA199": (r"糖类抗原\s*199[^\d]*(\d+\.?\d*)", "U/ml", 0, 37),
    "CA125": (r"糖类抗原\s*125[^\d]*(\d+\.?\d*)", "U/ml", 0, 35),
    "AFP": (r"甲胎蛋白[^\d]*(\d+\.?\d*)", "ng/ml", 0, 20),
    "WBC": (r"白细胞[计数]?[^\d]*(\d+\.?\d*)\s*\*?\^?\d*/L", "×10^9/L", 3.5, 9.5),
    "HGB": (r"血红蛋白[^\d]*(\d+\.?\d*)\s*g/L", "g/L", 130, 175),
    "PLT": (r"血小板[^\d]*(\d+\.?\d*)\s*\*?\^?\d*/L", "×10^9/L", 100, 300),
    "ALT": (r"丙氨酸氨基转移酶[^\d]*(\d+\.?\d*)\s*U/L", "U/L", 0, 40),
    "AST": (r"天门冬氨酸氨基转移酶[^\d]*(\d+\.?\d*)\s*U/L", "U/L", 0, 40),
    "Cr": (r"肌酐[^\d]*(\d+\.?\d*)\s*umol/L", "umol/L", 44, 133),
    "ALB": (r"白蛋白[^\d]*(\d+\.?\d*)\s*g/L", "g/L", 40, 55),
    "TBIL": (r"总胆红素[^\d]*(\d+\.?\d*)\s*umol/L", "umol/L", 3.4, 17.1),
    "DBIL": (r"直接胆红素[^\d]*(\d+\.?\d*)\s*umol/L", "umol/L", 0, 6.8),
    "ALP": (r"碱性磷酸酶[^\d]*(\d+\.?\d*)\s*U/L", "U/L", 45, 125),
    "GGT": (r"γ-谷氨酰转肽酶[^\d]*(\d+\.?\d*)\s*U/L", "U/L", 10, 60),
    "Amy": (r"淀粉酶[^\d]*(\d+\.?\d*)\s*U/L", "U/L", 35, 135),
    "D-dimer": (r"D[-–]二聚体[^\d]*(\d+\.?\d*)\s*mg/L", "mg/L", 0, 0.5),
}

def extract_lab_tests(text: str, source_file: str) -> List[Dict[str, Any]]:
    """从文本提取检验指标"""
    results = []
    for name, (pattern, unit, ref_low, ref_high) in LAB_PATTERNS.items():
        for m in re.finditer(pattern, text, re.IGNORECASE):
            value = float(m.group(1))
            flag = "↑" if value > ref_high else "↓" if value < ref_low else "正常"
            results.append({
                "name": name,
                "value": value,
                "unit": unit,
                "ref_range": {"low": ref_low, "high": ref_high},
                "flag": flag,
                "source": source_file,
            })
    return results

def extract_date(text: str, filename: str) -> str:
    """从文件名或文本提取日期"""
    # 优先文件名
    m = re.search(r"(\d{4})[-_.]?(\d{1,2})[-_.]?(\d{1,2})", filename)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # 文本
    for pat in [r"(\d{4})年(\d{1,2})月(\d{1,2})日", r"(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})"]:
        m = re.search(pat, text)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""

# 更多提取函数...
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/test_extractor.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add scripts/extractor.py tests/test_extractor.py
git commit -m "feat: add extractor for lab values and dates"
```

---

### Task 3: 分析引擎（Analysis Engine）

**Files:**
- Create: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/scripts/analysis_engine.py`
- Test: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/tests/test_analysis_engine.py`

**Interfaces:**
- Consumes: `PatientProfile` from Task 1
- Produces: `List[Alert]`（警示列表）

- [ ] **Step 1: 写失败的测试**

```python
def test_critical_alert():
    from scripts.analysis_engine import check_critical_values
    profile = create_test_profile_with_lab("HGB", 45, "g/L")
    alerts = check_critical_values(profile)
    assert any(a.level == "critical" and "血红蛋白" in a.message for a in alerts)

def test_complication_risk_gi_bleeding():
    from scripts.analysis_engine import assess_gi_bleeding_risk
    profile = create_test_profile_with_hgb(85)
    alerts = assess_gi_bleeding_risk(profile)
    assert any("消化道出血" in a.message for a in alerts)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/test_analysis_engine.py -v
# Expected: FAIL
```

- [ ] **Step 3: 实现分析引擎**

```python
# scripts/analysis_engine.py
from typing import List, Dict, Any
from .patient_profile import PatientProfile, Alert

# 危急值阈值（来自医学标准）
CRITICAL_THRESHOLDS = {
    "HGB": {"low": 60, "high": None, "unit": "g/L", "message": "血红蛋白极低，提示重度贫血"},
    "ALB": {"low": 25, "high": None, "unit": "g/L", "message": "白蛋白极低，重度营养不良"},
    "Cr": {"low": None, "high": 350, "unit": "umol/L", "message": "肌酐极高，肾功能异常"},
    "TBIL": {"low": None, "high": 342, "unit": "umol/L", "message": "总胆红素极高，严重黄疸"},
    "Amy": {"low": None, "high": 405, "unit": "U/L", "message": "淀粉酶显著升高，提示急性胰腺炎"},
}

def check_critical_values(profile: PatientProfile) -> List[Alert]:
    """检查危急值"""
    alerts = []
    for category in ["tumor_markers", "blood_routine", "liver_kidney"]:
        section = getattr(profile.lab_tests, category, {})
        for test_name, test_data in section.items():
            if test_name in CRITICAL_THRESHOLDS:
                thresh = CRITICAL_THRESHOLDS[test_name]
                trend = test_data.get("trend", [])
                if trend:
                    latest = trend[-1].get("value")
                    if latest:
                        if thresh["low"] and latest < thresh["low"]:
                            alerts.append(Alert(
                                id=f"critical_{test_name.lower()}",
                                level="critical",
                                category="lab_value",
                                message=f"{test_name} {latest}{thresh['unit']}（{thresh['message']}）",
                                action="立即联系医生",
                            ))
                        elif thresh["high"] and latest > thresh["high"]:
                            alerts.append(Alert(
                                id=f"critical_{test_name.lower()}",
                                level="critical",
                                category="lab_value",
                                message=f"{test_name} {latest}{thresh['unit']}（{thresh['message']}）",
                                action="立即联系医生",
                            ))
    return alerts

def check_trend_alerts(profile: PatientProfile) -> List[Alert]:
    """检查趋势异常（连续上升/下降）"""
    alerts = []
    # 肿瘤标志物连续3次上升
    for marker, data in profile.lab_tests.tumor_markers.items():
        trend = data.get("trend", [])
        if len(trend) >= 3:
            last3 = [t.get("value", 0) for t in trend[-3:]]
            if all(last3[i] < last3[i+1] for i in range(len(last3)-1)):
                alerts.append(Alert(
                    id=f"trend_{marker}_rising",
                    level="warning",
                    category="lab_trend",
                    message=f"{marker} 连续上升：{last3[0]} → {last3[-1]}",
                    action="建议复查影像",
                ))
    return alerts

def assess_gi_bleeding_risk(profile: PatientProfile) -> List[Alert]:
    """评估消化道出血风险"""
    alerts = []
    hgb_data = profile.lab_tests.blood_routine.get("HGB", {})
    trend = hgb_data.get("trend", [])
    if trend:
        latest_hgb = trend[-1].get("value", 100)
        if latest_hgb < 90:
            alerts.append(Alert(
                id="complication_gi_bleeding",
                level="critical" if latest_hgb < 60 else "warning",
                category="complication",
                message=f"消化道出血风险：血红蛋白 {latest_hgb} g/L（{'重度' if latest_hgb < 60 else '中度'}贫血）",
                action="立即就医排查出血原因",
            ))
    return alerts

def assess_biliary_obstruction(profile: PatientProfile) -> List[Alert]:
    """评估胆道梗阻风险"""
    alerts = []
    alp_data = profile.lab_tests.liver_kidney.get("ALP", {})
    ggt_data = profile.lab_tests.liver_kidney.get("GGT", {})
    alp_trend = alp_data.get("trend", [])
    ggt_trend = ggt_data.get("trend", [])
    if alp_trend:
        latest_alp = alp_trend[-1].get("value", 0)
        if latest_alp > 300:
            alerts.append(Alert(
                id="complication_biliary",
                level="warning",
                category="complication",
                message=f"胆道梗阻风险：ALP {latest_alp} U/L（显著升高）",
                action="建议超声/CT 排查胆道梗阻",
            ))
    return alerts

def assess_pancreatitis(profile: PatientProfile) -> List[Alert]:
    """评估胰腺炎风险"""
    alerts = []
    amy_data = profile.lab_tests.liver_kidney.get("Amy", {})
    trend = amy_data.get("trend", [])
    if trend:
        latest_amy = trend[-1].get("value", 0)
        if latest_amy > 405:
            alerts.append(Alert(
                id="complication_pancreatitis",
                level="warning",
                category="complication",
                message=f"胰腺炎风险：淀粉酶 {latest_amy} U/L（>正常3倍）",
                action="建议禁食、补液，必要时使用抑制胰酶药物",
            ))
    return alerts

def assess_thrombosis_risk(profile: PatientProfile) -> List[Alert]:
    """评估血栓风险"""
    alerts = []
    dd_data = profile.lab_tests.coagulation.get("D-dimer", {})
    trend = dd_data.get("trend", [])
    if trend:
        latest_dd = trend[-1].get("value", 0)
        if latest_dd > 2.0:
            alerts.append(Alert(
                id="complication_thrombosis",
                level="warning",
                category="complication",
                message=f"血栓高风险：D-二聚体 {latest_dd} mg/L",
                action="建议血管超声排查 DVT，必要时抗凝治疗",
            ))
    return alerts

def assess_complications(profile: PatientProfile) -> List[Alert]:
    """评估 6 大并发症风险"""
    alerts = []
    alerts.extend(assess_gi_bleeding_risk(profile))
    alerts.extend(assess_biliary_obstruction(profile))
    alerts.extend(assess_pancreatitis(profile))
    alerts.extend(assess_thrombosis_risk(profile))
    # 肠梗阻、感染需症状+指标综合判断，暂留接口
    return alerts
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/test_analysis_engine.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add scripts/analysis_engine.py tests/test_analysis_engine.py
git commit -m "feat: add analysis engine for critical values and 6 complications"
```

---

### Task 3.5: 支持治疗数据提取（Supportive Care Extractor）

**Files:**
- Create: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/scripts/supportive_care.py`
- Test: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/tests/test_supportive_care.py`

**Interfaces:**
- Consumes: `PatientProfile` + MinerU .md texts
- Produces: 填充 `supportive_care` 字段

**Note:** 此任务依赖 Task 2（Extractor），可并行于 Task 3

- [ ] **Step 1: 写失败的测试**

```python
def test_extract_nutrition_markers():
    from scripts.supportive_care import extract_nutrition_markers
    text = "白蛋白 35.4 g/L (参考值 35-50)\n血红蛋白 131 g/L"
    result = extract_nutrition_markers(text, "test.png")
    assert result["albumin"]["value"] == 35.4
    assert result["hemoglobin"]["value"] == 131

def test_assess_complication_gi_bleeding():
    from scripts.supportive_care import assess_gi_bleeding
    profile = create_profile_with_hgb(85)
    alerts = assess_gi_bleeding(profile)
    assert len(alerts) > 0
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/test_supportive_care.py -v
# Expected: FAIL
```

- [ ] **Step 3: 实现支持治疗提取器**

```python
# scripts/supportive_care.py
import re
from typing import Dict, Any, List
from .patient_profile import PatientProfile, Alert, Complication

# 营养指标模式
NUTRITION_PATTERNS = {
    "albumin": (r"白蛋白[^\d]*(\d+\.?\d*)\s*g/L", "g/L", 35, 50),
    "prealbumin": (r"前白蛋白[^\d]*(\d+\.?\d*)\s*mg/L", "mg/L", 180, 360),
    "hemoglobin": (r"血红蛋白[^\d]*(\d+\.?\d*)\s*g/L", "g/L", 130, 175),
    "total_protein": (r"总蛋白[^\d]*(\d+\.?\d*)\s*g/L", "g/L", 65, 85),
    "glucose": (r"空腹血糖[^\d]*(\d+\.?\d*)\s*mmol/L", "mmol/L", 3.9, 6.1),
    "cholesterol": (r"总胆固醇[^\d]*(\d+\.?\d*)\s*mmol/L", "mmol/L", 3.0, 5.7),
    "triglyceride": (r"甘油三酯[^\d]*(\d+\.?\d*)\s*mmol/L", "mmol/L", 0.56, 1.7),
}

def extract_nutrition_markers(text: str, source_file: str) -> Dict[str, Any]:
    """从文本提取营养指标"""
    results = {}
    for name, (pattern, unit, ref_low, ref_high) in NUTRITION_PATTERNS.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            value = float(m.group(1))
            flag = "↑" if value > ref_high else "↓" if value < ref_low else "正常"
            results[name] = {
                "value": value,
                "unit": unit,
                "ref_range": {"low": ref_low, "high": ref_high},
                "flag": flag,
                "source": source_file,
            }
    return results

def assess_gi_bleeding(profile: PatientProfile) -> List[Alert]:
    """评估消化道出血风险"""
    alerts = []
    hgb = profile.lab_tests.blood_routine.get("hemoglobin", {})
    trend = hgb.get("trend", [])
    if trend:
        latest = trend[-1].get("value", 100)
        if latest < 60:
            alerts.append(Alert(
                id="complication_gi_bleeding_severe",
                level="critical",
                category="complication",
                message=f"消化道出血重度风险：血红蛋白 {latest} g/L",
                action="立即就医",
            ))
        elif latest < 90:
            alerts.append(Alert(
                id="complication_gi_bleeding_moderate",
                level="warning",
                category="complication",
                message=f"消化道出血中度风险：血红蛋白 {latest} g/L",
                action="建议排查出血原因",
            ))
    return alerts

def assess_biliary_obstruction(profile: PatientProfile) -> List[Alert]:
    """评估胆道梗阻风险"""
    alerts = []
    alp = profile.lab_tests.liver_kidney.get("ALP", {})
    ggt = profile.lab_tests.liver_kidney.get("GGT", {})
    alp_trend = alp.get("trend", [])
    ggt_trend = ggt.get("trend", [])
    if alp_trend:
        latest_alp = alp_trend[-1].get("value", 0)
        if latest_alp > 300:
            alerts.append(Alert(
                id="complication_biliary",
                level="warning",
                category="complication",
                message=f"胆道梗阻风险：ALP {latest_alp} U/L（显著升高）",
                action="建议超声/CT 排查",
            ))
    return alerts

def assess_pancreatitis(profile: PatientProfile) -> List[Alert]:
    """评估胰腺炎风险"""
    alerts = []
    amy = profile.lab_tests.liver_kidney.get("amylase", {})
    trend = amy.get("trend", [])
    if trend:
        latest = trend[-1].get("value", 0)
        if latest > 405:
            alerts.append(Alert(
                id="complication_pancreatitis",
                level="warning",
                category="complication",
                message=f"胰腺炎风险：淀粉酶 {latest} U/L（>正常3倍）",
                action="建议禁食、补液",
            ))
    return alerts

def assess_infection(profile: PatientProfile) -> List[Alert]:
    """评估感染风险"""
    alerts = []
    pct = profile.lab_tests.liver_kidney.get("PCT", {})
    crp = profile.lab_tests.liver_kidney.get("CRP", {})
    pct_trend = pct.get("trend", [])
    crp_trend = crp.get("trend", [])
    if pct_trend:
        latest_pct = pct_trend[-1].get("value", 0)
        if latest_pct > 0.5:
            alerts.append(Alert(
                id="complication_infection",
                level="warning",
                category="complication",
                message=f"感染风险：PCT {latest_pct} ng/ml（>0.5 提示细菌感染）",
                action="建议血培养 + 经验性抗生素",
            ))
    return alerts

def assess_thrombosis(profile: PatientProfile) -> List[Alert]:
    """评估血栓风险"""
    alerts = []
    dd = profile.lab_tests.coagulation.get("D-dimer", {})
    trend = dd.get("trend", [])
    if trend:
        latest_dd = trend[-1].get("value", 0)
        if latest_dd > 2.0:
            alerts.append(Alert(
                id="complication_thrombosis",
                level="warning",
                category="complication",
                message=f"血栓高风险：D-二聚体 {latest_dd} mg/L",
                action="建议血管超声排查 DVT",
            ))
    return alerts

def build_supportive_care(profile: PatientProfile) -> Dict[str, Any]:
    """构建 supportive_care 对象"""
    return {
        "nutrition": {
            "assessment": {
                "weight_kg": profile.demographics.weight_kg,
                "height_cm": profile.demographics.height_cm,
                "bmi": profile.demographics.bmi,
            },
            "biochemical_markers": extract_nutrition_markers(
                " ".join(str(getattr(profile, f, "")) for f in profile.__dict__),
                profile.data_sources.file_registry[0]["original_name"] if profile.data_sources.file_registry else ""
            ),
        },
        "complications": {
            "gi_bleeding": Complication(
                name="消化道出血",
                risk_level="low",
                monitoring_indicators={},
                symptoms=["黑便", "呕血", "头晕"],
            ),
            "biliary_obstruction": Complication(
                name="胆道梗阻",
                risk_level="medium",
                monitoring_indicators={},
                symptoms=["黄疸", "皮肤瘙痒"],
            ),
            # ... 其他并发症
        },
        "psychological": {
            "screenings": [],
            "tools": {},
            "concerns": [],
            "recommendations": [],
        },
    }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/test_supportive_care.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add scripts/supportive_care.py tests/test_supportive_care.py
git commit -m "feat: add supportive care extractor for nutrition and 6 complications"
```

**Files:**
- Create: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/scripts/recommendation_engine.py`
- Test: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/tests/test_recommendation_engine.py`

**Interfaces:**
- Consumes: `PatientProfile` + `List[Alert]`
- Produces: `Dict[str, List[Recommendation]]`

- [ ] **Step 1: 写失败的测试**

```python
def test_nutrition_recommendation():
    from scripts.recommendation_engine import generate_recommendations
    profile = create_test_profile_with_albumin(35.4)
    recs = generate_recommendations(profile, [])
    assert any("蛋白质" in r.message for r in recs["immediate"])
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/test_recommendation_engine.py::test_nutrition_recommendation -v
# Expected: FAIL
```

- [ ] **Step 3: 实现建议引擎**

```python
# scripts/recommendation_engine.py
from typing import List, Dict, Any
from .patient_profile import PatientProfile, Alert, Recommendation

KNOWLEDGE_BASE = {
    "low_albumin": {
        "condition": lambda p: p.supportive_care.nutrition and p.supportive_care.nutrition.albumin and p.supportive_care.nutrition.albumin.get("value", 100) < 40,
        "recommendations": [
            Recommendation(
                priority="high",
                category="nutrition",
                message="白蛋白偏低，建议增加蛋白质摄入（鸡蛋、牛奶、鱼肉）",
                based_on="albumin_trend"
            )
        ]
    },
    "ca199_rising": {
        "condition": lambda p: any(t.get("flag") == "↑" for t in p.lab_tests.tumor_markers.get("CA199", {}).get("trend", [])[-3:]),
        "recommendations": [
            Recommendation(
                priority="high",
                category="follow_up",
                message="CA199 近期上升，建议复查影像",
                based_on="lab_trend"
            )
        ]
    },
    # 更多规则...
}

def generate_recommendations(profile: PatientProfile, alerts: List[Alert]) -> Dict[str, List[Recommendation]]:
    recs = {"immediate": [], "next_visit": [], "lifestyle": []}
    for rule_name, rule in KNOWLEDGE_BASE.items():
        if rule["condition"](profile):
            for r in rule["recommendations"]:
                recs[r.priority].append(r)
    return recs
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/test_recommendation_engine.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add scripts/recommendation_engine.py tests/test_recommendation_engine.py
git commit -m "feat: add recommendation engine"
```

---

### Task 4: 建议引擎（Recommendation Engine）

**Files:**
- Create: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/scripts/recommendation_engine.py`
- Test: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/tests/test_recommendation_engine.py`

**Interfaces:**
- Consumes: `PatientProfile` + `List[Alert]`
- Produces: `Dict[str, List[Recommendation]]`

- [ ] **Step 1: 写失败的测试**

```python
def test_nutrition_recommendation():
    from scripts.recommendation_engine import generate_recommendations
    profile = create_test_profile_with_albumin(35.4)
    recs = generate_recommendations(profile, [])
    assert any("蛋白质" in r.message for r in recs["immediate"])
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/test_recommendation_engine.py::test_nutrition_recommendation -v
# Expected: FAIL
```

- [ ] **Step 3: 实现建议引擎**

```python
# scripts/recommendation_engine.py
from typing import List, Dict, Any
from .patient_profile import PatientProfile, Alert, Recommendation

KNOWLEDGE_BASE = {
    "low_albumin": {
        "condition": lambda p: p.supportive_care.nutrition and p.supportive_care.nutrition.albumin and p.supportive_care.nutrition.albumin.get("value", 100) < 40,
        "recommendations": [
            Recommendation(
                priority="high",
                category="nutrition",
                message="白蛋白偏低，建议增加蛋白质摄入（鸡蛋、牛奶、鱼肉）",
                based_on="albumin_trend"
            )
        ]
    },
    "ca199_rising": {
        "condition": lambda p: any(t.get("flag") == "↑" for t in p.lab_tests.tumor_markers.get("CA199", {}).get("trend", [])[-3:]),
        "recommendations": [
            Recommendation(
                priority="high",
                category="follow_up",
                message="CA199 近期上升，建议复查影像",
                based_on="lab_trend"
            )
        ]
    },
    # 更多规则...
}

def generate_recommendations(profile: PatientProfile, alerts: List[Alert]) -> Dict[str, List[Recommendation]]:
    recs = {"immediate": [], "next_visit": [], "lifestyle": []}
    for rule_name, rule in KNOWLEDGE_BASE.items():
        if rule["condition"](profile):
            for r in rule["recommendations"]:
                recs[r.priority].append(r)
    return recs
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/test_recommendation_engine.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add scripts/recommendation_engine.py tests/test_recommendation_engine.py
git commit -m "feat: add recommendation engine"
```

---

### Task 5: 医护版渲染器（Clinical View）

**Files:**
- Create: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/scripts/render_clinical.py`
- Test: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/tests/test_render_clinical.py`

**Interfaces:**
- Consumes: `PatientProfile`
- Produces: `clinical_summary.md` + `patient_profile.json`

- [ ] **Step 1: 写失败的测试**

```python
def test_render_json():
    from scripts.render_clinical import render_profile_json
    profile = create_minimal_profile()
    output = render_profile_json(profile, "/tmp/test.json")
    assert Path("/tmp/test.json").exists()
    data = json.load(open("/tmp/test.json"))
    assert data["patient_id"] == "P_TEST"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/test_render_clinical.py::test_render_json -v
# Expected: FAIL
```

- [ ] **Step 3: 实现渲染器**

```python
# scripts/render_clinical.py
import json
from pathlib import Path
from .patient_profile import PatientProfile

def render_profile_json(profile: PatientProfile, output_path: str) -> str:
    """渲染为结构化 JSON"""
    Path(output_path).write_text(
        json.dumps(profile.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    return output_path

def render_clinical_summary(profile: PatientProfile, output_path: str) -> str:
    """渲染为临床摘要 Markdown（基于病历模板）"""
    md = f"""# 临床病历摘要

## 基本信息
- 姓名：{profile.demographics.name}
- 年龄：{profile.demographics.age}岁
- 性别：{profile.demographics.gender}

## 诊断
"""
    for dx in profile.diagnoses:
        md += f"- **{dx.name}**（{dx.confirmed_date}）\n"
    
    md += "\n## 检验指标\n"
    for category in ["tumor_markers", "blood_routine", "liver_kidney"]:
        section = getattr(profile.lab_tests, category, {})
        for name, data in section.items():
            trend = data.get("trend", [])
            if trend:
                latest = trend[-1]
                md += f"- {name}: {latest.get('value')} {latest.get('unit', '')} ({latest.get('flag', '')})\n"
    
    # 更多模板字段...
    
    Path(output_path).write_text(md, encoding="utf-8")
    return output_path
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/test_render_clinical.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add scripts/render_clinical.py tests/test_render_clinical.py
git commit -m "feat: add clinical view renderer"
```

---

### Task 6: 患者版渲染器（Patient View）

**Files:**
- Create: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/scripts/render_patient.py`
- Test: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/tests/test_render_patient.py`

**Interfaces:**
- Consumes: `PatientProfile` + `List[Alert]` + `Dict[str, List[Recommendation]]`
- Produces: `patient_report.md`（易读的 Markdown）

- [ ] **Step 1: 写失败的测试**

```python
def test_render_patient_report():
    from scripts.render_patient import render_patient_report
    profile = create_minimal_profile_with_alerts()
    output = render_patient_report(profile, [], {}, "/tmp/test.md")
    assert Path("/tmp/test.md").exists()
    content = open("/tmp/test.md").read()
    assert "病情档案" in content
```

- [ ] **Step 2: 运行测试确认失败**

```bash
python -m pytest tests/test_render_patient.py::test_render_patient_report -v
# Expected: FAIL
```

- [ ] **Step 3: 实现渲染器**

```python
# scripts/render_patient.py
from pathlib import Path
from .patient_profile import PatientProfile

def render_patient_report(
    profile: PatientProfile,
    alerts: List[Alert],
    recommendations: Dict[str, List[Recommendation]],
    output_path: str
) -> str:
    """渲染患者版报告（基于 case-report-template.md）"""
    
    # 检验指标趋势表
    lab_table = "| 日期 | 指标 | 数值 | 趋势 |\n|------|------|------|------|\n"
    for category in ["tumor_markers", "blood_routine", "liver_kidney"]:
        section = getattr(profile.lab_tests, category, {})
        for name, data in section.items():
            for item in data.get("trend", [])[-5:]:
                lab_table += f"| {item['date']} | {name} | {item['value']} {item.get('unit','')} | {item.get('flag','')} |\n"
    
    # 警示模块
    alerts_md = "## ⚠️ 需要关注\n\n"
    for alert in alerts:
        if alert.level in ("warning", "critical"):
            alerts_md += f"- **{alert.message}**\n  - 建议：{alert.action or '请咨询医生'}\n"
    
    # 建议模块
    recs_md = "## 📝 下次就诊建议\n\n"
    for rec in recommendations.get("next_visit", []):
        recs_md += f"- [ ] {rec.message}\n"
    
    # 支持治疗模块
    support_md = "## 💪 支持治疗\n\n"
    if profile.supportive_care.nutrition:
        support_md += "### 营养支持\n"
        n = profile.supportive_care.nutrition
        support_md += f"- BMI: {n.bmi}\n"
        support_md += f"- 白蛋白: {n.albumin.get('value') if n.albumin else '未检测'}\n"
    
    if profile.supportive_care.complications:
        support_md += "\n### 并发症风险\n"
        for comp in profile.supportive_care.complications.values():
            if comp.risk_level in ("medium", "high", "critical"):
                support_md += f"- **{comp.name}**（{comp.risk_level}）\n"
    
    report = f"""---
patient_id: {profile.patient_id}
schema_version: {profile.schema_version}
---

# 您的病情档案

> ⚠️ **免责声明**：本档案由 AI 辅助工具自动整理生成，仅供参考，不代表医学诊断。

## 📋 基本信息
- 姓名：{profile.demographics.name}
- 年龄：{profile.demographics.age}岁
- 诊断：{profile.diagnoses[0].name if profile.diagnoses else '未填写'}

## 📈 检验指标趋势
{lab_table}

{alerts_md}

{recs_md}

{support_md}

---
*档案生成时间：{profile.data_sources.last_updated}*
"""
    Path(output_path).write_text(report, encoding="utf-8")
    return output_path
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python -m pytest tests/test_render_patient.py -v
# Expected: PASS
```

- [ ] **Step 5: Commit**

```bash
git add scripts/render_patient.py tests/test_render_patient.py
git commit -m "feat: add patient view renderer"
```

---

### Task 7: 端到端集成测试

**Files:**
- Create: `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/tests/test_e2e.py`

**Interfaces:**
- Consumes: 所有前面的模块
- Produces: 完整的 PatientProfile + 报告

- [ ] **Step 1: 写端到端测试**

```python
def test_full_pipeline():
    """测试从 MinerU .md 文件到完整 PatientProfile 的流水线"""
    from scripts.extractor import extract_from_directory
    from scripts.patient_profile import PatientProfile
    from scripts.analysis_engine import check_critical_values
    from scripts.recommendation_engine import generate_recommendations
    from scripts.render_patient import render_patient_report
    
    # 1. 从真实解析文件提取
    profile = extract_from_directory("/Users/qinxiaoqiang/Downloads/report_mess/data/extracted")
    
    # 2. 验证 schema
    assert isinstance(profile, PatientProfile)
    assert profile.patient_id == "P_report_mess"
    
    # 3. 分析引擎
    alerts = check_critical_values(profile)
    assert isinstance(alerts, list)
    
    # 4. 建议引擎
    recs = generate_recommendations(profile, alerts)
    assert "immediate" in recs
    
    # 5. 渲染
    output = "/tmp/test_e2e.md"
    render_patient_report(profile, alerts, recs, output)
    assert Path(output).exists()
    content = open(output).read()
    assert "病情档案" in content
```

- [ ] **Step 2: 运行端到端测试**

```bash
cd /Users/qinxiaoqiang/.agents/skills/patient-record-organizer
python -m pytest tests/test_e2e.py -v
# Expected: PASS（使用真实解析数据）
```

- [ ] **Step 3: 修复任何失败**

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: add end-to-end integration test"
```

---

## 执行顺序

1. **Task 1** (PatientProfile Schema) — 必须先完成
2. **Task 2** (Extractor) — 依赖 Task 1
3. **Task 3** (Analysis Engine) — 依赖 Task 1
4. **Task 4** (Recommendation Engine) — 依赖 Task 1, 3
5. **Task 5** (Clinical Renderer) — 依赖 Task 1
6. **Task 6** (Patient Renderer) — 依赖 Task 1, 3, 4
7. **Task 7** (E2E Test) — 依赖 Task 1-6

## 验证标准

- [ ] 所有 pytest 测试通过
- [ ] PatientProfile 可以序列化为 JSON 并符合 schema v1.0
- [ ] 从真实 MinerU 解析文件提取的 profile 包含 ≥70% 的诊断/用药/检验信息
- [ ] 分析引擎能检测到 CA199 趋势异常
- [ ] 建议引擎能生成营养支持和随访建议
- [ ] 患者版报告可读性评分：包含 ≤3 个医学缩写词（需解释）
