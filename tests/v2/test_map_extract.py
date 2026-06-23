"""
v2 Map 层测试
"""
from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from scripts.v2.map_extract import extract_single, extract_batch


def test_extract_lab_report(monkeypatch):
    text = """
    报告日期：2025-03-31
    癌胚抗原（CEA）：5.51 ng/ml（参考值 0-5）
    糖类抗原199（CA199）：16.6 U/ml（参考值 0-37）
    """
    response = {
        'report_type': 'lab',
        'report_date': '2025-03-31',
        'confidence': 0.9,
        'lab_values': [
            {'name': 'CEA', 'value': 5.51, 'unit': 'ng/ml', 'ref_low': 0, 'ref_high': 5},
            {'name': 'CA199', 'value': 16.6, 'unit': 'U/ml', 'ref_low': 0, 'ref_high': 37},
        ],
    }
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda messages, schema, **kw: response)

    result = extract_single(text, 'lab_report.md')
    assert result['report_type'] == 'lab'
    assert result['report_date'] == '2025-03-31'
    assert any(v['name'] in ('CEA', 'CA199') for v in result.get('lab_values', []))


def test_extract_invoice_as_noise(monkeypatch):
    text = '门诊收费发票 金额：¥350.00 收款员：张三'
    response = {
        'report_type': 'other',
        'confidence': 0.95,
        'noise': ['发票', '收费'],
    }
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda messages, schema, **kw: response)

    result = extract_single(text, 'invoice.jpg.md')
    assert result['report_type'] == 'other'
    assert len(result.get('noise', [])) > 0


def test_extract_single_adds_source_file():
    text = '血常规报告'
    response = {'report_type': 'lab', 'confidence': 0.8}
    import scripts.v2.map_extract as mm
    original = mm.call_llm_with_retry
    try:
        mm.call_llm_with_retry = lambda *a, **kw: response
        result = extract_single(text, 'report_001.md')
        assert result['_source_file'] == 'report_001.md'
    finally:
        mm.call_llm_with_retry = original


def test_extract_batch_writes_json(tmp_dir, monkeypatch):
    response = {'report_type': 'lab', 'confidence': 0.8}
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda *a, **kw: response)

    (tmp_dir / 'a.md').write_text('检验报告', encoding='utf-8')
    (tmp_dir / 'b.md').write_text('CT报告', encoding='utf-8')
    out_dir = tmp_dir / 'out'
    results = extract_batch(str(tmp_dir), str(out_dir))

    assert len(results) == 2
    assert (out_dir / 'a.json').exists()
    assert (out_dir / 'b.json').exists()
