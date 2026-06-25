"""
CLI 验收测试：xyb 入口与 process 子命令

覆盖：
  - xyb process 不再 ModuleNotFoundError（已从 scripts.v2.pipeline_v2 导入）
  - process --help 正常
  - process 调用透传到 v2 run_pipeline（mock）
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_XYB = _PROJECT_ROOT / "xyb"


def _load_xyb():
    """以脚本方式加载 xyb（无 .py 后缀，用 runpy 执行）。"""
    return runpy.run_path(str(_XYB), run_name="xyb_cli")


def test_xyb_process_imports_v2_pipeline():
    """xyb 能加载且 process 子命令走 v2 pipeline，不再 ModuleNotFoundError。"""
    xyb = _load_xyb()
    from scripts.v2.pipeline_v2 import run_pipeline
    assert callable(run_pipeline)
    parser = xyb["_build_parser"]()
    # process 是注册的子命令
    assert "process" in parser._subparsers._group_actions[0].choices


def test_xyb_process_help_runs_without_error(capsys):
    """python3 xyb process --help 正常退出并包含 --skip-ocr。"""
    with pytest.raises(SystemExit) as exc:
        _load_xyb()["main"](["process", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--skip-ocr" in out
    assert "source" in out


def test_xyb_process_routes_to_v2_run_pipeline(tmp_path, monkeypatch):
    """xyb process SOURCE 应调用 scripts.v2.pipeline_v2.run_pipeline。"""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.md").write_text("姓名：张三", encoding="utf-8")
    output_dir = tmp_path / "output"

    called = {}

    def fake_run_pipeline(input_dir, output_dir, **kwargs):
        called["input_dir"] = input_dir
        called["output_dir"] = output_dir
        called["patient_id"] = kwargs.get("patient_id")
        called["skip_ocr"] = kwargs.get("skip_ocr")
        return {"patient_id": kwargs.get("patient_id", "P"), "file_count": 1}

    monkeypatch.setattr("scripts.v2.pipeline_v2.run_pipeline", fake_run_pipeline)
    # 跳过 preflight 避免依赖本机 env/可选包
    rc = _load_xyb()["main"]([
        "process", str(input_dir),
        "--patient", "P_TEST",
        "--output-dir", str(output_dir),
        "--skip-ocr",
        "--skip-preflight",
    ])
    assert rc == 0
    assert called["patient_id"] == "P_TEST"
    assert called["skip_ocr"] is True


def test_xyb_preflight_subcommand_exists(monkeypatch):
    """xyb preflight 子命令应注册并可调用（mock 掉实际检测）。"""
    rc_holder = {}
    monkeypatch.setattr(
        "scripts.preflight.main",
        lambda: rc_holder.setdefault("rc", 0),
        raising=False,
    )
    rc = _load_xyb()["main"](["preflight"])
    # 允许返回非0（本机未装有 tesseract），但不应该抛异常
    assert rc in (0, 2)