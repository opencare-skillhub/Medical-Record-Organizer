#!/usr/bin/env python3
"""
依赖自检（preflight）。

用途：技能包新部署后，跑一次确认环境就绪；缺失给明确安装命令而非静默失败。
  - 必需 Python 包（requirements.txt）缺失 → 提示 pip install
  - 可选离线 OCR：pytesseract 包 + tesseract 系统二进制 + chi_sim 语言包
  - 核心 .env 变量（云端 OCR/LLM key）是否配置

退出码：
  0  全部就绪（可选依赖缺失只 warning，不 fail）
  2  必需依赖缺失
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


# 必需 Python 包（import 名, pip 名）
_REQUIRED_PACKAGES: List[Tuple[str, str]] = [
    ('fitz', 'PyMuPDF'),
    ('jinja2', 'Jinja2'),
    ('requests', 'requests'),
    ('openai', 'openai'),
    ('dotenv', 'python-dotenv'),
]

# 可选离线 OCR 包
_OPTIONAL_PACKAGES: List[Tuple[str, str]] = [
    ('pytesseract', 'pytesseract'),
    ('PIL', 'Pillow'),
]

# 核心 env 变量（任一满足即 OK）
_ENV_GROUPS = [
    ('MinerU OCR', [('MINERU_API_KEY',), ('MINERU_TOKEN',)]),
    ('SiliconFlow DeepSeek-OCR / LLM', [('OCR_API_KEY',), ('SILICONFLOW_API_KEY',)]),
    ('StepFun ASR', [('STEP_API_KEY',)]),
]


def _check_python_packages(packages: List[Tuple[str, str]]) -> List[str]:
    """返回缺失包的 pip 安装名列表。"""
    missing: List[str] = []
    for imp_name, pip_name in packages:
        try:
            importlib.import_module(imp_name)
        except ImportError:
            missing.append(pip_name)
    return missing


def _check_tesseract_binary() -> Tuple[bool, bool]:
    """返回 (tesseract 在 PATH, chi_sim 语言包可用)。"""
    if not shutil.which('tesseract'):
        return False, False
    # 检测 chi_sim 语言包
    try:
        out = subprocess.run(
            ['tesseract', '--list-langs'], capture_output=True, text=True, timeout=10
        )
        langs = (out.stdout or '') + (out.stderr or '')
        return True, 'chi_sim' in langs
    except Exception:
        return True, False


def _check_env() -> List[str]:
    """返回未满足的环境变量组描述。"""
    missing: List[str] = []
    for label, alternatives in _ENV_GROUPS:
        ok = any(any(os.getenv(k) for k in alt) for alt in alternatives)
        if not ok:
            keys = ' 或 '.join('/'.join(alt) for alt in alternatives)
            missing.append(f'{label}（需 {keys}）')
    return missing


def main() -> int:
    rc = 0
    print("=" * 60)
    print("  Patient Record Organizer — 依赖自检 (preflight)")
    print("=" * 60)

    # 加载 .env（若存在），使 env 检测反映真实运行配置
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).resolve().parent.parent / ".env"
        if env_path.exists():
            load_dotenv(str(env_path), override=True)
    except ImportError:
        pass

    # 1. 必需 Python 包
    print("\n[1] 必需 Python 包（requirements.txt）")
    missing_req = _check_python_packages(_REQUIRED_PACKAGES)
    if missing_req:
        print(f"  ❌ 缺失：{', '.join(missing_req)}")
        print(f"     请运行: pip install -r requirements.txt")
        rc = 2
    else:
        print("  ✅ 全部就绪")

    # 2. 可选离线 OCR
    print("\n[2] 可选离线 OCR 兜底（requirements-ocr.txt）")
    missing_opt = _check_python_packages(_OPTIONAL_PACKAGES)
    if missing_opt:
        print(f"  ⚠️  缺失 Python 包：{', '.join(missing_opt)}")
        print("     离线 OCR 默认不可用（云端 MinerU/SF 仍正常）")
        print("     如需离线兜底: pip install -r requirements-ocr.txt")
    else:
        print("  ✅ pytesseract/Pillow 已安装")
        # 进一步检测 tesseract 二进制
        has_bin, has_chi = _check_tesseract_binary()
        if not has_bin:
            print("  ⚠️  未检测到 tesseract 系统二进制")
            print("     macOS:    brew install tesseract tesseract-lang")
            print("     Debian/Ubuntu: sudo apt-get install tesseract-ocr tesseract-ocr-chi-sim")
            print("     离线 OCR 不可用，但不影响云端主链路")
        elif not has_chi:
            print("  ⚠️  tesseract 已装但缺 chi_sim 中文语言包")
            print("     macOS: brew install tesseract-lang")
            print("     Debian/Ubuntu: sudo apt-get install tesseract-ocr-chi-sim")
            print("     离线 OCR 中文识别受限")
        else:
            print("  ✅ tesseract + chi_sim 就绪，离线 OCR 可用")

    # 3. 核心 env
    print("\n[3] 核心 .env 配置")
    missing_env = _check_env()
    if missing_env:
        for m in missing_env:
            print(f"  ⚠️  未配置：{m}")
        print("     参考 .env.example 填写；缺失将导致对应云端服务不可用")
    else:
        print("  ✅ 关键 key 已配置")

    print("\n" + "=" * 60)
    if rc == 0:
        print("  ✅ 必需依赖就绪，可运行 xyb process")
    else:
        print("  ❌ 必需依赖缺失，请先按提示安装")
    print("=" * 60)
    return rc


if __name__ == '__main__':
    raise SystemExit(main())