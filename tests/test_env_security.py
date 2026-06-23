"""
环境与忽略规则安全测试
"""
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_gitignore_ignores_secrets_and_sensitive_outputs():
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    required = [
        ".env",
        ".env.*",
        "!.env.example",
        "extracted/",
        "output/",
        "patients/",
        "*.html",
        "*.pdf",
        "*.docx",
    ]
    for pattern in required:
        assert pattern in text


def test_env_example_contains_only_placeholder_secrets():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    uncommented = "\n".join(
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )

    assert not re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", uncommented)
    assert not re.search(r"sk-[A-Za-z0-9]{16,}", uncommented)
    assert "your-" in uncommented or "xxxxxxxx" in uncommented
