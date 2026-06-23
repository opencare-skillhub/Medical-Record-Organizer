"""
v2 Map 层

对单份脱敏后的医疗文本做 LLM 结构化提取。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.v2.llm_client import call_llm_with_retry

logger = logging.getLogger(__name__)


EXTRACT_SCHEMA: Dict[str, Any] = {
    'type': 'object',
    'properties': {
        'report_type': {
            'type': 'string',
            'enum': ['lab', 'imaging', 'pathology', 'medication', 'clinical', 'other'],
        },
        'report_date': {'type': 'string'},
        'confidence': {'type': 'number'},
        'diagnoses': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'icd10': {'type': 'string'},
                    'subtype': {'type': 'string'},
                    'confirmed_date': {'type': 'string'},
                },
            },
        },
        'lab_values': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'value': {'type': 'number'},
                    'unit': {'type': 'string'},
                    'ref_low': {'type': 'number'},
                    'ref_high': {'type': 'number'},
                    'abnormal': {'type': 'boolean'},
                },
            },
        },
        'medications': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'drug': {'type': 'string'},
                    'dose': {'type': 'string'},
                    'route': {'type': 'string'},
                    'frequency': {'type': 'string'},
                    'cycle': {'type': 'string'},
                },
            },
        },
        'findings': {'type': 'array', 'items': {'type': 'string'}},
        'procedures': {'type': 'array', 'items': {'type': 'string'}},
        'noise': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['report_type', 'confidence'],
}

SYSTEM_PROMPT = """你是一名资深病案整理员。下面是一份医疗文件（已脱敏）。
请提取其中的结构化信息。注意：
1. report_type 必须准确：检验报告选 lab，CT/MRI/超声选 imaging，病理/基因选 pathology，
   处方/医嘱选 medication，出院/门诊/手术记录选 clinical，非医疗文件选 other。
2. 必须提取报告日期：report_date 字段格式为 YYYY-MM-DD。如果文件中有明确日期（如
   "2024-12-31"、"2024年3月15日"），请准确提取；如果日期不确定，返回空字符串。
3. 数值必须带单位和参考范围（如报告自带）。
4. 如某字段在文件中不存在，返回空数组，不要编造。
5. confidence 反映你对该分类的把握（0-1）。"""


def extract_single(
    sanitized_text: str,
    filename: str,
    *,
    model: Optional[str] = None,
    max_chars: int = 4000,
) -> Dict[str, Any]:
    """单文件 LLM 提取。"""
    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': f'文件名：{filename}\n\n内容：\n{sanitized_text[:max_chars]}'},
    ]
    result = call_llm_with_retry(messages, EXTRACT_SCHEMA, model=model)
    result.setdefault('report_type', 'other')
    result.setdefault('confidence', 0.0)
    result['_source_file'] = filename
    return result


def extract_batch(
    sanitized_dir: str,
    output_dir: str,
    *,
    model: Optional[str] = None,
    max_workers: int = 2,
) -> List[Dict[str, Any]]:
    """批量提取目录下所有脱敏文件。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    md_files = sorted(Path(sanitized_dir).glob('*.md'))

    def process_one(md_file: Path) -> Dict[str, Any]:
        out_path = Path(output_dir) / f'{md_file.stem}.json'
        if out_path.exists():
            try:
                return json.loads(out_path.read_text(encoding='utf-8'))
            except Exception:
                pass
        text = md_file.read_text(encoding='utf-8')
        try:
            result = extract_single(text, md_file.name, model=model)
        except Exception as exc:
            logger.exception('Map 提取失败: %s', md_file)
            result = {
                'report_type': 'error',
                'confidence': 0.0,
                '_source_file': md_file.name,
                'error': str(exc),
            }
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result

    results: List[Dict[str, Any]] = []
    if not md_files:
        return results

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_one, f) for f in md_files]
        for future in as_completed(futures):
            results.append(future.result())

    return results
