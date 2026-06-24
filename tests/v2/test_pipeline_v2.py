"""
v2 pipeline 测试
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.v2.pipeline_v2 import run_pipeline


def test_run_pipeline_generates_profile(tmp_dir, monkeypatch):
    input_dir = tmp_dir / 'input'
    input_dir.mkdir()
    (input_dir / 'a.md').write_text('姓名：张三，性别：男', encoding='utf-8')
    (input_dir / 'b.md').write_text('检验报告：CEA 5.2 ng/ml', encoding='utf-8')

    output_dir = tmp_dir / 'output'
    profile = run_pipeline(str(input_dir), str(output_dir), patient_id='P001')

    assert profile['patient_id'] == 'P001'
    assert profile['file_count'] == 2
    assert profile['map_count'] == 2
    assert (output_dir / 'profile.json').exists()
    assert (output_dir / 'mdt_analysis.json').exists()
    mdt = json.loads((output_dir / 'mdt_analysis.json').read_text(encoding='utf-8'))
    assert {'specialty_reports', 'concerns', 'fallback_used', 'error'} <= set(mdt)
    assert (output_dir / 'report.html').exists()
    assert (output_dir / 'report.html').stat().st_size > 0
    assert (output_dir / 'case_report.md').exists()
    assert (output_dir / 'mappings.json').exists()


def test_run_pipeline_no_input(tmp_dir):
    output_dir = tmp_dir / 'output'
    profile = run_pipeline(str(tmp_dir), str(output_dir), patient_id='P001')
    assert profile['status'] == 'no_input'
    assert profile['files'] == 0


def test_run_pipeline_creates_sanitized_and_map_dirs(tmp_dir, monkeypatch):
    input_dir = tmp_dir / 'input'
    input_dir.mkdir()
    (input_dir / 'a.md').write_text('姓名：张三', encoding='utf-8')

    output_dir = tmp_dir / 'output'
    profile = run_pipeline(str(input_dir), str(output_dir), patient_id='P001')

    assert (output_dir / 'sanitized').exists()
    assert (output_dir / 'map').exists()
    assert (output_dir / 'report.html').exists()
    assert (output_dir / 'sanitized' / 'a.md').exists()
