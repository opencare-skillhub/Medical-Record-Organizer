"""
CLI 入口测试（xyb）

注意：xyb 是脚本文件，通过 subprocess 调用以模拟真实 CLI 使用。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


XYB_PATH = str(Path(__file__).resolve().parent.parent / "xyb")


def _run_xyb(args):
    result = subprocess.run(
        [sys.executable, XYB_PATH] + args,
        capture_output=True,
        text=True,
    )
    return result


def test_xyb_help():
    result = _run_xyb(["--help"])
    assert result.returncode == 0
    assert "Patient Record Organizer" in result.stdout or "收集资料" in result.stdout


def test_xyb_ingest_list(tmp_dir):
    (tmp_dir / "a.jpg").write_bytes(b"img")
    (tmp_dir / "b.mp3").write_bytes(b"audio")
    result = _run_xyb(["ingest", str(tmp_dir)])
    assert result.returncode == 0
    assert "收集到" in result.stdout


def test_xyb_manifest_init(tmp_dir):
    result = _run_xyb([
        "manifest", "--init", "--patient", "P_TEST",
        "--name", "测试", "--age", "30"
    ])
    assert result.returncode == 0
    assert "P_TEST" in result.stdout


def test_xyb_process_publish_requires_public_confirmation(tmp_dir):
    result = _run_xyb(["process", str(tmp_dir), "--publish"])
    assert result.returncode != 0
    assert "--confirm-public" in result.stderr


def test_xyb_process_help_includes_publish_safety_flags():
    result = _run_xyb(["process", "--help"])
    assert result.returncode == 0
    assert "--confirm-public" in result.stdout
    assert "--no-desensitize" in result.stdout


def test_pipeline_cli_open_prefers_report_html(tmp_dir, monkeypatch):
    import scripts.pipeline as pipeline

    opened = []
    (tmp_dir / "input.md").write_text("检验报告", encoding="utf-8")
    output_dir = tmp_dir / "output"
    output_dir.mkdir()
    (output_dir / "report.html").write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(
        pipeline,
        "run_pipeline",
        lambda **_kw: {"patient_id": "P_TEST", "file_count": 1, "groups": {}},
    )
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    rc = pipeline.main([
        "--input-dir", str(tmp_dir),
        "--output-dir", str(output_dir),
        "--patient-id", "P_TEST",
        "--format", "html",
        "--open",
    ])

    assert rc == 0
    assert opened == [f"file://{output_dir / 'report.html'}"]


def test_pipeline_cli_open_falls_back_to_case_report_html(tmp_dir, monkeypatch):
    import scripts.pipeline as pipeline

    opened = []
    (tmp_dir / "input.md").write_text("检验报告", encoding="utf-8")
    output_dir = tmp_dir / "output"
    output_dir.mkdir()
    (output_dir / "case_report.html").write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(
        pipeline,
        "run_pipeline",
        lambda **_kw: {"patient_id": "P_TEST", "file_count": 1, "groups": {}},
    )
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    rc = pipeline.main([
        "--input-dir", str(tmp_dir),
        "--output-dir", str(output_dir),
        "--patient-id", "P_TEST",
        "--format", "html",
        "--open",
    ])

    assert rc == 0
    assert opened == [f"file://{output_dir / 'case_report.html'}"]
