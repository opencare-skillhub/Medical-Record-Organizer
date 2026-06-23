"""
scripts/parse_genetics.py 验收测试

覆盖：
  ① EGFR 19del + 点位/丰度/突变类型/致病基因 + 奥希替尼敏感
  ② ALK 融合阴性
  ③ PD-L1 TPS 60% 高表达
  ④ UGT1A1 药物代谢基因
  ⑤ 病理类型：肺腺癌
  ⑥ build_recent_focus 从危急值 + 时间线提取重点
  ⑦ build_consultation_questions 生成咨询问题
  ⑧ format_genetic_highlights_md 输出 Markdown（含新字段）
  ⑨ format_genetic_highlights_html 输出 HTML 结构（含新字段）
  ⑩ genetic_test.txt fixture 端到端
  ⑪ discharge_summary.txt 含病理信息
  ⑫ 空文本返回空列表
  ⑬ 突变丰度提取（VAF 15%）
  ⑭ 突破方式提取（获得性耐药）
  ⑮ 致病基因标记 pathogenic=True
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.parse_genetics import (
    parse_genetics,
    build_recent_focus,
    build_consultation_questions,
    format_genetic_highlights_md,
    format_genetic_highlights_html,
    GeneticHighlight,
)
from scripts.critical_values import CriticalAlert, LEVEL_4


# ── ① EGFR 19del + 奥希替尼敏感 ─────────────────────────────────────

def test_parse_egfr_mutation_and_drug():
    text = "EGFR 基因：外显子19缺失突变（19del）阳性，建议使用 EGFR-TKI 靶向治疗（如奥希替尼）。"
    highlights = parse_genetics(text)
    egfr = [h for h in highlights if h.gene == "EGFR"]
    assert egfr, f"应检测到 EGFR，实际: {[h.gene for h in highlights]}"
    # 点位提取
    assert egfr[0].position == "19del" or "19del" in egfr[0].position
    # 突变类型
    assert "缺失" in egfr[0].mutation
    # 致病基因标记
    assert egfr[0].pathogenic is True
    # 药物敏感
    assert "奥希替尼" in egfr[0].drug_sensitivity or "EGFR-TKI" in egfr[0].drug_sensitivity


# ── ② ALK 融合阴性 ──────────────────────────────────────────────────

def test_parse_alk_negative():
    text = "ALK 基因：未检测到融合（阴性）"
    highlights = parse_genetics(text)
    alk = [h for h in highlights if h.gene == "ALK"]
    assert alk, f"应检测到 ALK，实际: {[h.gene for h in highlights]}"
    # ALK 融合属于突变类型
    assert "融合" in alk[0].mutation or "融合" in (alk[0].raw_text or "")
    assert alk[0].pathogenic is True


# ── ③ PD-L1 TPS 60% ─────────────────────────────────────────────────

def test_parse_pdl1_expression():
    text = "PD-L1 表达：TPS 60%"
    highlights = parse_genetics(text)
    # PD-L1 可能附加到 EGFR 条目上，或单独出现
    immune = [h for h in highlights if "PD-L1" in (h.immune_marker or "")]
    if not immune:
        # 也可能在 immune_marker 里
        all_text = " ".join(h.immune_marker or "" for h in highlights)
        assert "PD-L1" in all_text, f"应检测到 PD-L1，实际 highlights: {highlights}"
    else:
        assert "60%" in immune[0].immune_marker or "TPS 60" in immune[0].immune_marker


# ── ④ UGT1A1 药物代谢基因 ──────────────────────────────────────────

def test_parse_pharmacogenomics():
    text = "患者 UGT1A1 基因型为 *1/*1，伊立替康代谢正常。"
    highlights = parse_genetics(text)
    ugt = [h for h in highlights if h.gene == "UGT1A1"]
    assert ugt, f"应检测到 UGT1A1，实际: {[h.gene for h in highlights]}"
    assert ugt[0].level == "info"


# ── ⑤ 病理类型：肺腺癌 ──────────────────────────────────────────────

def test_parse_pathology_type():
    text = "病理结果：右肺上叶浸润性腺癌"
    highlights = parse_genetics(text)
    pt = [h for h in highlights if h.gene == "病理类型"]
    assert pt, f"应检测到病理类型，实际: {[h.gene for h in highlights]}"
    assert "腺癌" in pt[0].pathology_type


# ── ⑥ build_recent_focus ─────────────────────────────────────────────

def test_build_recent_focus_from_critical():
    alerts = [
        CriticalAlert(
            item_name="血钾", value=7.2, unit="mmol/L",
            level=LEVEL_4, level_label="Ⅳ级（高危急）",
            message="血钾 7.2 mmol/L ↑↑ Ⅳ级（高危急），立即拨打 120",
            color="#e74c3c", emoji="🔴", action="立即拨打 120",
            category="电解质",
        ),
    ]
    focus = build_recent_focus(alerts, [], [], [])
    assert any("危急值" in f for f in focus)


def test_build_recent_focus_from_timeline():
    timeline = [
        {"dates": ["2024-03-15"], "title": "首诊，肺腺癌确诊"},
        {"dates": ["2024-03-20"], "title": "基因检测报告"},
    ]
    focus = build_recent_focus([], [], [], timeline)
    assert len(focus) >= 1
    # build_recent_focus 从时间线取最近事件，两条都应在列表中
    focus_text = " ".join(focus)
    assert "基因检测报告" in focus_text


# ── ⑦ build_consultation_questions ───────────────────────────────────

def test_build_consultation_questions_from_gaps():
    gaps = ["缺少过敏史信息", "缺少最近化疗方案"]
    questions = build_consultation_questions(gaps, [], [])
    assert len(questions) >= 1
    assert any("过敏" in q for q in questions)


def test_build_consultation_questions_from_genetics():
    highlights = [
        GeneticHighlight(gene="EGFR", mutation="19del",
                         drug_sensitivity="奥希替尼敏感",
                         level="highlight"),
    ]
    questions = build_consultation_questions([], [], highlights)
    assert any("EGFR" in q and "19del" in q for q in questions)


# ── ⑧ format_genetic_highlights_md ───────────────────────────────────

def test_format_genetic_highlights_md():
    highlights = [
        GeneticHighlight(gene="EGFR", position="19del", mutation="缺失突变",
                         drug_sensitivity="奥希替尼敏感", level="highlight"),
        GeneticHighlight(gene="病理类型", pathology_type="肺腺癌", level="info"),
    ]
    md = format_genetic_highlights_md(highlights)
    assert "基因与病理重点提示" in md
    assert "EGFR" in md
    assert "19del" in md
    assert "肺腺癌" in md


# ── ⑨ format_genetic_highlights_html ─────────────────────────────────

def test_format_genetic_highlights_html():
    highlights = [
        GeneticHighlight(gene="EGFR", position="19del", mutation="缺失突变",
                         drug_sensitivity="奥希替尼敏感", level="highlight"),
    ]
    html = format_genetic_highlights_html(highlights)
    assert "genetic-section" in html
    assert "EGFR" in html
    assert "19del" in html
    assert "<table" in html


def test_format_genetic_highlights_html_escapes_dynamic_fields():
    highlights = [
        GeneticHighlight(
            gene="<script>alert(1)</script>",
            position='<img src=x onerror="alert(1)">',
            mutation="<b>突变</b>",
            drug_sensitivity="<script>steal()</script>",
            level="highlight",
        ),
    ]

    html = format_genetic_highlights_html(highlights)

    assert "<script" not in html
    assert "onerror" not in html
    assert "<img" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


# ── ⑩ genetic_test.txt fixture 端到端 ────────────────────────────────

def test_genetic_test_fixture():
    fixture = Path(__file__).parent / "fixtures" / "genetic_test.txt"
    text = fixture.read_text(encoding="utf-8")
    highlights = parse_genetics(text)
    genes = {h.gene for h in highlights}
    assert "EGFR" in genes
    # PD-L1 应被检测到（可能附加到 EGFR 条目）
    all_immune = " ".join(h.immune_marker or "" for h in highlights)
    assert "PD-L1" in all_immune


# ── ⑪ discharge_summary.txt 含病理信息 ──────────────────────────────

def test_discharge_summary_pathology():
    fixture = Path(__file__).parent / "fixtures" / "discharge_summary.txt"
    text = fixture.read_text(encoding="utf-8")
    highlights = parse_genetics(text)
    genes = {h.gene for h in highlights}
    assert "EGFR" in genes or "病理类型" in genes


# ── ⑫ 空文本 ─────────────────────────────────────────────────────────

def test_empty_text_returns_no_highlights():
    assert parse_genetics("") == []
    assert parse_genetics("   ") == []


# ── ⑬ 突变丰度提取（VAF 15%） ──────────────────────────────────────

def test_parse_abundance():
    text = "EGFR 19del 突变，VAF 15%，同时检出 T790M 耐药突变。"
    highlights = parse_genetics(text)
    egfr = [h for h in highlights if h.gene == "EGFR"]
    assert egfr, f"应检测到 EGFR，实际: {[h.gene for h in highlights]}"
    # 丰度应提取到 VAF 15%
    assert egfr[0].abundance and "15" in egfr[0].abundance


# ── ⑭ 突破方式提取（获得性耐药） ────────────────────────────────────

def test_parse_breakthrough():
    text = "患者服用奥希替尼 18 个月后进展，基因检测发现 EGFR T790M 获得性耐药突变。"
    highlights = parse_genetics(text)
    egfr = [h for h in highlights if h.gene == "EGFR"]
    assert egfr, f"应检测到 EGFR，实际: {[h.gene for h in highlights]}"
    assert "获得性耐药" in (egfr[0].breakthrough_type or "")


# ── ⑮ 致病基因标记 pathogenic=True ─────────────────────────────────

def test_parse_pathogenic_flag():
    text = "EGFR 19del 阳性，KRAS 野生型"
    highlights = parse_genetics(text)
    egfr = [h for h in highlights if h.gene == "EGFR"]
    kras = [h for h in highlights if h.gene == "KRAS"]
    assert egfr and egfr[0].pathogenic is True
    # KRAS 野生型也属于驱动基因库，应标记为致病基因
    if kras:
        assert kras[0].pathogenic is True


# ── 辅助函数兼容 dict highlight/alert ─────────────────────────────────

def test_genetic_helpers_accept_dict_highlights_and_alerts():
    alerts = [{
        "item_name": "血钾",
        "value": 7.2,
        "unit": "mmol/L",
        "level": 4,
        "level_label": "Ⅳ级（高危急）",
        "message": "血钾 7.2 mmol/L Ⅳ级（高危急），立即就医",
        "color": "#e74c3c",
        "emoji": "🔴",
        "action": "立即就医急诊",
        "category": "电解质",
        "raw_text": "",
    }]
    highlights = [{
        "gene": "EGFR",
        "position": "19del",
        "abundance": "",
        "breakthrough_type": "",
        "pathogenic": True,
        "mutation": "缺失突变",
        "drug_sensitivity": "奥希替尼敏感",
        "immune_marker": "",
        "pathology_type": "",
        "raw_text": "",
        "level": "highlight",
    }]

    focus = build_recent_focus(alerts, [], [], [])
    questions = build_consultation_questions([], alerts, highlights)
    md = format_genetic_highlights_md(highlights)
    html = format_genetic_highlights_html(highlights)

    assert any("危急值" in item for item in focus)
    assert any("EGFR" in q for q in questions)
    assert "EGFR" in md
    assert "EGFR" in html
