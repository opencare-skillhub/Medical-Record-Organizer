"""v2 数据契约一致性测试。"""
from __future__ import annotations

import re
from pathlib import Path

from scripts.v2.map_extract import EXTRACT_SCHEMA
from scripts.v2.render_html import compute_report_context
from scripts.v2.shuffle_group import group_by_type, merge_lab_trends


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_CONTRACT = PROJECT_ROOT / "dev" / "docs" / "data-contract.md"
TEMPLATE = PROJECT_ROOT / "references" / "html-report-template.html"


EXPECTED_REPORT_TYPES = {
    "lab_results",
    "imaging",
    "pathology",
    "medication",
    "clinical_records",
    "basic_info",
    "invoice",
    "noise",
}

EXPECTED_CONTEXT_KEYS = {
    "demographics",
    "has_critical",
    "critical_alerts",
    "timeline",
    "pathology",
    "pathology_tag",
    "genetic_highlights",
    "ihc_note",
    "medication_summary",
    "medication_table",
    "medication_prescription_date",
    "medication",
    "imaging_summary",
    "tumor_marker_tables",
    "lab_trend",
    "chart_svg_ca199",
    "chart_svg",
    "key_concerns",
    "consultation_questions",
    "files",
    "gaps",
    "updated_at",
    "report_title",
}


def test_map_schema_report_type_enum_matches_data_contract():
    schema_enum = set(EXTRACT_SCHEMA["properties"]["report_type"]["enum"])
    contract_text = DATA_CONTRACT.read_text(encoding="utf-8")

    assert schema_enum == EXPECTED_REPORT_TYPES
    for report_type in EXPECTED_REPORT_TYPES:
        assert f"`{report_type}`" in contract_text


def test_shuffle_consumes_contract_report_type_and_lab_values():
    extracted = [
        {
            "report_type": "lab_results",
            "document_date": "2025-03-31",
            "_source_file": "lab.md",
            "lab_values": [
                {
                    "name": "CA199",
                    "value": 88.0,
                    "unit": "U/ml",
                    "date": "2025-03-31",
                    "ref_low": 0,
                    "ref_high": 37,
                    "abnormal": True,
                }
            ],
        },
        {"report_type": "imaging", "document_date": "2025-04-01", "_source_file": "ct.md"},
    ]

    groups = group_by_type(extracted)
    trends = merge_lab_trends(groups["lab"])

    assert "lab" in groups
    assert "imaging" in groups
    assert "CA199" in trends
    assert trends["CA199"]["ref_range"] == (0, 37)
    assert trends["CA199"]["trend"][0]["flag"] == "↑"


def test_compute_report_context_contains_template_contract_keys():
    profile = {
        "patient_id": "P_TEST",
        "generated_at": "2026-06-24T00:00:00+00:00",
        "lab_trends": {
            "CA199": {
                "unit": "U/ml",
                "ref_range": (0, 37),
                "trend": [
                    {
                        "date": "2025-03-31",
                        "value": 88.0,
                        "unit": "U/ml",
                        "abnormal": True,
                    }
                ],
            }
        },
        "lab_analysis": {"CA199": {"alert_level": "warning", "clinical_inference": "异常"}},
        "medication_timeline": {
            "timeline": [
                {"name": "奥希替尼", "type": "靶向", "start_date": "2025-04-02", "dosage": "80mg QD"}
            ]
        },
        "imaging_narrative": {},
    }
    groups = {
        "demographics": [
            {
                "report_type": "basic_info",
                "document_date": "2025-03-30",
                "_source_file": "basic.md",
                "demographics": {"name": "张三", "gender": "男", "age": 62},
            }
        ],
        "lab": [],
        "imaging": [],
        "medication": [],
        "pathology": [],
    }

    ctx = compute_report_context(profile, groups)

    assert EXPECTED_CONTEXT_KEYS <= set(ctx)
    assert ctx["demographics"]["name"] == "张三"
    assert "CA199" in ctx["tumor_marker_tables"]


def test_template_uses_only_known_top_level_context_variables():
    template_text = TEMPLATE.read_text(encoding="utf-8")
    ignored = {
        "a",
        "c",
        "d",
        "f",
        "g",
        "gh",
        "ihc_items",
        "is_al",
        "is_alert",
        "item",
        "label",
        "lvl",
        "m",
        "marker_data",
        "marker_name",
        "msg",
        "q",
        "row",
        "t",
        "text",
        "loop",
        "getattr",
    }
    candidates = set(re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", template_text))
    template_vars = {
        name
        for name in candidates
        if name in EXPECTED_CONTEXT_KEYS and name not in ignored
    }

    assert template_vars <= EXPECTED_CONTEXT_KEYS
    assert {"demographics", "timeline", "report_title", "tumor_marker_tables"} <= template_vars
