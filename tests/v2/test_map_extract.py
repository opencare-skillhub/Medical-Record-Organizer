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
        'report_type': 'lab_results',
        'document_date': '2025-03-31',
        'confidence': 0.9,
        'lab_values': [
            {'name': 'CEA', 'value': 5.51, 'unit': 'ng/ml', 'ref_low': 0, 'ref_high': 5},
            {'name': 'CA199', 'value': 16.6, 'unit': 'U/ml', 'ref_low': 0, 'ref_high': 37},
        ],
    }
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda messages, schema, **kw: response)

    result = extract_single(text, 'lab_report.md')
    assert result['report_type'] == 'lab_results'
    assert result['document_date'] == '2025-03-31'
    assert result['report_date'] == '2025-03-31'
    assert any(v['name'] in ('CEA', 'CA199') for v in result.get('lab_values', []))


def test_extract_invoice_as_noise(monkeypatch):
    text = '门诊收费发票 金额：¥350.00 收款员：张三'
    response = {
        'report_type': 'noise',
        'confidence': 0.95,
        'noise': ['发票', '收费'],
    }
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda messages, schema, **kw: response)

    result = extract_single(text, 'invoice.jpg.md')
    assert result['report_type'] == 'noise'
    assert len(result.get('noise', [])) > 0


def test_extract_single_adds_source_file():
    text = '血常规报告'
    response = {'report_type': 'lab_results', 'confidence': 0.8}
    import scripts.v2.map_extract as mm
    original = mm.call_llm_with_retry
    try:
        mm.call_llm_with_retry = lambda *a, **kw: response
        result = extract_single(text, 'report_001.md')
        assert result['_source_file'] == 'report_001.md'
    finally:
        mm.call_llm_with_retry = original


def test_extract_batch_writes_json(tmp_dir, monkeypatch):
    response = {'report_type': 'lab_results', 'confidence': 0.8}
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda *a, **kw: response)

    (tmp_dir / 'a.md').write_text('检验报告', encoding='utf-8')
    (tmp_dir / 'b.md').write_text('CT报告', encoding='utf-8')
    out_dir = tmp_dir / 'out'
    results = extract_batch(str(tmp_dir), str(out_dir))

    assert len(results) == 2
    assert (out_dir / 'a.json').exists()
    assert (out_dir / 'b.json').exists()


# ── 关键词规则兜底测试 ──────────────────────────────────────────────


def test_keyword_fallback_corrects_noise_to_lab_results(monkeypatch):
    """LLM 返回 noise 但文本含检验关键词 → 兜底修正为 lab_results。"""
    text = '报告日期：2025-03-31 检验报告 癌胚抗原 5.51 ng/ml 参考区间 0-5'
    response = {'report_type': 'noise', 'confidence': 0.0}
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda *a, **kw: response)

    result = extract_single(text, 'blood_test.md')
    assert result['report_type'] == 'lab_results'
    assert result['confidence'] >= 0.7


def test_keyword_fallback_corrects_noise_to_imaging(monkeypatch):
    """LLM 返回 noise 但文本含 CT 关键词 → 兜底修正为 imaging。"""
    text = '影像所见：胰头肿块 诊断意见：胰头癌治疗后改变'
    response = {'report_type': 'noise', 'confidence': 0.0}
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda *a, **kw: response)

    result = extract_single(text, 'ct_report.md')
    assert result['report_type'] == 'imaging'
    assert result['confidence'] >= 0.7


def test_keyword_fallback_corrects_noise_to_pathology(monkeypatch):
    """LLM 返回 noise 但文本含病理/基因关键词 → 兜底修正为 pathology。"""
    text = '病理诊断：胰腺导管腺癌 免疫组化：CK7(-) SMAD4(+) KRAS G12D 突变'
    response = {'report_type': 'noise', 'confidence': 0.0}
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda *a, **kw: response)

    result = extract_single(text, 'pathology.md')
    assert result['report_type'] == 'pathology'
    assert result['confidence'] >= 0.7


def test_keyword_fallback_corrects_noise_to_medication(monkeypatch):
    """LLM 返回 noise 但文本含化疗/方案关键词 → 兜底修正为 medication。"""
    text = 'AG方案 白蛋白紫杉醇 180mg 静滴 吉西他滨 8支/d1 化疗第38次'
    response = {'report_type': 'noise', 'confidence': 0.0}
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda *a, **kw: response)

    result = extract_single(text, 'therapy.md')
    assert result['report_type'] == 'medication'
    assert result['confidence'] >= 0.7


def test_keyword_fallback_does_not_override_high_confidence(monkeypatch):
    """高置信度 non-noise 结果不应被关键词覆盖。"""
    text = 'AG方案 白蛋白紫杉醇 180mg 静滴 化疗第38次'
    response = {'report_type': 'medication', 'confidence': 0.95, 'medications': [{'name': '紫杉醇'}]}
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda *a, **kw: response)

    result = extract_single(text, 'therapy.md')
    assert result['report_type'] == 'medication'
    assert result['confidence'] == 0.95


def test_keyword_fallback_does_not_correct_invoice(monkeypatch):
    """发票文本虽含'收费'但不是医疗内容 → 仍保持 noise。"""
    text = '门诊收费发票 金额：¥350.00 收款员：张三'
    response = {'report_type': 'noise', 'confidence': 0.95, 'noise': ['发票', '收费']}
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda *a, **kw: response)

    result = extract_single(text, 'invoice.jpg.md')
    assert result['report_type'] == 'noise'


# ── 基因报告 schema 测试 ────────────────────────────────────────────


def test_genetic_report_pharmacogenomics_field(monkeypatch):
    """基因检测报告应能提取 pharmacogenomics（UGT1A1/DPYD）字段。"""
    text = '肿瘤基因检测报告 UGT1A1*28 6TA/6TA 野生型 伊立替康 毒副作用风险较低'
    response = {
        'report_type': 'pathology',
        'confidence': 0.9,
        'document_date': '2024-02-17',
        'test_items': [
            {'gene_name': 'KRAS', 'detection_result': 'G12D突变', 'is_pathogenic': True},
            {'gene_name': 'TP53', 'detection_result': 'R248W突变', 'is_pathogenic': True},
        ],
        'pharmacogenomics': [
            {'gene': 'UGT1A1', 'variant': 'UGT1A1*28', 'genotype': '6TA/6TA',
             'drug': '伊立替康', 'risk': '毒副作用风险较低', 'recommendation': ''},
        ],
        'report_summary': 'KRAS G12D驱动突变；TMB-Low 1.89; MSI稳定',
    }
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda *a, **kw: response)

    result = extract_single(text, 'gene_report.md')
    assert result['report_type'] == 'pathology'
    assert len(result['test_items']) == 2
    assert len(result['pharmacogenomics']) == 1
    assert result['pharmacogenomics'][0]['gene'] == 'UGT1A1'
    assert result['pharmacogenomics'][0]['drug'] == '伊立替康'
    assert 'KRAS' in result.get('report_summary', '')


def test_genetic_report_qc_metrics_field(monkeypatch):
    """基因报告应能提取 QC 质控信息。"""
    text = 'DNA抽提量(ng) 合格 平均测序深度 3203.65X'
    response = {
        'report_type': 'pathology',
        'confidence': 0.9,
        'qc_metrics': {
            'dna_quantity': '合格',
            'average_depth': '3203.65X',
            'quality': '合格',
        },
    }
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda *a, **kw: response)

    result = extract_single(text, 'gene_report.md')
    assert result['report_type'] == 'pathology'
    assert result['qc_metrics']['average_depth'] == '3203.65X'
    assert result['qc_metrics']['quality'] == '合格'


def test_genetic_report_hrr_and_drug_rec_fields(monkeypatch):
    """基因报告应能提取 HRR 基因、用药推荐、TMB/MSI 等新字段。"""
    text = 'PARP HRR基因 ATM BRCA2 TMB<0.1 MSS 可能敏感药物 奥拉帕利'
    response = {
        'report_type': 'pathology', 'confidence': 0.9,
        'tmb_value': 'TMB<0.1',
        'msi_status': 'MSS',
        'hrr_genes': [
            {'gene': 'ATM', 'status': '致病突变', 'is_pathogenic': True},
            {'gene': 'BRCA2', 'status': '野生型', 'is_pathogenic': False},
        ],
        'drug_recommendations': [
            {'gene': 'ATM', 'drug': '奥拉帕利', 'sensitivity': '可能敏感', 'evidence': 'NCCN'},
        ],
        'test_items': [
            {'gene_name': 'ATM', 'detection_result': '移码缺失', 'is_pathogenic': True},
        ],
    }
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda *a, **kw: response)

    result = extract_single(text, 'gene_hrr.md')
    assert result['tmb_value'] == 'TMB<0.1'
    assert result['msi_status'] == 'MSS'
    assert len(result['hrr_genes']) == 2
    assert result['hrr_genes'][0]['gene'] == 'ATM'
    assert result['hrr_genes'][1]['is_pathogenic'] is False
    assert result['drug_recommendations'][0]['drug'] == '奥拉帕利'


def test_genetic_report_sample_info_field(monkeypatch):
    """基因报告应提取 sample_info（样本类型/平台/出具方等临床上下文）。"""
    text = '石蜡切片+血液 胰腺 胰腺癌 III期 MGISEQ-2000 华大'
    response = {
        'report_type': 'pathology', 'confidence': 0.9,
        'sample_info': {
            'specimen_type': '石蜡切片+血液',
            'biopsy_site': '胰腺',
            'tumor_type': '胰腺癌',
            'cancer_stage': 'III',
            'sample_id': '23B06606453R',
            'hospital': '昆山市中医医院',
            'issuing_org': '华大基因',
            'sampling_date': '2024-02-09',
            'receipt_date': '2024-02-10',
            'reporting_platform': 'MGISEQ-2000/DNBSEQ-T7',
            'gene_panel_size': '689个实体瘤基因+69个胚系基因',
        },
    }
    monkeypatch.setattr('scripts.v2.map_extract.call_llm_with_retry', lambda *a, **kw: response)

    result = extract_single(text, 'gene_full.md')
    assert result['sample_info']['specimen_type'] == '石蜡切片+血液'
    assert result['sample_info']['biopsy_site'] == '胰腺'
    assert result['sample_info']['cancer_stage'] == 'III'
    assert result['sample_info']['reporting_platform'] == 'MGISEQ-2000/DNBSEQ-T7'
    assert result['sample_info']['issuing_org'] == '华大基因'
    assert result['sample_info']['hospital'] == '昆山市中医医院'
