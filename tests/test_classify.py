"""
T4 验收测试：scripts/classify.py

覆盖：
  ① "血常规"命中 lab_results
  ② "CT报告"命中 imaging
  ③ LLM 兜底分支（mock 返回）
  ④ 三种日期格式都能提取
  ⑤ 多分类时主分类正确
"""
from __future__ import annotations

import json
import pytest

from scripts.classify import (
    _rule_match,
    _extract_dates,
    classify,
    build_timeline_entry,
    _CATEGORY_ORDER,
)


# ① "血常规"命中 lab_results
def test_rule_match_blood_routine():
    cats = _rule_match("患者血常规检查：白细胞 6.5，血红蛋白 132，血小板 210")
    assert "lab_results" in cats


# ② "CT报告"命中 imaging
def test_rule_match_ct():
    cats = _rule_match("胸部CT报告：右肺上叶结节 2.1cm")
    assert "imaging" in cats


# ④ 三种日期格式都能提取
@pytest.mark.parametrize("text,expected", [
    ("检查日期：2024-03-15", ["2024-03-15"]),
    ("报告日期：2024年3月15日", ["2024-03-15"]),
    ("记录时间 24/03/15", ["2024-03-15"]),
    ("2024-03-15 与 2024年6月1日", ["2024-03-15", "2024-06-01"]),
])
def test_extract_dates(text, expected):
    assert _extract_dates(text) == expected


# ⑤ 多分类时主分类正确（basic_info 不应作为主分类，除非它是唯一匹配）
def test_multi_category_primary():
    text = "患者主诉咳嗽，行胸部CT检查，血常规正常"
    primary, secondary_json, confidence = classify(text)
    # basic_info 被排除在主分类之外，lab_results 成为主分类
    assert primary == "lab_results"
    assert confidence >= 0.85
    secondary = json.loads(secondary_json)
    assert "basic_info" in secondary or "imaging" in secondary


# ③ LLM 兜底分支（mock 返回）
def test_classify_llm_fallback(monkeypatch):
    class FakeClient:
        def chat(self, model, messages):
            return {"choices": [{"message": {"content": "pathology"}}]}

    primary, _, confidence = classify("这是一段无法被规则匹配的文本", llm_client=FakeClient())
    assert primary == "pathology"
    assert confidence == 0.6


# 无关键词时回退 other
def test_classify_no_match():
    primary, _, confidence = classify("患者状态良好，无特殊不适")
    assert primary == "other"
    assert confidence == 0.5


# build_timeline_entry 结构
def test_build_timeline_entry():
    entry = build_timeline_entry("/tmp/x.jpg", "lab_results", ["2024-03-15"], title="血常规")
    assert entry["category"] == "lab_results"
    assert entry["dates"] == ["2024-03-15"]
    assert entry["file"] == "/tmp/x.jpg"


# Fix 2：规则层对全文匹配，前500字后仍有关键词也应命中
def test_rule_match_full_text_not_truncated():
    long_prefix = "患者自述无特殊不适，既往体健。" * 50  # 远超500字
    text = long_prefix + "本报告为胸部CT检查结果：右肺上叶结节。"
    cats = _rule_match(text)
    assert "imaging" in cats, "规则层应全文匹配，不应截断到前500字"


# Fix 8：YY/MM/DD 含时间的日期应正确提取日期部分，不混入时间
def test_extract_dates_with_time_suffix():
    # 24/03/15 12:30 中的日期部分应被正确提取
    result = _extract_dates("记录时间 24/03/15 12:30")
    assert result == ["2024-03-15"], "应正确提取日期部分，忽略时间"


# Fix 8：YY/MM/DD 正常匹配仍应工作
def test_extract_dates_yy_mm_dd_normal():
    result = _extract_dates("报告日期 23/08/05")
    assert result == ["2023-08-05"]


# update_categories_summary 功能
def test_update_categories_summary():
    from scripts.classify import update_categories_summary
    m = {
        "files": [
            {"category": "lab_results"},
            {"category": "lab_results.blood_routine"},
            {"category": "imaging"},
            {"category": None},
            {"category": ""},
        ]
    }
    update_categories_summary(m)
    assert m["categories_summary"]["lab_results"] == 2
    assert m["categories_summary"]["imaging"] == 1
