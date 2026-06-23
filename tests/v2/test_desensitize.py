"""
v2 脱敏层测试
"""
from __future__ import annotations

import pytest

from scripts.v2.desensitize import (
    desensitize,
    restore,
    desensitize_file,
    desensitize_directory,
)


def test_desensitize_name():
    text = '姓名：秦晓强，性别：男，年龄：49'
    sanitized, mapping = desensitize(text)
    assert '[NAME_1]' in sanitized
    assert '秦晓强' not in sanitized
    assert any('秦晓强' in v for v in mapping.values())


def test_desensitize_phone():
    text = '联系电话：13812345678'
    sanitized, mapping = desensitize(text)
    assert '[PHONE_1]' in sanitized
    assert '13812345678' not in sanitized


def test_desensitize_id_card():
    text = '身份证号：310101199001011234'
    sanitized, mapping = desensitize(text)
    assert '[ID_1]' in sanitized
    assert '310101199001011234' not in sanitized


def test_desensitize_medical_record_no():
    text = '门诊号：11493391'
    sanitized, mapping = desensitize(text)
    assert '[MRN_1]' in sanitized
    assert '11493391' not in sanitized


def test_desensitize_preserves_medical_terms():
    text = '患者姓名：李华，性别：男，诊断：肺腺癌。建议行胸部CT平扫。'
    sanitized, mapping = desensitize(text)
    assert '肺腺癌' in sanitized
    assert '胸部CT' in sanitized
    assert '李华' not in sanitized


def test_restore_roundtrip():
    text = '患者秦晓强（男，49岁），病历号11493391，电话13812345678'
    sanitized, mapping = desensitize(text)
    restored = restore(sanitized, mapping)
    assert '秦晓强' in restored
    assert '13812345678' in restored
    assert '11493391' in restored


def test_desensitize_email():
    text = '联系邮箱：test@example.com'
    sanitized, mapping = desensitize(text)
    assert '[EMAIL_1]' in sanitized
    assert 'test@example.com' not in sanitized


def test_desensitize_multiple_occurrences():
    text = '张三，男，电话13812345678，备用电话13987654321'
    sanitized, mapping = desensitize(text)
    assert '张三' not in sanitized
    assert '13812345678' not in sanitized
    assert '13987654321' not in sanitized


def test_desensitize_directory(tmp_dir):
    (tmp_dir / 'a.md').write_text('姓名：张三，电话13812345678', encoding='utf-8')
    (tmp_dir / 'b.md').write_text('姓名：李四，住院号Z20240315001', encoding='utf-8')

    out_dir = tmp_dir / 'sanitized'
    mappings = desensitize_directory(str(tmp_dir), str(out_dir))

    assert (out_dir / 'a.md').exists()
    assert (out_dir / 'b.md').exists()
    assert '张三' not in (out_dir / 'a.md').read_text(encoding='utf-8')
    assert '13812345678' not in (out_dir / 'a.md').read_text(encoding='utf-8')
    assert 'a.md' in mappings
    assert 'b.md' in mappings


def test_desensitize_file_writes_mapping(tmp_dir):
    src = tmp_dir / 'input.md'
    src.write_text('姓名：王五，年龄：62', encoding='utf-8')
    out = tmp_dir / 'out.md'
    mapping_path = tmp_dir / 'mapping.json'
    mapping = desensitize_file(str(src), str(out), str(mapping_path))

    assert out.exists()
    assert mapping_path.exists()
    assert '王五' not in out.read_text(encoding='utf-8')
    assert mapping_path.exists()
