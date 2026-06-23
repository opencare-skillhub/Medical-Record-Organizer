"""
v2 Reduce 层测试
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from scripts.v2.reduce_merge import reduce_lab_trends, reduce_medication_history, reduce_imaging_narrative


def test_reduce_lab_detects_rising_trend(monkeypatch):
    trends = {
        'CA199': {
            'unit': 'U/ml',
            'ref_range': [0, 37],
            'trend': [
                {'date': '2025-01-01', 'value': 100},
                {'date': '2025-02-01', 'value': 150},
                {'date': '2025-03-01', 'value': 200},
            ],
        }
    }
    expected = {
        'trend_summary': '持续上升',
        'alert_level': 'warning',
        'clinical_inference': '指标持续上升，需关注',
        'consecutive_rises': 3,
    }
    monkeypatch.setattr(
        'scripts.v2.reduce_merge.call_llm_with_retry',
        lambda messages, schema, **kw: expected,
    )

    result = reduce_lab_trends(trends)
    assert result['CA199']['trend_summary'] in ('上升', '持续上升')
    assert result['CA199']['alert_level'] in ('warning', 'critical')


def test_reduce_lab_empty_trends():
    result = reduce_lab_trends({})
    assert result == {}


def test_reduce_medication_history(monkeypatch):
    med_group = [
        {
            'report_date': '2025-01-01',
            'medications': [{'drug': '奥希替尼', 'dose': '80mg', 'frequency': 'qd'}],
        }
    ]
    expected = {'regimens': [{'name': 'EGFR-TKI'}], 'cycles': []}
    monkeypatch.setattr(
        'scripts.v2.reduce_merge.call_llm_with_retry',
        lambda messages, schema, **kw: expected,
    )
    result = reduce_medication_history(med_group)
    assert result == expected


def test_reduce_medication_history_failure(monkeypatch):
    med_group = [{'report_date': '2025-01-01', 'medications': []}]
    monkeypatch.setattr(
        'scripts.v2.reduce_merge.call_llm_with_retry',
        lambda messages, schema, **kw: (_ for _ in ()).throw(RuntimeError('LLM 不可用')),
    )
    result = reduce_medication_history(med_group)
    assert 'error' in result


def test_reduce_imaging_narrative(monkeypatch):
    imaging_group = [
        {
            'report_date': '2025-01-01',
            'findings': ['右肺上叶结节，大小约 1.2cm'],
        }
    ]
    expected = {'primary_lesion_timeline': [], 'metastasis_timeline': [], 'overall_response': '稳定'}
    monkeypatch.setattr(
        'scripts.v2.reduce_merge.call_llm_with_retry',
        lambda messages, schema, **kw: expected,
    )
    result = reduce_imaging_narrative(imaging_group)
    assert result == expected


def test_reduce_imaging_narrative_failure(monkeypatch):
    imaging_group = [{'report_date': '2025-01-01', 'findings': []}]
    monkeypatch.setattr(
        'scripts.v2.reduce_merge.call_llm_with_retry',
        lambda messages, schema, **kw: (_ for _ in ()).throw(RuntimeError('LLM 不可用')),
    )
    result = reduce_imaging_narrative(imaging_group)
    assert 'error' in result
