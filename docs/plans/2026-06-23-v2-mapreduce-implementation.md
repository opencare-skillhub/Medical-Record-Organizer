# PatientProfile v2.0 实现计划（MapReduce 架构升级）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 v1.0 的正则/规则提取链路升级为 MapReduce 三层架构（脱敏 → Map LLM → Shuffle → Reduce LLM），让 LLM 能力最大化、隐私零泄露、细节不丢失。

**Architecture:** 参考 `docs/prd-v2-mapreduce-architecture.md`
1. `desensitize.py` — 脱敏层（本地正则）
2. `map_extract.py` — Map 层（逐文件 LLM + function calling）
3. `shuffle_group.py` — Shuffle 层（本地分组）
4. `reduce_merge.py` — Reduce 层（按类 LLM 跨文档推理）
5. `pipeline_v2.py` — 端到端编排

**Tech Stack:** Python 3.10+, Pydantic v2, qwen3-flash / glm-4-flash（SiliconFlow API）

## Global Constraints

- Python 3.10+，复用 v1.0 的 `patient_profile.py`、`render_clinical.py`、`render_patient.py`
- 所有新脚本放在 `/Users/qinxiaoqiang/.agents/skills/patient-record-organizer/scripts/v2/`
- 测试放在 `tests/v2/`
- **隐私红线**：任何送 LLM 的文本必须先过脱敏层
- **质量门禁**：每 Phase 完成后抽样对比人工标注
- API Key 从 `~/.zshrc` 环境变量读取（`OCR_API_KEY`、`SILICONFLOW_API_KEY`）
- 单文件 LLM 调用必须有重试 + 失败兜底

---

## 文件结构

```
patient-record-organizer/
├── scripts/
│   ├── v1/                          # v1.0 模块（保留）
│   │   ├── extractor.py
│   │   ├── analysis_engine.py
│   │   ├── supportive_care.py
│   │   └── recommendation_engine.py
│   ├── v2/                          # v2.0 新模块
│   │   ├── desensitize.py           # Phase 1
│   │   ├── map_extract.py           # Phase 2
│   │   ├── shuffle_group.py         # Phase 3
│   │   ├── reduce_merge.py          # Phase 4
│   │   └── pipeline_v2.py           # Phase 6
│   ├── patient_profile.py           # 共用（v1.0 + v2.0）
│   ├── render_clinical.py           # 共用
│   └── render_patient.py            # 共用
├── tests/
│   └── v2/
│       ├── test_desensitize.py
│       ├── test_map_extract.py
│       ├── test_shuffle_group.py
│       ├── test_reduce_merge.py
│       └── test_pipeline_v2.py
└── docs/
    ├── prd-v2-mapreduce-architecture.md
    └── plans/
        └── 2026-06-23-v2-mapreduce-implementation.md  # 本计划
```

---

## Phase 1: 脱敏层（P0）

### Task 1.1: 脱敏规则与回填

**Files:**
- Create: `scripts/v2/desensitize.py`
- Test: `tests/v2/test_desensitize.py`

**Interfaces:**
- Consumes: 原始 .md 文本
- Produces: `desensitize(text) -> (sanitized_text, mapping)`、`restore(sanitized, mapping) -> original`

- [ ] **Step 1: 写失败的测试**

```python
# tests/v2/test_desensitize.py
from scripts.v2.desensitize import desensitize, restore

def test_desensitize_name():
    text = "姓名：秦晓强，性别：男，年龄：49"
    sanitized, mapping = desensitize(text)
    assert "[NAME]" in sanitized
    assert "秦晓强" not in sanitized
    assert any("秦晓强" in v for v in mapping.values())

def test_desensitize_phone():
    text = "联系电话：13812345678"
    sanitized, mapping = desensitize(text)
    assert "[PHONE]" in sanitized
    assert "13812345678" not in sanitized

def test_desensitize_id_card():
    text = "身份证号：310101199001011234"
    sanitized, mapping = desensitize(text)
    assert "[ID]" in sanitized
    assert "310101199001011234" not in sanitized

def test_restore_roundtrip():
    text = "患者秦晓强（男，49岁），病历号11493391，电话13812345678"
    sanitized, mapping = desensitize(text)
    restored = restore(sanitized, mapping)
    assert "秦晓强" in restored
    assert "13812345678" in restored

def test_desensitize_medical_record_no():
    text = "门诊号：11493391"
    sanitized, mapping = desensitize(text)
    assert "[MRN]" in sanitized
    assert "11493391" not in sanitized
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/qinxiaoqiang/.agents/skills/patient-record-organizer
python3 -m pytest tests/v2/test_desensitize.py -v
# Expected: FAIL (module not found)
```

- [ ] **Step 3: 实现脱敏层**

```python
# scripts/v2/desensitize.py
import re
from typing import Tuple, Dict

DESENSITIZE_PATTERNS = [
    # 姓名：紧跟性别的 2-4 字汉字
    (r'([\u4e00-\u9fa5]{2,4})(?=\s*[，,]?\s*(男|女))', 'NAME'),
    # 身份证（18位）
    (r'\d{17}[\dXx]', 'ID'),
    # 手机号
    (r'1[3-9]\d{9}', 'PHONE'),
    # 座机
    (r'0\d{2,3}-?\d{7,8}', 'PHONE'),
    # 病历号（6位以上数字紧跟"号/病/门诊/住院"）
    (r'\d{6,}(?=\s*[号]?\s*(病|门诊|住院))', 'MRN'),
    # 邮箱
    (r'[\w.]+@[\w.]+', 'EMAIL'),
    # 地址
    (r'[\u4e00-\u9fa5]{2,}(省|市|区|县|路|街|号|弄|室)\d*', 'ADDR'),
    # 银行卡号
    (r'\d{16,19}', 'CARD'),
]

def desensitize(text: str) -> Tuple[str, Dict[str, str]]:
    """脱敏文本，返回 (脱敏后文本, 映射表)。
    
    映射表格式：{"[PLACEHOLDER]_N": "原始值"}
    """
    mapping = {}
    counters = {}
    
    sanitized = text
    for pattern, label in DESENSITIZE_PATTERNS:
        def replace_match(m):
            original = m.group(0)
            counters[label] = counters.get(label, 0) + 1
            placeholder = f"[{label}_{counters[label]}]"
            mapping[placeholder] = original
            return placeholder
        sanitized = re.sub(pattern, replace_match, sanitized)
    
    return sanitized, mapping

def restore(sanitized: str, mapping: Dict[str, str]) -> str:
    """用映射表把脱敏文本还原为原始文本。"""
    restored = sanitized
    # 按 placeholder 长度降序替换，避免短 placeholder 误匹配长 placeholder
    for placeholder in sorted(mapping.keys(), key=len, reverse=True):
        restored = restored.replace(placeholder, mapping[placeholder])
    return restored

def desensitize_file(input_path: str, output_path: str, mapping_path: str = None) -> Dict[str, str]:
    """脱敏单个文件，返回映射表。"""
    import json
    from pathlib import Path
    
    text = Path(input_path).read_text(encoding="utf-8")
    sanitized, mapping = desensitize(text)
    
    Path(output_path).write_text(sanitized, encoding="utf-8")
    if mapping_path:
        Path(mapping_path).write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    return mapping

def desensitize_directory(input_dir: str, output_dir: str) -> Dict[str, Dict[str, str]]:
    """批量脱敏目录下所有 .md 文件。"""
    import os
    from pathlib import Path
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    all_mappings = {}
    
    for md_file in sorted(Path(input_dir).glob("*.md")):
        out_file = Path(output_dir) / md_file.name
        mapping = desensitize_file(str(md_file), str(out_file))
        all_mappings[md_file.name] = mapping
    
    return all_mappings
```

- [ ] **Step 4: 运行测试确认通过**

```bash
python3 -m pytest tests/v2/test_desensitize.py -v
# Expected: 5 passed
```

- [ ] **Step 5: Commit**

```bash
git add scripts/v2/desensitize.py tests/v2/test_desensitize.py
git commit -m "feat(v2): add desensitization layer with PII patterns and restore"
```

### Task 1.2: 脱敏质量验收（真实数据）

- [ ] **对 110 份真实文件跑脱敏**

```bash
cd /Users/qinxiaoqiang/.agents/skills/patient-record-organizer
python3 -c "
from scripts.v2.desensitize import desensitize_directory
m = desensitize_directory(
    '/Users/qinxiaoqiang/Downloads/report_mess/data/extracted',
    '/tmp/sanitized_test'
)
print(f'脱敏 {len(m)} 个文件')
import json
print(json.dumps({k: {kk: vv[:20]+'...' for kk, vv in v.items()} for k, v in list(m.items())[:3]}, ensure_ascii=False, indent=2))
"
```

- [ ] **抽检 20 份，确认 0 处隐私残留**

```bash
# 用 grep 检查脱敏后是否还有常见隐私模式
grep -rE "1[3-9]\d{9}|[\u4e00-\u9fa5]{2,4}(?=.{0,3}男|女)|\d{17}[\dXx]" /tmp/sanitized_test/ | head -20
# Expected: 0 matches
```

- [ ] **验证回填准确率**

```bash
python3 -c "
from pathlib import Path
from scripts.v2.desensitize import desensitize, restore
import random

files = list(Path('/Users/qinxiaoqiang/Downloads/report_mess/data/extracted').glob('*.md'))
samples = random.sample(files, min(10, len(files)))
roundtrip_ok = 0
for f in samples:
    text = f.read_text(encoding='utf-8')
    sanitized, mapping = desensitize(text)
    restored = restore(sanitized, mapping)
    if restored == text:
        roundtrip_ok += 1
print(f'回填准确率：{roundtrip_ok}/{len(samples)}')
# Expected: 10/10
"
```

---

## Phase 2: Map 层（P0）

### Task 2.1: LLM 调用封装

**Files:**
- Create: `scripts/v2/llm_client.py`
- Test: `tests/v2/test_llm_client.py`

**Interfaces:**
- Produces: `call_llm_with_schema(messages, schema, model) -> dict`

- [ ] **Step 1: 写失败的测试**

```python
# tests/v2/test_llm_client.py
from scripts.v2.llm_client import call_llm_with_schema

def test_llm_returns_structured_json():
    messages = [{"role": "user", "content": "CA199: 342 U/ml（参考值 0-37）"}]
    schema = {
        "type": "object",
        "properties": {
            "lab_values": {"type": "array"}
        }
    }
    result = call_llm_with_schema(messages, schema, model="qwen3-flash")
    assert isinstance(result, dict)
    assert "lab_values" in result
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现 LLM 客户端（支持 function calling 和 JSON mode）**

```python
# scripts/v2/llm_client.py
import os, json, requests
from typing import Dict, Any, List

API_KEY = os.environ.get("OCR_API_KEY", "") or os.environ.get("SILICONFLOW_API_KEY", "")
API_BASE = os.environ.get("OCR_BASE_URL", "https://api.siliconflow.cn/v1").rstrip("/")

def call_llm_with_schema(
    messages: List[Dict],
    schema: Dict[str, Any],
    model: str = "qwen3-flash",
    temperature: float = 0.1,
    max_tokens: int = 2000,
    timeout: int = 30,
) -> Dict[str, Any]:
    """调用 LLM 并用 JSON schema 约束输出。"""
    resp = requests.post(
        f"{API_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)

def call_llm_with_retry(
    messages: List[Dict],
    schema: Dict[str, Any],
    model: str = "qwen3-flash",
    max_retries: int = 3,
) -> Dict[str, Any]:
    """带重试的 LLM 调用，失败时降级到备选模型。"""
    fallback_models = [model, "glm-4-flash", "qwen3-flash"]
    last_error = None
    for m in fallback_models[:max_retries]:
        try:
            return call_llm_with_schema(messages, schema, model=m)
        except Exception as e:
            last_error = e
            continue
    raise RuntimeError(f"LLM 调用失败（{max_retries}次重试）：{last_error}")
```

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: Commit**

```bash
git add scripts/v2/llm_client.py tests/v2/test_llm_client.py
git commit -m "feat(v2): add LLM client with JSON schema and retry"
```

### Task 2.2: Map 层单文件提取

**Files:**
- Create: `scripts/v2/map_extract.py`
- Test: `tests/v2/test_map_extract.py`

**Interfaces:**
- Consumes: 脱敏后 .md 文本
- Produces: `extract_single(sanitized_text, filename) -> ExtractResult`

- [ ] **Step 1: 写失败的测试**

```python
# tests/v2/test_map_extract.py
from scripts.v2.map_extract import extract_single

def test_extract_lab_report():
    text = """
    报告日期：2025-03-31
    癌胚抗原（CEA）：5.51 ng/ml（参考值 0-5）
    糖类抗原199（CA199）：16.6 U/ml（参考值 0-37）
    """
    result = extract_single(text, "lab_report.md")
    assert result["report_type"] == "lab"
    assert result["report_date"] == "2025-03-31"
    assert any(v["name"] in ("CEA", "CA199") for v in result["lab_values"])

def test_extract_invoice_as_noise():
    text = "门诊收费发票 金额：¥350.00 收款员：张三"
    result = extract_single(text, "invoice.jpg.md")
    assert result["report_type"] == "other"
    assert len(result.get("noise", [])) > 0
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现 Map 层**

```python
# scripts/v2/map_extract.py
from typing import Dict, Any
from .llm_client import call_llm_with_retry

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "report_type": {"type": "string", "enum": ["lab", "imaging", "pathology", "medication", "clinical", "other"]},
        "report_date": {"type": "string"},
        "confidence": {"type": "number"},
        "diagnoses": {"type": "array"},
        "lab_values": {"type": "array"},
        "medications": {"type": "array"},
        "findings": {"type": "array"},
        "procedures": {"type": "array"},
        "noise": {"type": "array"},
    },
    "required": ["report_type", "confidence"],
}

SYSTEM_PROMPT = """你是一名资深病案整理员。下面是一份医疗文件（已脱敏）。
请提取结构化信息。注意：
1. report_type：检验报告选 lab，CT/MRI/超声选 imaging，病理/基因选 pathology，
   处方/医嘱选 medication，出院/门诊/手术记录选 clinical。
2. 非医疗文件（发票、收据、聊天截图）report_type=other，noise 字段标明原因。
3. 数值必须带单位和参考范围（如报告自带）。
4. 某字段不存在则返回空数组，不要编造。
5. confidence 反映分类把握（0-1）。"""

def extract_single(sanitized_text: str, filename: str, model: str = "qwen3-flash") -> Dict[str, Any]:
    """单文件 LLM 提取。"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"文件名：{filename}\n\n内容：\n{sanitized_text[:3000]}"},
    ]
    result = call_llm_with_retry(messages, EXTRACT_SCHEMA, model=model)
    result["_source_file"] = filename
    return result

def extract_batch(sanitized_dir: str, output_dir: str, max_workers: int = 4) -> list:
    """批量提取目录下所有脱敏文件。"""
    import json, os
    from pathlib import Path
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    results = []
    
    md_files = sorted(Path(sanitized_dir).glob("*.md"))
    
    def process_one(md_file):
        out_path = Path(output_dir) / f"{md_file.stem}.json"
        if out_path.exists():
            return json.loads(out_path.read_text(encoding="utf-8"))
        text = md_file.read_text(encoding="utf-8")
        try:
            result = extract_single(text, md_file.name)
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            return result
        except Exception as e:
            return {"report_type": "error", "error": str(e), "_source_file": md_file.name}
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_one, f) for f in md_files]
        for future in as_completed(futures):
            results.append(future.result())
    
    return results
```

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: Commit**

```bash
git add scripts/v2/map_extract.py tests/v2/test_map_extract.py
git commit -m "feat(v2): add Map layer with LLM single-file extraction"
```

### Task 2.3: Map 层质量验收（5 份真实文件 PoC）

- [ ] **选 5 份有代表性的文件做 PoC**

```bash
python3 -c "
from scripts.v2.desensitize import desensitize
from scripts.v2.map_extract import extract_single
from pathlib import Path

# 选 5 份：1份检验、1份影像、1份处方、1份病情概述、1份发票
samples = [
    'ca199.xlsx.md',  # 检验
    'IMG_1103.jpg.md',  # 影像
    '2025-03-31_处方用药.JPG.md',  # 处方
    '01_病情概述_页面_01.md',  # 病情
    # 找一份发票
]

for fname in samples:
    p = Path(f'/Users/qinxiaoqiang/Downloads/report_mess/data/extracted/{fname}')
    if not p.exists():
        print(f'跳过（不存在）：{fname}')
        continue
    text = p.read_text(encoding='utf-8')
    sanitized, _ = desensitize(text)
    result = extract_single(sanitized, fname)
    print(f'--- {fname} ---')
    print(f'  type: {result.get(\"report_type\")}, confidence: {result.get(\"confidence\")}')
    print(f'  lab_values: {len(result.get(\"lab_values\", []))}')
    print(f'  noise: {result.get(\"noise\", [])}')
"
```

- [ ] **对比人工标注，验证质量门禁（report_type 准确率 ≥ 90%）**

---

## Phase 3: Shuffle 层（P1）

### Task 3.1: 分组与趋势合并

**Files:**
- Create: `scripts/v2/shuffle_group.py`
- Test: `tests/v2/test_shuffle_group.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/v2/test_shuffle_group.py
from scripts.v2.shuffle_group import group_by_type, merge_lab_trends

def test_group_by_type():
    extracted = [
        {"report_type": "lab", "report_date": "2025-01-01", "lab_values": [{"name": "CA199", "value": 100}]},
        {"report_type": "lab", "report_date": "2025-02-01", "lab_values": [{"name": "CA199", "value": 150}]},
        {"report_type": "imaging", "report_date": "2025-01-15"},
    ]
    groups = group_by_type(extracted)
    assert len(groups["lab"]) == 2
    assert len(groups["imaging"]) == 1

def test_merge_lab_trends():
    lab_group = [
        {"report_date": "2025-01-01", "lab_values": [{"name": "CA199", "value": 100, "unit": "U/ml"}]},
        {"report_date": "2025-02-01", "lab_values": [{"name": "CA199", "value": 150, "unit": "U/ml"}]},
    ]
    trends = merge_lab_trends(lab_group)
    assert "CA199" in trends
    assert len(trends["CA199"]["trend"]) == 2
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现 Shuffle 层**

```python
# scripts/v2/shuffle_group.py
from typing import Dict, List, Any
from collections import defaultdict

def group_by_type(extracted: List[Dict]) -> Dict[str, List[Dict]]:
    """按 report_type 分组，每组按 date 排序。"""
    groups = defaultdict(list)
    for item in extracted:
        rt = item.get("report_type", "other")
        groups[rt].append(item)
    for rt in groups:
        groups[rt].sort(key=lambda x: x.get("report_date", ""))
    return dict(groups)

def merge_lab_trends(lab_group: List[Dict]) -> Dict[str, Any]:
    """把多份检验报告的同一指标合并成时间序列。"""
    trends = defaultdict(lambda: {"unit": "", "ref_range": None, "trend": []})
    
    for report in lab_group:
        date = report.get("report_date", "")
        for lv in report.get("lab_values", []):
            name = lv.get("name", "")
            if not name:
                continue
            trends[name]["unit"] = lv.get("unit", trends[name]["unit"])
            ref = lv.get("ref_low"), lv.get("ref_high")
            if ref[0] is not None:
                trends[name]["ref_range"] = ref
            trends[name]["trend"].append({
                "date": date,
                "value": lv.get("value"),
                "abnormal": lv.get("abnormal"),
                "source": report.get("_source_file", ""),
            })
    
    # 每个指标按 date 排序
    for name in trends:
        trends[name]["trend"].sort(key=lambda x: x["date"])
    
    return dict(trends)
```

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: Commit**

```bash
git add scripts/v2/shuffle_group.py tests/v2/test_shuffle_group.py
git commit -m "feat(v2): add Shuffle layer for grouping and trend merging"
```

---

## Phase 4: Reduce 层（P1）

### Task 4.1: 检验组 Reduce

**Files:**
- Create: `scripts/v2/reduce_merge.py`（先实现 lab 部分）
- Test: `tests/v2/test_reduce_merge.py`

- [ ] **Step 1: 写失败的测试**

```python
# tests/v2/test_reduce_merge.py
from scripts.v2.reduce_merge import reduce_lab_trends

def test_reduce_lab_detects_rising_trend():
    trends = {
        "CA199": {
            "unit": "U/ml",
            "ref_range": (0, 37),
            "trend": [
                {"date": "2025-01-01", "value": 100},
                {"date": "2025-02-01", "value": 150},
                {"date": "2025-03-01", "value": 200},
            ]
        }
    }
    result = reduce_lab_trends(trends)
    assert result["CA199"]["trend_summary"] in ("上升", "持续上升")
    assert result["CA199"]["alert_level"] in ("warning", "critical")
```

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现检验组 Reduce**

```python
# scripts/v2/reduce_merge.py
from typing import Dict, Any
from .llm_client import call_llm_with_retry
import json

LAB_REDUCE_PROMPT = """你是临床检验分析师。以下是患者某检验指标在多次随访中的数值（已脱敏）：

指标：{indicator}
单位：{unit}
参考范围：{ref_low} - {ref_high}
趋势数据：
{trend_json}

请判断：
1. trend_summary：整体趋势（持续下降/上升/波动/稳定）
2. alert_level：预警级别（normal/warning/critical）
3. clinical_inference：临床意义推断（治疗反应、病情变化）
4. consecutive_rises：连续上升次数（0 表示无）

输出 JSON。"""

def reduce_lab_trends(trends: Dict[str, Any]) -> Dict[str, Any]:
    """对每个检验指标做 LLM 趋势分析。"""
    results = {}
    for indicator, data in trends.items():
        ref = data.get("ref_range") or (None, None)
        messages = [{
            "role": "user",
            "content": LAB_REDUCE_PROMPT.format(
                indicator=indicator,
                unit=data.get("unit", ""),
                ref_low=ref[0] or "未知",
                ref_high=ref[1] or "未知",
                trend_json=json.dumps(data["trend"], ensure_ascii=False, indent=2),
            )
        }]
        schema = {
            "type": "object",
            "properties": {
                "trend_summary": {"type": "string"},
                "alert_level": {"type": "string"},
                "clinical_inference": {"type": "string"},
                "consecutive_rises": {"type": "integer"},
            }
        }
        try:
            result = call_llm_with_retry(messages, schema, model="qwen3-flash")
            results[indicator] = result
        except Exception as e:
            results[indicator] = {"error": str(e)}
    return results

def reduce_medication_history(med_group: list) -> Dict[str, Any]:
    """重建化疗周期时间线（Task 4.2 实现）。"""
    raise NotImplementedError

def reduce_imaging_narrative(imaging_group: list) -> Dict[str, Any]:
    """生成病灶演变叙事（Task 4.3 实现）。"""
    raise NotImplementedError
```

- [ ] **Step 4: 运行测试确认通过**

- [ ] **Step 5: Commit**

```bash
git add scripts/v2/reduce_merge.py tests/v2/test_reduce_merge.py
git commit -m "feat(v2): add Reduce layer for lab trend analysis"
```

### Task 4.2: 用药组 Reduce

- [ ] **实现 `reduce_medication_history`：重建化疗周期**

```python
MED_REDUCE_PROMPT = """你是肿瘤化疗药师。以下是患者所有处方/医嘱记录（已脱敏，按时间排序）：

{medications_json}

请重建完整的化疗时间线：
1. regimens：识别的化疗方案（如 AG 方案）
2. cycles：每周期起止日期、用药、剂量、周期编号
3. response_assessments：疗效评估节点（PR/SD/PD）
4. toxicities：副作用记录

输出 JSON。"""
```

### Task 4.3: 影像组 Reduce

- [ ] **实现 `reduce_imaging_narrative`：病灶演变叙事**

```python
IMAGING_REDUCE_PROMPT = """你是影像科医生。以下是患者所有 CT/MRI 报告（已脱敏，按时间排序）：

{imaging_json}

请生成病灶演变的连贯叙事：
1. primary_lesion_timeline：原发灶变化（大小、密度、强化）
2. metastasis_timeline：转移灶变化（淋巴结、肝、腹膜）
3. overall_response：总体疗效评估

输出 JSON。"""
```

---

## Phase 5: 修复 v1.0 bug + 接 Reduce 输出

### Task 5.1: 修复 supportive_care bug

- [ ] **修复 `supportive_care.build_supportive_care`：接收 Map 层 lab_values 而非 `str(profile.__dict__)`**

### Task 5.2: PatientProfile 组装

- [ ] **写 `pipeline_v2.py`：把 Reduce 输出组装成 PatientProfile**

---

## Phase 6: 端到端联调

### Task 6.1: pipeline_v2.py 编排

**Files:**
- Create: `scripts/v2/pipeline_v2.py`
- Test: `tests/v2/test_pipeline_v2.py`

- [ ] **实现完整流水线编排**

```python
# scripts/v2/pipeline_v2.py
def run_pipeline(extracted_dir: str, output_dir: str):
    """端到端流水线：脱敏 → Map → Shuffle → Reduce → Profile → 渲染"""
    # 1. 脱敏
    sanitized_dir = f"{output_dir}/sanitized"
    mappings = desensitize_directory(extracted_dir, sanitized_dir)
    
    # 2. Map
    map_dir = f"{output_dir}/map"
    extracted = extract_batch(sanitized_dir, map_dir)
    
    # 3. Shuffle
    groups = group_by_type(extracted)
    lab_trends = merge_lab_trends(groups.get("lab", []))
    
    # 4. Reduce
    lab_analysis = reduce_lab_trends(lab_trends)
    med_timeline = reduce_medication_history(groups.get("medication", []))
    imaging_narrative = reduce_imaging_narrative(groups.get("imaging", []))
    
    # 5. Profile 组装
    profile = assemble_profile(lab_trends, lab_analysis, med_timeline, imaging_narrative, ...)
    
    # 6. 渲染
    render_clinical_summary(profile, f"{output_dir}/clinical_summary.md")
    render_patient_report(profile, alerts, recs, f"{output_dir}/patient_report.md")
    
    return profile
```

### Task 6.2: 真实数据验收

- [ ] **对 110 份真实文件跑全流程**

```bash
python3 -c "
from scripts.v2.pipeline_v2 import run_pipeline
profile = run_pipeline(
    '/Users/qinxiaoqiang/Downloads/report_mess/data/extracted',
    '/Users/qinxiaoqiang/patients/P_report_mess/output_v2'
)
print(f'Profile: {profile.patient_id}')
print(f'Diagnoses: {len(profile.diagnoses)}')
print(f'Lab indicators: {sum(len(v.get(\"trend\", [])) for v in profile.lab_tests.tumor_markers.values())}')
"
```

- [ ] **对比人工整理，验证关键信息覆盖率 ≥ 80%**

---

## Phase 7: 优化（P2，按需）

- [ ] 本地模型选项（Qwen 本地部署）
- [ ] 成本监控仪表盘
- [ ] 失败文件人工复核界面
- [ ] 增量更新（只处理新文件）

---

## 执行顺序与依赖

```
Phase 1 (脱敏) ──→ Phase 2 (Map) ──→ Phase 3 (Shuffle) ──→ Phase 4 (Reduce)
                                                                    │
                                                                    ▼
                    Phase 5 (修复+组装) ←──────────────────────────┘
                          │
                          ▼
                    Phase 6 (端到端)
                          │
                          ▼
                    Phase 7 (优化)
```

## 验证标准

- [ ] 所有 pytest 测试通过
- [ ] 脱敏后 0 处隐私残留（grep 验证）
- [ ] Map 层 report_type 准确率 ≥ 90%
- [ ] Reduce 层 CA199 趋势判断与人工一致
- [ ] 端到端关键信息覆盖率 ≥ 80%
- [ ] 110 文件全流程 ≤ 30 分钟，成本 ≤ ¥10
