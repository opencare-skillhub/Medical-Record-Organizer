"""
脱敏工具测试
"""
from __future__ import annotations

import pytest

from scripts.desensitize import (
    desensitize_text,
    desensitize_manifest,
    desensitize_file_list,
    desensitize_for_output,
)


def test_desensitize_text_id_card():
    text = "患者，身份证号110101199001011234，前来就诊。"
    result = desensitize_text(text)
    assert "110101199001011234" not in result
    assert "***身份证***" in result


def test_desensitize_text_phone():
    text = "联系电话：13812345678"
    result = desensitize_text(text)
    assert "13812345678" not in result
    assert "***手机***" in result


def test_desensitize_text_medical_record_number():
    text = "住院号：Z20240315001"
    result = desensitize_text(text)
    # 病历号应被脱敏
    assert "Z20240315001" not in result


def test_desensitize_manifest_name():
    m = {
        "demographics": {
            "name": "张三丰",
            "age": 62,
            "gender": "男",
        },
        "files": [],
    }
    result = desensitize_manifest(m)
    assert result["demographics"]["name"] == "张**"


def test_desensitize_manifest_single_char_name():
    m = {"demographics": {"name": "李", "age": 30}, "files": []}
    result = desensitize_manifest(m)
    assert result["demographics"]["name"] == "*"


def test_desensitize_file_list():
    files = [
        {"original_name": "张三_血常规.jpg", "title": "张三的血常规报告"},
        {"original_name": "CT报告.pdf", "title": "胸部CT"},
    ]
    result = desensitize_file_list(files)
    assert "张三" not in result[0]["original_name"]
    assert "张三" not in result[0]["title"]
    assert result[1]["original_name"] == "CT报告.pdf"  # 无 PHI，不变


def test_desensitize_for_output_full():
    m = {
        "demographics": {"name": "张三丰", "age": 62, "gender": "男"},
        "files": [
            {"original_name": "张三_血常规.jpg", "title": "张三的血常规", "date_detected": "2024-03-15"},
        ],
    }
    result = desensitize_for_output(m)
    assert result["demographics"]["name"] == "张**"
    assert "张三" not in result["files"][0]["original_name"]


# Fix 9：医疗术语不应被误脱敏
def test_desensitize_preserves_medical_terms():
    text = "患者：李华，诊断：肺腺癌。建议行胸部CT平扫。"
    result = desensitize_text(text)
    # 医疗术语应保留
    assert "肺腺癌" in result, "医疗术语不应被误脱敏"
    assert "胸部CT" in result, "影像检查术语不应被误脱敏"
    # 姓名应被脱敏
    assert "李华" not in result
