"""
v2 Reduce 层

职责：
- 对检验组做趋势分析
- 对用药组重建化疗时间线（含去重）
- 对影像组生成病灶演变叙事
- alert_level 字符串规范化（C5）
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from scripts.v2.llm_client import call_llm_with_retry

logger = logging.getLogger(__name__)


# alert_level 别名映射（C5）
_ALERT_LEVEL_ALIASES = {
    'high': 'critical',
    'elevated': 'warning',
    'abnormal': 'warning',
    'normal': 'normal',
    'warning': 'warning',
    'critical': 'critical',
}


def normalize_alert_level(raw: str) -> str:
    """规范化 alert_level 字符串。"""
    if not raw:
        return 'normal'
    key = raw.lower().strip()
    return _ALERT_LEVEL_ALIASES.get(key, 'normal')


LAB_REDUCE_PROMPT = """你是临床检验分析师。以下是患者某检验指标在多次随访中的数值（已脱敏）：

指标：{indicator}
单位：{unit}
参考范围：{ref_low} - {ref_high}
趋势数据：
{trend_json}

请判断：
1. trend_summary：整体趋势（持续下降/上升/波动/稳定）
2. alert_level：预警级别（normal/warning/critical）
3. clinical_inference：临床意义推断（治疗反应、病情变化）
4. consecutive_rises：连续上升次数（0 表示无）

输出 JSON。"""

MED_REDUCE_PROMPT = """你是肿瘤化疗药师。以下是患者所有处方/医嘱记录（已脱敏，按时间排序）：

{medications_json}

请重建完整的化疗时间线：
1. regimens：识别的化疗方案（如 AG 方案）
2. cycles：每周期起止日期、用药、剂量、周期编号
3. response_assessments：疗效评估节点（PR/SD/PD）
4. toxicities：副作用记录

输出 JSON。"""

IMAGING_REDUCE_PROMPT = """你是影像科医生。以下是患者所有 CT/MRI 报告（已脱敏，按时间排序）：

{imaging_json}

请生成病灶演变的连贯叙事：
1. primary_lesion_timeline：原发灶变化（大小、密度、强化）
2. metastasis_timeline：转移灶变化（淋巴结、肝、腹膜）
3. overall_response：总体疗效评估

输出 JSON。"""


def _reduce_with_schema(
    prompt: str,
    schema: Dict[str, Any],
    *,
    model: str = 'qwen3-flash',
) -> Dict[str, Any]:
    messages = [{'role': 'user', 'content': prompt}]
    return call_llm_with_retry(messages, schema, model=model)


def reduce_lab_trends(
    trends: Dict[str, Any],
    *,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """对每个检验指标做趋势分析。"""
    results: Dict[str, Any] = {}
    schema = {
        'type': 'object',
        'properties': {
            'trend_summary': {'type': 'string'},
            'alert_level': {'type': 'string'},
            'clinical_inference': {'type': 'string'},
            'consecutive_rises': {'type': 'integer'},
        },
    }
    for indicator, data in trends.items():
        ref = data.get('ref_range') or (None, None)
        prompt = LAB_REDUCE_PROMPT.format(
            indicator=indicator,
            unit=data.get('unit', ''),
            ref_low=ref[0] if isinstance(ref, tuple) and ref[0] is not None else (ref if ref else '未知'),
            ref_high=ref[1] if isinstance(ref, tuple) and ref[1] is not None else '未知',
            trend_json=json.dumps(data.get('trend', []), ensure_ascii=False, indent=2),
        )
        try:
            result = _reduce_with_schema(prompt, schema, model=model)
            # 规范化 alert_level（C5）
            if 'alert_level' in result:
                result['alert_level'] = normalize_alert_level(result['alert_level'])
            results[indicator] = result
        except Exception as exc:
            logger.warning('Reduce lab 失败 %s: %s', indicator, exc)
            results[indicator] = {'error': str(exc), 'indicator': indicator, 'alert_level': 'normal'}
    return results


def reduce_medication_history(
    med_group: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """重建化疗时间线（含去重合并）。"""
    schema = {
        'type': 'object',
        'properties': {
            'regimens': {'type': 'array'},
            'cycles': {'type': 'array'},
            'response_assessments': {'type': 'array'},
            'toxicities': {'type': 'array'},
        },
    }

    # 预处理：合并所有 medications，去重（同名+同期视为同一条）
    all_meds: List[Dict[str, Any]] = []
    seen_keys = set()
    for record in med_group:
        meds = record.get('medications') or []
        record_date = record.get('document_date') or record.get('report_date') or ''
        for med in meds:
            if not isinstance(med, dict):
                continue
            name = med.get('name') or med.get('drug') or ''
            start = med.get('start_date') or record_date or ''
            key = f"{name}|{start}"
            if key in seen_keys or not name:
                continue
            seen_keys.add(key)
            normalized_med = dict(med)
            normalized_med.setdefault('name', name)
            normalized_med.setdefault('start_date', start)
            all_meds.append(normalized_med)

    # 按 start_date 排序
    all_meds.sort(key=lambda m: m.get('start_date', '') or '')

    prompt = MED_REDUCE_PROMPT.format(
        medications_json=json.dumps(all_meds, ensure_ascii=False, indent=2)
    )
    try:
        result = _reduce_with_schema(prompt, schema, model=model)
        # 保留去重后的时间线供下游使用
        result['timeline'] = all_meds
        return result
    except Exception as exc:
        logger.warning('Reduce medication 失败: %s', exc)
        return {'error': str(exc), 'timeline': all_meds}


def reduce_imaging_narrative(
    imaging_group: List[Dict[str, Any]],
    *,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """生成病灶演变叙事。"""
    schema = {
        'type': 'object',
        'properties': {
            'primary_lesion_timeline': {'type': 'array'},
            'metastasis_timeline': {'type': 'array'},
            'overall_response': {'type': 'string'},
        },
    }
    prompt = IMAGING_REDUCE_PROMPT.format(
        imaging_json=json.dumps(imaging_group, ensure_ascii=False, indent=2)
    )
    try:
        return _reduce_with_schema(prompt, schema, model=model)
    except Exception as exc:
        logger.warning('Reduce imaging 失败: %s', exc)
        return {'error': str(exc)}
