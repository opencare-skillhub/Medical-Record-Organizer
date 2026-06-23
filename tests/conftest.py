"""
pytest 共享配置 / fixtures
"""
from pathlib import Path
import tempfile
import pytest


@pytest.fixture
def tmp_dir() -> Path:
    """提供一个临时目录（Path），测试结束后自动清理"""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)
