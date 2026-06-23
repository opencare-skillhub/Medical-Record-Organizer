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
            'enum': ['lab_results', 'imaging', 'pathology', 'medication', 'clinical_records', 'basic_info', 'invoice', 'noise'],
        },
        'document_date': {'type': 'string', 'description': 'YYYY-MM-DD'},
        'confidence': {'type': 'number'},
        'demographics': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string'},
                'gender': {'type': 'string'},
                'age': {'type': 'number'},
                'medical_record_no': {'type': 'string'},
            },
        },
        'lab_values': {
            'type': 'array',
            'description': '展平格式的检验指标（Shuffle 直接消费）',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'value': {'type': 'number'},
                    'unit': {'type': 'string'},
                    'date': {'type': 'string'},
                    'ref_low': {'type': 'number'},
                    'ref_high': {'type': 'number'},
                    'abnormal': {'type': 'boolean'},
                },
            },
        },
        'lab_tests': {
            'type': 'object',
            'description': '嵌套结构（供下游按需使用）',
            'properties': {
                'tumor_markers': {'type': 'array'},
                'blood_routine': {'type': 'array'},
                'liver_kidney': {'type': 'array'},
            },
        },
        'imaging': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'modality': {'type': 'string'},
                    'date': {'type': 'string'},
                    'findings': {'type': 'string'},
                    'conclusion': {'type': 'string'},
                },
            },
        },
        'medications': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'type': {'type': 'string'},
                    'start_date': {'type': 'string'},
                    'dosage': {'type': 'string'},
                    'dose': {'type': 'string'},
                    'route': {'type': 'string'},
                    'frequency': {'type': 'string'},
                    'purpose': {'type': 'string'},
                },
            },
        },
        'diagnoses': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'stage': {'type': 'string'},
                    'icd10': {'type': 'string'},
                    'subtype': {'type': 'string'},
                    'confirmed_date': {'type': 'string'},
                },
            },
        },
        'findings': {'type': 'array', 'items': {'type': 'string'}},
        'conclusion': {'type': 'string'},
        'procedures': {'type': 'array', 'items': {'type': 'string'}},
        'test_items': {
            'type': 'array',
            'description': '基因检测项目（pathology 类型）',
            'items': {
                'type': 'object',
                'properties': {
                    'gene_name': {'type': 'string'},
                    'detection_result': {'type': 'string'},
                    'category': {'type': 'string'},
                    'is_pathogenic': {'type': 'boolean'},
                    'clinical_significance': {'type': 'string'},
                },
            },
        },
        'noise': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['report_type', 'confidence'],
}

SYSTEM_PROMPT = """你是一名资深病案整理员。下面是一份医疗文件（已脱敏）。
请提取其中的结构化信息。注意：
1. report_type 必须准确，只能从以下枚举值中选择：
   - lab_results：检验报告（血常规/生化/肿瘤标志物/凝血等）
   - imaging：影像检查（CT/MRI/超声/内镜/PET-CT等）
   - pathology：病理报告（组织学/基因检测/免疫组化等）
   - medication：用药/处方/医嘱
   - clinical_records：出院小结/门诊/手术记录
   - basic_info：患者基本信息
   - invoice：发票/收据
   - noise：非医疗内容
2. document_date：报告日期，格式 YYYY-MM-DD。必须提取！如果文件中有明确日期（如
   "2024-12-31"、"2024年3月15日"），请准确提取；不确定则返回空字符串。
3. lab_values：所有检验指标用展平数组输出，每项必须包含 name/value/unit，
   有参考范围时填 ref_low/ref_high/abnormal。
4. medications 数组中每项用 name 字段（不是 drug）。
5. 如某字段在文件中不存在，返回空数组，不要编造。
6. confidence 反映你对该分类的把握（0-1）。"""


def extract_single(
    sanitized_text: str,
    filename: str,
    *,
    model: Optional[str] = None,
    max_chars: int = 12000,
) -> Dict[str, Any]:
    """单文件 LLM 提取。"""
    truncation_note = ''
    if len(sanitized_text) > max_chars:
        truncation_note = f'\n[文本已截断，原始长度 {len(sanitized_text)} 字符]'
        # 保留开头和结尾
        head = sanitized_text[:max_chars - 500]
        tail = sanitized_text[-400:]
        truncated_text = head + '\n...\n' + tail
    else:
        truncated_text = sanitized_text

    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {'role': 'user', 'content': f'文件名：{filename}\n\n内容：\n{truncated_text}{truncation_note}'},
    ]
    result = call_llm_with_retry(messages, EXTRACT_SCHEMA, model=model)
    result.setdefault('report_type', 'noise')
    result.setdefault('confidence', 0.0)
    result['_source_file'] = filename
    # 向后兼容：document_date 也映射到 report_date
    if result.get('document_date') and not result.get('report_date'):
        result['report_date'] = result['document_date']
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
