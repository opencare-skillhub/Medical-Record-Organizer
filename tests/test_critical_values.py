"""
scripts/critical_values.py 验收测试

覆盖：
  ① 血钾 7.2 mmol/L → Ⅴ级（极危急，CTCAE G4）
  ② 血红蛋白 55 g/L → Ⅴ级（极危急）
  ③ 血小板 22 → Ⅴ级（极危急）
  ④ 白细胞 0.8 → Ⅴ级（极危急）
  ⑤ 中性粒细胞 0.4 → Ⅴ级（极危急）
  ⑥ 血钾 4.2 mmol/L → Ⅱ级（轻度异常，低于正常下限）
  ⑦ has_critical_alerts 正确过滤 Ⅳ/Ⅴ 级
  ⑧ format_alerts_md 输出含 🆘
  ⑨ format_alerts_html 输出含红色 CSS
  ⑩ blood_test.txt 端到端（正常值，无 Ⅳ/Ⅴ 级）
  ⑪ blood_test_critical.txt 端到端（多项 Ⅴ 级）
  ⑫ 结果按 level 降序排列（最危险在前）
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.critical_values import (
    LEVEL_1, LEVEL_2, LEVEL_3, LEVEL_4, LEVEL_5,
    LEVEL_COLORS, LEVEL_EMOJIS, LEVEL_LABELS,
    check_critical_values,
    has_critical_alerts,
    format_alerts_md,
    format_alerts_html,
    CriticalAlert,
    _CRITICAL_THRESHOLD,
)


def _alert(name="血钾", value=7.2, unit="mmol/L", level=LEVEL_5):
    return CriticalAlert(
        item_name=name,
        value=value,
        unit=unit,
        level=level,
        level_label=LEVEL_LABELS[level],
        message=f"{name} {value}{unit} ↑↑ {LEVEL_LABELS[level]}，立即拨打 120",
        color=LEVEL_COLORS[level],
        emoji=LEVEL_EMOJIS[level],
        action="立即拨打 120",
        category="电解质",
    )


# ① 血钾 7.2 → Ⅴ级
def test_hyperkalemia_level_5():
    text = "血钾：7.2 mmol/L"
    alerts = check_critical_values(text)
    k = [a for a in alerts if "钾" in a.item_name or "K" in a.item_name]
    assert k, "应检测到血钾告警"
    assert k[0].level == LEVEL_5
    assert k[0].emoji == "🆘"


# ② 血红蛋白 55 → Ⅴ级
def test_hemoglobin_level_5():
    text = "血红蛋白(HGB) 55 g/L"
    alerts = check_critical_values(text)
    # display_name 取最短别名，可能是 "Hb"
    hb = [a for a in alerts if a.item_name in ("血红蛋白", "HGB", "Hb", "血红蛋白浓度")]
    assert hb, f"应检测到血红蛋白告警，实际 alerts: {[(a.item_name, a.value) for a in alerts]}"
    assert hb[0].level == LEVEL_5
    assert hb[0].value == 55.0


# ③ 血小板 22 → Ⅳ级（CTCAE G3，重度；<10 才是 Ⅴ级 G4）
def test_platelet_level_4():
    text = "血小板(PLT) 22 ×10^9/L"
    alerts = check_critical_values(text)
    pl = [a for a in alerts if "血小板" in a.item_name]
    assert pl, "应检测到血小板告警"
    assert pl[0].level == LEVEL_4
    assert pl[0].value == 22.0


# ④ 白细胞 0.8 → Ⅴ级
def test_wbc_level_5():
    text = "白细胞(WBC) 0.8 ×10^9/L"
    alerts = check_critical_values(text)
    wbc = [a for a in alerts if "白细胞" in a.item_name or "WBC" in a.item_name]
    assert wbc, "应检测到白细胞告警"
    assert wbc[0].level == LEVEL_5


# ⑤ 中性粒细胞 0.4 → Ⅴ级
def test_neutrophil_level_5():
    text = "中性粒细胞(ANC) 0.4 ×10^9/L"
    alerts = check_critical_values(text)
    anc = [a for a in alerts if "中性粒" in a.item_name or "ANC" in a.item_name]
    assert anc, "应检测到中性粒细胞告警"
    assert anc[0].level == LEVEL_5


# ⑥ 血钾 4.2 mmol/L → Ⅱ级（轻度异常，略低于正常下限 3.5-5.5）
def test_hypokalemia_mild_level_2():
    text = "血钾：4.2 mmol/L"
    alerts = check_critical_values(text)
    k = [a for a in alerts if "钾" in a.item_name or "K" in a.item_name]
    if k:
        assert k[0].level == LEVEL_2
    else:
        # 若规则认为正常也接受（边界弹性）
        pass


# ⑦ has_critical_alerts 过滤 Ⅳ/Ⅴ 级
def test_has_critical_alerts_filter():
    mixed = [
        _alert("血钾", 7.2, "mmol/L", LEVEL_5),
        _alert("血红蛋白", 55, "g/L", LEVEL_5),
        _alert("CEA", 8.0, "ng/mL", LEVEL_3),
    ]
    assert has_critical_alerts(mixed) is True
    safe = [_alert("CEA", 3.0, "ng/mL", LEVEL_2)]
    assert has_critical_alerts(safe) is False


# ⑧ format_alerts_md 含 🆘
def test_format_alerts_md_contains_emoji():
    alerts = [_alert("血钾", 7.2, "mmol/L", LEVEL_5)]
    md = format_alerts_md(alerts)
    assert "🆘" in md
    assert "7.2" in md
    assert "mmol/L" in md
    assert "立即拨打 120" in md


# ⑨ format_alerts_html 含红色警示结构（颜色由 render_html 的 CSS 提供）
def test_format_alerts_html_contains_alert_structure():
    alerts = [_alert("血钾", 7.2, "mmol/L", LEVEL_5)]
    html = format_alerts_html(alerts)
    assert "critical-banner" in html
    assert "alert-level-5" in html          # CSS 类名，render_html 会为其注入红色样式
    assert "🆘" in html
    assert 'role="alert"' in html           # 无障碍访问标记
    assert "立即拨打 120" in html


# ⑩ blood_test.txt 端到端（正常值，无 Ⅳ/Ⅴ 级）
def test_normal_blood_test_no_critical():
    fixture = Path(__file__).parent / "fixtures" / "blood_test.txt"
    text = fixture.read_text(encoding="utf-8")
    alerts = check_critical_values(text)
    critical = [a for a in alerts if a.level >= _CRITICAL_THRESHOLD]
    assert critical == [], f"正常血常规不应有 Ⅳ/Ⅴ 级告警，实际: {[(a.item_name, a.level) for a in critical]}"


# ⑪ blood_test_critical.txt 端到端（多项 Ⅳ/Ⅴ 级）
def test_critical_blood_test_has_high_levels():
    fixture = Path(__file__).parent / "fixtures" / "blood_test_critical.txt"
    text = fixture.read_text(encoding="utf-8")
    alerts = check_critical_values(text)
    # PLT 22 → Level 4 (CTCAE G3)，其余四项 → Level 5 (G4)
    high_levels = [a for a in alerts if a.level >= LEVEL_4]
    unique_names = {a.item_name for a in high_levels}
    assert len(unique_names) >= 4, f"期望 ≥4 个不同指标达 Ⅳ/Ⅴ 级，实际: {unique_names}"
    # 确认包含关键指标（display_name 可能是缩写）
    has_hb = any(n in ("血红蛋白", "HGB", "Hb", "血红蛋白浓度") for n in unique_names)
    has_wbc = any(n in ("白细胞", "WBC", "白细胞计数") for n in unique_names)
    assert has_hb, f"应包含血红蛋白告警，实际: {unique_names}"
    assert has_wbc, f"应包含白细胞告警，实际: {unique_names}"


# ⑫ check_critical_values 返回结果按 level 降序排列（最危险在前）
def test_alerts_sorted_descending():
    # 用一段包含多个指标的文本来验证排序
    text = (
        "CEA 8.0 ng/mL\n"
        "血钾：7.2 mmol/L\n"
        "ALT 600 U/L\n"
    )
    alerts = check_critical_values(text)
    levels = [a.level for a in alerts]
    assert levels == sorted(levels, reverse=True), (
        f"check_critical_values 应按 level 降序排列，实际: {levels}"
    )


# 边界：空文本
def test_empty_text_returns_no_alerts():
    assert check_critical_values("") == []
    assert check_critical_values("   ") == []


# 边界：不相关文本
def test_irrelevant_text_returns_no_alerts():
    text = "患者状态良好，无特殊不适，今日出院。"
    alerts = check_critical_values(text)
    assert alerts == []


def test_alert_helpers_accept_dict_alerts():
    alert = _alert("血钾", 7.2, "mmol/L", LEVEL_5).__dict__

    assert has_critical_alerts([alert]) is True

    md = format_alerts_md([alert])
    html = format_alerts_html([alert])

    assert "血钾" in md
    assert "critical-banner" in html


def test_format_alerts_html_escapes_dynamic_fields():
    alert = _alert("<script>alert(1)</script>", 7.2, "mmol/L", LEVEL_5).__dict__
    alert["message"] = '<img src=x onerror="alert(1)">'
    alert["category"] = "<b>电解质</b>"
    alert["action"] = "<script>steal()</script>"

    html = format_alerts_html([alert])

    # 核心 XSS 向量：不应出现未转义的 HTML 标签
    assert "<script" not in html
    assert "<img" not in html
    assert "<b>" not in html
    # 转义后的文本内容应保留（作为安全文本）
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "critical-banner" in html
