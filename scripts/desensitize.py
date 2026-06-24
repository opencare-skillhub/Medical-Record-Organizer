"""
脱敏层

职责：
- 对原始医疗文本做本地正则脱敏，输出可安全送 LLM 的文本
- 生成 mapping.json，供后续回填使用
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple


DESENSITIZE_PATTERNS: List[Tuple[str, str]] = [
    # 邮箱
    (r'[\w.+-]+@[\w-]+\.[\w.-]+', 'EMAIL'),
    # 身份证号（必须在手机号/座机前，避免长数字被拆分）
    (r'\d{17}[\dXx]', 'ID'),
    # 银行卡号
    (r'\d{16,19}', 'CARD'),
    # 座机
    (r'0\d{2,3}-?\d{7,8}', 'PHONE'),
    # 手机号
    (r'1[3-9]\d{9}', 'PHONE'),
    # 病历号/住院号（常见前缀 + 数字）
    (r'(?:门诊号|住院号|病历号|病案号|病历号)[：:\s]*\d+', 'MRN'),
    # 地址（简化）
    (r'[\u4e00-\u9fa5]{2,}(?:省|市|区|县|路|街|号|弄|室)\d*', 'ADDR'),
]

# 姓名正则（多种格式）
_NAME_PATTERNS = [
    # 姓名：紧跟性别的 2-4 字汉字
    r'([\u4e00-\u9fa5]{2,4})(?=[\s，,；;。.]{0,2}(?:男|女))',
    # 患者姓名：XXX
    r'(?<=患者姓名[：:\s])[\u4e00-\u9fa5]{2,4}',
    # 姓名：XXX（任何标点/空格后的姓名标记）
    r'(?<=姓名[：:\s])[\u4e00-\u9fa5]{2,4}',
    # 患者：XXX（冒号或空格后的 2-4 字中文名）
    r'(?<=患者[：:\s])[\u4e00-\u9fa5]{2,4}(?=[\s，,。.；;])',
    # 字符串开头的 2-4 字中文名（如文件名/标题前缀）
    r'^[\u4e00-\u9fa5]{2,4}(?=[_\-])',
    # 分隔符后的 2-4 字中文名（文件名/路径中）
    r'(?<=[_\-\s])[\u4e00-\u9fa5]{2,4}(?=[_\-\s])',
    # 所有格/ possessive：XXX的...
    r'(?<![\\u4e00-\\u9fa5])[\u4e00-\u9fa5]{2,4}(?=的)',
]

# 医疗术语白名单，避免误脱敏
MEDICAL_TERMS = {
    '肺腺癌', '鳞癌', '小细胞肺癌', '非小细胞肺癌', '浸润性', '周围型',
    '血常规', '生化', '肝功能', '肾功能', '凝血功能', '肿瘤标志物',
    '胸部CT', '增强CT', '胸部平扫', '胸部增强', 'CT平扫', 'CT增强',
    '出院', '住院', '门诊', '手术', '化疗', '放疗', '靶向', '免疫治疗',
    '出院小结', '门诊记录', '住院记录', '手术记录', '化疗小结',
    'CEA', 'CA199', 'CA125', 'AFP', 'PSA',
}


def _protect_medical_terms(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """用占位符临时保护医疗术语，避免被其他正则误伤。"""
    placeholders: List[Tuple[str, str]] = []
    # 先保护较长的术语，避免短术语被长术语的部分匹配先替换
    for i, term in enumerate(sorted(MEDICAL_TERMS, key=len, reverse=True)):
        placeholder = f'\x00MED{i:04d}\x00'
        if term in text:
            text = text.replace(term, placeholder)
            placeholders.append((placeholder, term))
    return text, placeholders


def _restore_medical_terms(text: str, placeholders: List[Tuple[str, str]]) -> str:
    """还原被保护的医疗术语。"""
    for placeholder, term in placeholders:
        text = text.replace(placeholder, term)
    return text


def desensitize(text: str) -> Tuple[str, Dict[str, str]]:
    """脱敏文本，返回 (脱敏后文本, 映射表)。"""
    mapping: Dict[str, str] = {}
    counters: Dict[str, int] = {}

    # 先保护医疗术语（防止后续正则误伤）
    text, term_placeholders = _protect_medical_terms(text)

    sanitized = text
    for pattern, label in DESENSITIZE_PATTERNS:
        def _replace(m: re.Match, lbl: str = label) -> str:
            original = m.group(0)
            counters[lbl] = counters.get(lbl, 0) + 1
            placeholder = f'[{lbl}_{counters[lbl]}]'
            mapping[placeholder] = original
            return placeholder
        sanitized = re.sub(pattern, _replace, sanitized)

    # 姓名单独处理
    for pattern in _NAME_PATTERNS:
        def _replace_name(m: re.Match, p: str = pattern) -> str:
            original = m.group(1) if m.lastindex else m.group(0)
            counters['NAME'] = counters.get('NAME', 0) + 1
            placeholder = f'[NAME_{counters["NAME"]}]'
            mapping[placeholder] = original
            return placeholder
        sanitized = re.sub(pattern, _replace_name, sanitized)

    # 还原医疗术语
    sanitized = _restore_medical_terms(sanitized, term_placeholders)
    return sanitized, mapping


def restore(sanitized: str, mapping: Dict[str, str]) -> str:
    """用映射表把脱敏文本还原为原始文本。"""
    restored = sanitized
    for placeholder in sorted(mapping.keys(), key=len, reverse=True):
        restored = restored.replace(placeholder, mapping[placeholder])
    return restored


def desensitize_file(input_path: str, output_path: str, mapping_path: str | None = None) -> Dict[str, str]:
    """脱敏单个文件，返回映射表。"""
    text = Path(input_path).read_text(encoding='utf-8')
    sanitized, mapping = desensitize(text)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(sanitized, encoding='utf-8')
    if mapping_path:
        Path(mapping_path).parent.mkdir(parents=True, exist_ok=True)
        Path(mapping_path).write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
    return mapping


def desensitize_directory(input_dir: str, output_dir: str) -> Dict[str, Dict[str, str]]:
    """批量脱敏目录下所有 .md 文件。"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    all_mappings: Dict[str, Dict[str, str]] = {}

    for md_file in sorted(Path(input_dir).glob('*.md')):
        out_file = Path(output_dir) / md_file.name
        mapping_path = Path(output_dir) / f'{md_file.stem}.mapping.json'
        mapping = desensitize_file(str(md_file), str(out_file), str(mapping_path))
        all_mappings[md_file.name] = mapping

    return all_mappings


# ── 兼容层（供 tests/test_desensitize.py 使用）─────────────────

def desensitize_text(text: str, *, keep_name_initials: bool = True) -> str:
    """对一段文本进行脱敏处理（兼容旧接口）"""
    sanitized, _ = desensitize(text)
    return sanitized


def desensitize_manifest(manifest: Dict) -> Dict:
    """对 manifest 中的 PHI 字段进行脱敏"""
    m = dict(manifest)
    demo = dict(m.get("demographics", {}) or {})
    if "name" in demo and demo["name"]:
        name = demo["name"]
        if len(name) > 1:
            demo["name"] = name[0] + "*"   # "张三丰" -> "张*"
        else:
            demo["name"] = "*"
    m["demographics"] = demo
    return m


def desensitize_file_list(files: List[Dict]) -> List[Dict]:
    """对文件列表中的路径/名称进行脱敏"""
    result = []
    for fe in files:
        entry = dict(fe)
        if entry.get("original_name"):
            entry["original_name"] = desensitize_text(entry["original_name"])
        if entry.get("title"):
            entry["title"] = desensitize_text(entry["title"])
        result.append(entry)
    return result


def desensitize_for_output(
    manifest: Dict,
    *,
    desensitize_text: bool = True,
    desensitize_demo: bool = True,
    desensitize_files: bool = True,
) -> Dict:
    """统一入口：对报告输出用的 manifest 副本做脱敏"""
    m = dict(manifest)
    if desensitize_demo:
        m = desensitize_manifest(m)
    if desensitize_files and m.get("files"):
        m["files"] = desensitize_file_list(m["files"])
    return m

