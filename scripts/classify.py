"""
两层分类 + 日期提取（T4）

第一层：规则快速分类（零成本）
  → 关键词匹配（见 references/classification-rules.md）

第二层：LLM 语义分类（成本极低）
  → 对第一层未命中/置信度低的文件，调用 LLM 返回类别名

日期提取：正则兼容
  - 2024-03-15
  - 2024年3月15日
  - 24/03/15
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 规则关键词词库（与 references/classification-rules.md 保持一致）
_RULES: Dict[str, List[str]] = {
    "lab_results": [
        "血常规", "白细胞", "血红蛋白", "血小板", "生化", "肝功能", "ALT", "AST",
        "肾功能", "肌酐", "尿素氮", "血糖", "糖化血红蛋白", "电解质",
        "肿瘤标志物", "CEA", "CA125", "CA199", "AFP", "PSA", "凝血", "INR", "D-二聚体",
    ],
    "imaging": [
        "CT", "MRI", "核磁共振", "超声", "B超", "彩超", "X线", "X-ray",
        "PET-CT", "骨扫描", "内镜", "胃镜", "肠镜", "支气管镜", "造影", "增强", "平扫",
    ],
    "pathology": [
        "病理", "活检", "免疫组化", "基因检测", "突变", "EGFR", "ALK", "ROS1",
        "KRAS", "HER2", "PD-L1", "TMB",
    ],
    "medication": [
        "处方", "用药", "化疗方案", "靶向", "免疫治疗",
        "奥希替尼", "吉非替尼", "信迪利单抗", "帕博利珠单抗", "贝伐珠单抗",
    ],
    "clinical_records": [
        "出院小结", "出院记录", "门诊", "住院", "手术记录", "术中", "术后",
        "治疗小结", "化疗小结", "放疗小结",
    ],
    "basic_info": [
        "主诉", "现病史", "既往史", "过敏史", "家族史", "体格检查",
    ],
}

_CATEGORY_ORDER = [
    "basic_info",
    "lab_results",
    "imaging",
    "pathology",
    "medication",
    "clinical_records",
    "other",
]


def _rule_match(text: str) -> List[str]:
    """第一层：规则匹配，返回命中的类别列表（可能有多个）"""
    hits: List[str] = []
    for category, keywords in _RULES.items():
        for kw in keywords:
            if kw in text:
                hits.append(category)
                break
    return hits


def _extract_dates(text: str) -> List[str]:
    """从文本中提取日期，返回去重后的 ISO 日期列表 YYYY-MM-DD"""
    patterns = [
        r"\d{4}-\d{2}-\d{2}",          # 2024-03-15
        r"\d{4}年\d{1,2}月\d{1,2}日",   # 2024年3月15日
        r"\d{2}/\d{2}/\d{2}",          # 24/03/15
    ]
    results: List[str] = []
    for pat in patterns:
        for m in re.finditer(pat, text):
            s = m.group(0)
            if "年" in s and "月" in s and "日" in s:
                y, rest = s.split("年")
                mo, d = rest.split("月")
                day = d.rstrip("日")
                results.append(f"{y}-{int(mo):02d}-{int(day):02d}")
            elif "/" in s and len(s) == 8:
                y, mo, d = s.split("/")
                y = int(y)
                y = y + 2000 if y < 100 else y
                results.append(f"{y:04d}-{int(mo):02d}-{int(d):02d}")
            else:
                results.append(s)
    # 去重保序
    seen = set()
    out = []
    for d in results:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def classify(
    text: str,
    *,
    llm_client=None,
    max_chars: int = 500,
) -> Tuple[str, Optional[str], float]:
    """对一段文本做分类。

    Returns
    -------
    (primary_category, secondary_categories_json, confidence)
    """
    snippet = text[:max_chars]
    hits = _rule_match(snippet)

    if hits:
        primary = hits[0]
        secondary = hits[1:] if len(hits) > 1 else []
        confidence = 0.95 if not secondary else 0.85
        return primary, json.dumps(secondary, ensure_ascii=False), confidence

    # 第二层：LLM 兜底
    if llm_client is not None:
        try:
            label = llm_classify(snippet, client=llm_client)
            if label in _CATEGORY_ORDER:
                return label, "[]", 0.6
        except Exception as exc:
            logger.warning("LLM 分类失败，回退到 other: %s", exc)

    return "other", "[]", 0.5


def llm_classify(text: str, *, client, model: str = "qwen3-flash") -> str:
    """调用 LLM 返回单一类别名（类别必须在 _CATEGORY_ORDER 中）"""
    prompt = (
        "以下是一份医疗报告的文本片段，请判断它属于哪个类别。"
        "仅返回类别名，不要解释。\n"
        f"文本：\n{text}\n"
        f"可选类别：{', '.join(_CATEGORY_ORDER)}"
    )
    resp = client.chat(model=model, messages=[{"role": "user", "content": prompt}])
    content = resp["choices"][0]["message"]["content"].strip()
    return content


def build_timeline_entry(
    file_path: str,
    primary: str,
    dates: List[str],
    title: Optional[str] = None,
) -> Dict:
    """构造 timeline 条目"""
    return {
        "file": file_path,
        "category": primary,
        "dates": dates,
        "title": title or Path(file_path).name,
    }


def update_categories_summary(manifest: Dict[str, Any]) -> None:
    """根据 manifest["files"] 中每条记录的 category 刷新 categories_summary。

    规则：取 category 的第一段（如 "lab_results.blood_routine" → "lab_results"）作为统计键。
    category 为 None / 空字符串的条目归入 "other"。
    """
    summary: Dict[str, int] = {}
    for fe in (manifest.get("files") or []):
        cat = (fe.get("category") or "other") or "other"
        top = cat.split(".")[0]
        summary[top] = summary.get(top, 0) + 1
    manifest["categories_summary"] = summary
