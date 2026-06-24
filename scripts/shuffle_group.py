"""
Shuffle 层

职责：
- 按 report_type 分组（data-contract.md 枚举 → 分组键）
- 按 document_date 排序
- 合并检验指标趋势（优先 lab_values，回退 lab_tests 嵌套）

对应 dev/docs/data-contract.md。
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 枚举 → 分组键映射（data-contract.md）
# ---------------------------------------------------------------------------
_REPORT_TYPE_TO_GROUP = {
    'lab_results': 'lab',
    'imaging': 'imaging',
    'pathology': 'pathology',
    'medication': 'medication',
    'clinical_records': 'clinical',
    'basic_info': 'demographics',
    'invoice': 'noise',
    'noise': 'noise',
}

# 旧枚举值（向后兼容）→ 新枚举值
_LEGACY_TYPE_MAP = {
    'lab': 'lab_results',
    'clinical': 'clinical_records',
    'other': 'noise',
}


# ---------------------------------------------------------------------------
# 日期处理
# ---------------------------------------------------------------------------
def _parse_ref_range(ref_range: str) -> Tuple[Optional[float], Optional[float]]:
    """解析参考范围字符串，返回 (low, high) 或 (None, None)。"""
    if not ref_range:
        return None, None
    m = re.search(r'([0-9.]+)\s*[-–—~]\s*([0-9.]+)', ref_range)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except (ValueError, TypeError):
            pass
    return None, None


def _normalize_date(raw: str) -> str:
    """把常见日期格式统一成 YYYY-MM-DD。"""
    raw = (raw or '').strip()
    if not raw:
        return ''
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw


def _extract_date_from_filename(filename: str) -> str:
    """从文件名中提取日期，支持常见格式。"""
    patterns = [
        r'(\d{4}-\d{2}-\d{2})',
        r'(\d{4}/\d{2}/\d{2})',
        r'(\d{8})',
    ]
    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            date_str = match.group(1).replace('/', '-')
            if len(date_str) == 8 and '-' not in date_str:
                date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            return date_str
    return ''


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------
def _normalize_report(item: Dict[str, Any]) -> Dict[str, Any]:
    """把 Map 层输出规约到统一 schema，方便下游消费。

    主要工作：
    1. report_type 枚举归一（legacy 值 → data-contract 枚举）
    2. document_date / report_date 双向兼容
    3. lab_values 展平（兼容 items / test_results / lab_tests 嵌套）
    4. 日期兜底从文件名提取
    """
    normalized = dict(item)

    # 1. report_type 归一
    rt = (normalized.get('report_type') or '').strip()
    if rt in _LEGACY_TYPE_MAP:
        rt = _LEGACY_TYPE_MAP[rt]
    if not rt:
        # 尝试从 items 推断
        items = normalized.get('items', []) or []
        if items and isinstance(items, list) and any(
            isinstance(i, dict) and (i.get('test_name') or i.get('name')) for i in items
        ):
            rt = 'lab_results'
        elif normalized.get('lab_values') or normalized.get('lab_tests'):
            rt = 'lab_results'
        elif normalized.get('medications'):
            rt = 'medication'
        else:
            rt = 'noise'
    normalized['report_type'] = rt

    # 2. document_date / report_date 双向兼容
    raw_date = normalized.get('document_date') or normalized.get('report_date') or ''
    normalized['document_date'] = _normalize_date(raw_date)
    normalized['report_date'] = normalized['document_date']  # 双写，保持兼容
    if not normalized['document_date']:
        source_file = normalized.get('_source_file', '') or ''
        filename_date = _extract_date_from_filename(source_file)
        if filename_date:
            normalized['document_date'] = filename_date
            normalized['report_date'] = filename_date

    # 3. lab_values 展平
    if rt == 'lab_results':
        normalized['lab_values'] = _flatten_lab_values(normalized)

    # 4. imaging findings 归一
    if rt == 'imaging':
        findings = normalized.get('findings')
        if not findings and normalized.get('imaging'):
            imaging_list = normalized['imaging'] or []
            if isinstance(imaging_list, list):
                flat = []
                for im in imaging_list:
                    if isinstance(im, dict):
                        if im.get('findings'):
                            flat.append(im['findings'])
                        if im.get('conclusion'):
                            flat.append(im['conclusion'])
                    elif isinstance(im, str):
                        flat.append(im)
                normalized['findings'] = flat

    return normalized


def _flatten_lab_values(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把各种异构的检验字段归约成统一的 lab_values 数组。

    优先级：lab_values > test_results > items > lab_tests.*（嵌套回退）
    """
    # 优先使用已有的 lab_values
    existing = item.get('lab_values') or []
    if existing and isinstance(existing, list):
        return [_normalize_lab_item(lv, item.get('document_date') or item.get('report_date')) for lv in existing]

    # test_results（旧 schema）
    test_results = item.get('test_results') or []
    if test_results and isinstance(test_results, list):
        return [
            _normalize_lab_item({
                'name': tr.get('test_name') or tr.get('name'),
                'value': tr.get('value') or tr.get('result'),
                'unit': tr.get('unit'),
                'ref_low': tr.get('ref_low'),
                'ref_high': tr.get('ref_high'),
                'abnormal': tr.get('is_abnormal'),
            }, item.get('document_date') or item.get('report_date'))
            for tr in test_results
            if isinstance(tr, dict) and (tr.get('test_name') or tr.get('name'))
        ]

    # items（LLM 常见输出）
    items = item.get('items') or []
    if items and isinstance(items, list):
        result = []
        for it in items:
            if not isinstance(it, dict):
                continue
            name = it.get('name') or it.get('test_name')
            if not name:
                continue
            result.append(_normalize_lab_item({
                'name': name,
                'value': it.get('result') or it.get('value'),
                'unit': it.get('unit'),
                'ref_low': it.get('ref_low'),
                'ref_high': it.get('ref_high'),
                'abnormal': it.get('is_abnormal'),
            }, item.get('document_date') or item.get('report_date')))
        if result:
            return result

    # lab_tests 嵌套回退
    lab_tests = item.get('lab_tests') or {}
    if isinstance(lab_tests, dict):
        result = []
        for _category, arr in lab_tests.items():
            if not isinstance(arr, list):
                continue
            for it in arr:
                if not isinstance(it, dict):
                    continue
                name = it.get('name') or it.get('test_name')
                if not name:
                    continue
                result.append(_normalize_lab_item({
                    'name': name,
                    'value': it.get('value') or it.get('result'),
                    'unit': it.get('unit'),
                    'ref_low': it.get('ref_low'),
                    'ref_high': it.get('ref_high'),
                    'abnormal': it.get('is_abnormal'),
                }, it.get('date') or item.get('document_date') or item.get('report_date')))
        if result:
            return result

    return []


def _normalize_lab_item(raw: Dict[str, Any], fallback_date: str = '') -> Dict[str, Any]:
    """归一化单个检验项，补全 ref_range 和 abnormal。"""
    name = (str(raw.get('name') or '')).strip()
    value = raw.get('value')
    unit = (str(raw.get('unit') or '')).strip()
    ref_low = raw.get('ref_low')
    ref_high = raw.get('ref_high')
    abnormal = raw.get('abnormal')
    date = raw.get('date') or fallback_date or ''

    # 从 reference_range 字符串解析
    if ref_low is None and ref_high is None:
        ref_range_str = raw.get('reference_range') or raw.get('ref_range') or ''
        ref_low, ref_high = _parse_ref_range(ref_range_str)

    # 推断 abnormal
    if abnormal is None and ref_low is not None and ref_high is not None and value is not None:
        try:
            abnormal = float(value) < ref_low or float(value) > ref_high
        except (ValueError, TypeError):
            abnormal = None

    # 计算 flag
    flag = _compute_flag(value, ref_low, ref_high, abnormal)

    return {
        'name': name,
        'value': value,
        'unit': unit,
        'date': _normalize_date(date),
        'ref_low': ref_low,
        'ref_high': ref_high,
        'abnormal': abnormal,
        'flag': flag,
    }


def _compute_flag(value: Any, ref_low: Optional[float], ref_high: Optional[float], abnormal: Optional[bool]) -> str:
    """计算异常标志：'↑' / '↓' / '→' / ''"""
    if value is None:
        return ''
    try:
        v = float(value)
    except (ValueError, TypeError):
        return '→' if abnormal else ''
    if ref_low is not None and v < ref_low:
        return '↓'
    if ref_high is not None and v > ref_high:
        return '↑'
    return ''


def _normalize_batch(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_normalize_report(it) for it in items]


# ---------------------------------------------------------------------------
# 分组 & 合并
# ---------------------------------------------------------------------------
def group_by_type(extracted: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """按 report_type 分组，每组按 document_date 排序。

    invoice/noise 归到 'noise' 组（下游跳过）。
    """
    normalized = _normalize_batch(extracted)
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in normalized:
        rt = item.get('report_type', 'noise') or 'noise'
        group_key = _REPORT_TYPE_TO_GROUP.get(rt, 'noise')
        groups[group_key].append(item)
    for key in groups:
        groups[key].sort(key=lambda x: x.get('document_date', '') or x.get('report_date', '') or '')
    return dict(groups)


def merge_lab_trends(lab_group: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把多份检验报告的同一指标合并成时间序列。

    输出格式（data-contract.md Reduce 消费约定）：
        {indicator: {unit, ref_range, trend[{date, value, unit, abnormal, flag, source}]}}
    """
    trends: Dict[str, Any] = defaultdict(lambda: {'unit': '', 'ref_range': None, 'trend': []})

    for report in lab_group:
        date = report.get('document_date') or report.get('report_date') or ''
        lab_values = report.get('lab_values') or []
        if not lab_values:
            continue
        for lv in lab_values:
            if not isinstance(lv, dict):
                continue
            name = (lv.get('name') or '').strip()
            if not name:
                continue
            if not trends[name]['unit'] and lv.get('unit'):
                trends[name]['unit'] = lv['unit']
            ref_low = lv.get('ref_low')
            ref_high = lv.get('ref_high')
            if ref_low is not None and ref_high is not None:
                trends[name]['ref_range'] = (ref_low, ref_high)
            trends[name]['trend'].append({
                'date': lv.get('date') or date,
                'value': lv.get('value'),
                'unit': lv.get('unit'),
                'abnormal': lv.get('abnormal'),
                'flag': lv.get('flag', ''),
                'source': report.get('_source_file', ''),
            })

    for name in trends:
        trends[name]['trend'].sort(key=lambda x: x.get('date', '') or '')

    return dict(trends)
