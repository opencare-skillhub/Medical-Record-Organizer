"""
v2 脱敏层

职责：
- 对原始医疗文本做本地正则脱敏，输出可安全送 LLM 的文本
- 生成 mapping.json，供后续回填使用
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Tuple


# 医疗术语白名单，避免误脱敏
MEDICAL_TERMS = {
    '肺腺癌', '鳞癌', '小细胞肺癌', '非小细胞肺癌', '浸润性', '周围型',
    '血常规', '生化', '肝功能', '肾功能', '凝血功能', '肿瘤标志物',
    '胸部CT', '增强CT', '胸部平扫', '胸部增强', 'CT平扫', 'CT增强',
    '出院', '住院', '门诊', '手术', '化疗', '放疗', '靶向', '免疫治疗',
    '出院小结', '门诊记录', '住院记录', '手术记录', '化疗小结',
    'CEA', 'CA199', 'CA125', 'AFP', 'PSA',
}

DESENSITIZE_PATTERNS: List[Tuple[str, str]] = [
    # 邮箱
    (r'[\w.+-]+@[\w-]+\.[\w.-]+', 'EMAIL'),
    # 身份证号（必须在手机号/座机前，避免长数字被拆分）
    (r'[1-9]\d{16}[\dXx]', 'ID'),
    # 手机号（11位，1开头）：不使用 \b，因为中文文本中中文字符也属于 \w
    (r'1[3-9]\d{9}', 'PHONE'),
    # 座机（区号+号码，可选扩展）
    (r'0\d{2,3}[-\s]?\d{7,8}(-\d+)?', 'PHONE'),
    # 病历号/住院号/门诊号（常见前缀 + 数字）
    (r'(?:门诊号|住院号|病历号|病案号|病历号)[：:\s]*\d+', 'MRN'),
    # 地址（简化：包含省市县镇村路街号的序列）
    (r'[\u4e00-\u9fa5]{2,}(?:省|市|区|县|路|街|号|弄|室)\d*', 'ADDRESS'),
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
    # 文件名/路径中的 2-4 字中文名（无前缀时兜底）
    r'(?<=[_-])[\u4e00-\u9fa5]{2,4}(?=[_-])',
]


def _protect_medical_terms(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """用占位符临时保护医疗术语，避免被其他正则误伤。"""
    placeholders: List[Tuple[str, str]] = []
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

    sanitized = text

    # 第一步：先处理 MRN / ID / PHONE / EMAIL / CARD / ADDRESS
    # （这些模式可能包含医疗术语片段，必须在保护医疗术语之前处理）
    for pattern, label in DESENSITIZE_PATTERNS:
        if label == 'MRN':
            def _replace(m: re.Match, lbl: str = label) -> str:
                original = m.group(0)
                counters[lbl] = counters.get(lbl, 0) + 1
                placeholder = f'[{lbl}_{counters[lbl]}]'
                mapping[placeholder] = original
                return placeholder
            sanitized = re.sub(pattern, _replace, sanitized)

    # 第二步：保护医疗术语（防止姓名等正则误伤医疗术语）
    sanitized, term_placeholders = _protect_medical_terms(sanitized)

    # 第三步：处理剩余模式（ID / PHONE / EMAIL / CARD / ADDRESS）
    for pattern, label in DESENSITIZE_PATTERNS:
        if label == 'MRN':
            continue  # 已在第一步处理
        def _replace(m: re.Match, lbl: str = label) -> str:
            original = m.group(0)
            counters[lbl] = counters.get(lbl, 0) + 1
            placeholder = f'[{lbl}_{counters[lbl]}]'
            mapping[placeholder] = original
            return placeholder
        sanitized = re.sub(pattern, _replace, sanitized)

    # 第四步：姓名单独处理
    for pattern in _NAME_PATTERNS:
        def _replace_name(m: re.Match, p: str = pattern) -> str:
            original = m.group(1) if m.lastindex else m.group(0)
            counters['NAME'] = counters.get('NAME', 0) + 1
            placeholder = f'[NAME_{counters["NAME"]}]'
            mapping[placeholder] = original
            return placeholder
        sanitized = re.sub(pattern, _replace_name, sanitized)

    # 第五步：还原医疗术语
    sanitized = _restore_medical_terms(sanitized, term_placeholders)
    return sanitized, mapping


def restore(text: str, mapping: Dict[str, str]) -> str:
    """根据 mapping 回填原始值"""
    for placeholder, original in mapping.items():
        text = text.replace(placeholder, original)
    return text


def desensitize_file(
    input_path: str,
    output_path: str,
    mapping_path: str,
) -> Dict[str, str]:
    """脱敏单个文件，写入 output_path 和 mapping_path，返回映射表。"""
    text = Path(input_path).read_text(encoding='utf-8')
    sanitized, mapping = desensitize(text)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(sanitized, encoding='utf-8')
    Path(mapping_path).parent.mkdir(parents=True, exist_ok=True)
    Path(mapping_path).write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    return mapping


def desensitize_directory(
    dir_path: str,
    output_dir: str,
) -> Dict[str, Dict[str, str]]:
    """批量脱敏目录下所有文本文件，写入 output_dir，返回 {filename: mapping}。"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    all_mappings: Dict[str, Dict[str, str]] = {}

    for p in sorted(Path(dir_path).rglob('*')):
        if p.is_file() and p.suffix.lower() in {'.txt', '.md', '.json'}:
            text = p.read_text(encoding='utf-8')
            sanitized, mapping = desensitize(text)
            out_file = Path(output_dir) / p.name
            out_file.write_text(sanitized, encoding='utf-8')
            all_mappings[p.name] = mapping

    return all_mappings
