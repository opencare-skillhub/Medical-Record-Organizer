"""
v2 Shuffle 层

职责：
- 按 report_type 分组
- 按 report_date 排序
- 合并检验指标趋势
- 规范化 Map 输出字段名，适配 Reduce 阶段
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 字段名规范化
# ---------------------------------------------------------------------------

def _normalize_report(item: Dict[str, Any]) -> Dict[str, Any]:
    """把 Map 层的异构字段名规约到统一 schema，方便下游 Shuffle/Reduce 消费。"""
    normalized = dict(item)
    rt = normalized.get("report_type", "other") or "other"

    # 兜底：有些 LLM 会把 report_type 输出成空格键 " "
    if rt == " " or rt.strip() == "":
        # 尝试从 items/noise 推断类型
        items = normalized.get("items", [])
        if items and any("test_name" in str(i) or "result" in str(i) for i in items):
            rt = "lab"
        elif items and any("gene_name" in str(i) for i in items):
            rt = "pathology"
        elif items and any("category" in str(i) and "amount" in str(i) for i in items):
            rt = "other"
        else:
            rt = "other"
        normalized["report_type"] = rt

    # 检验报告：兼容多种异构字段名
    if rt == "lab":
        # items + name/result/unit/reference_range (常见 LLM 输出)
        if not normalized.get("lab_values") and not normalized.get("lab_tests"):
            raw_items = normalized.get("items", [])
            lab_values = []
            for it in raw_items:
                if not isinstance(it, dict):
                    continue
                name = (it.get("name") or it.get("test_name") or "").strip()
                result = it.get("result") or it.get("value") or ""
                unit = it.get("unit") or ""
                ref_range = it.get("reference_range") or ""
                if not name and not result:
                    continue
                ref_low, ref_high = _parse_ref_range(ref_range)
                abnormal = it.get("is_abnormal")
                if abnormal is None and ref_low is not None and ref_high is not None:
                    try:
                        abnormal = float(result) < ref_low or float(result) > ref_high
                    except (ValueError, TypeError):
                        abnormal = False
                lab_values.append({
                    "name": name,
                    "value": result,
                    "unit": unit,
                    "ref_low": ref_low,
                    "ref_high": ref_high,
                    "abnormal": abnormal,
                })
            if lab_values:
                normalized["lab_values"] = lab_values
        # test_results -> lab_values (Schema 格式)
        if not normalized.get("lab_values") and normalized.get("test_results"):
            lab_values = []
            for tr in normalized.get("test_results", []):
                name = (tr.get("test_name") or "").strip()
                if not name:
                    continue
                ref_range = tr.get("reference_range") or ""
                ref_low, ref_high = _parse_ref_range(ref_range)
                abnormal = tr.get("is_abnormal")
                if abnormal is None and ref_low is not None and ref_high is not None:
                    try:
                        abnormal = float(tr.get("value", 0)) < ref_low or float(tr.get("value", 0)) > ref_high
                    except (ValueError, TypeError):
                        abnormal = False
                lab_values.append({
                    "name": name,
                    "value": tr.get("value", ""),
                    "unit": tr.get("unit", ""),
                    "ref_low": ref_low,
                    "ref_high": ref_high,
                    "abnormal": abnormal,
                })
            normalized["lab_values"] = lab_values

    # 影像报告：diagnostic_impression -> findings
    if rt == "imaging":
        findings = []
        for di in normalized.get("diagnostic_impression", []) or []:
            if isinstance(di, str):
                findings.append(di)
            elif isinstance(di, dict):
                findings.append(di.get("text") or di.get("impression") or str(di))
        if findings and not normalized.get("findings"):
            normalized["findings"] = findings

    # 统一 report_date：支持 "2025-8-28 0:00:00" 这种格式
    raw_date = normalized.get("report_date", "") or ""
    normalized["report_date"] = _normalize_date(raw_date)
    
    # 如果 LLM 没提取到日期，尝试从文件名提取
    if not normalized.get("report_date"):
        source_file = normalized.get("_source_file", "") or ""
        filename_date = _extract_date_from_filename(source_file)
        if filename_date:
            normalized["report_date"] = filename_date

    return normalized


def _parse_ref_range(ref_range: str):
    """解析参考范围字符串，返回 (low, high) 或 (None, None)。"""
    if not ref_range:
        return None, None
    import re
    m = re.search(r"([0-9.]+)\s*[-–—]\s*([0-9.]+)", ref_range)
    if m:
        try:
            return float(m.group(1)), float(m.group(2))
        except (ValueError, TypeError):
            pass
    return None, None


def _normalize_date(raw: str) -> str:
    """把常见日期格式统一成 YYYY-MM-DD。"""
    raw = raw.strip()
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw


def _extract_date_from_filename(filename: str) -> str:
    """从文件名中提取日期，支持常见格式。"""
    import re
    # 匹配 YYYY-MM-DD 或 YYYY/MM/DD 或 YYYYMMDD
    patterns = [
        r'(\d{4}-\d{2}-\d{2})',
        r'(\d{4}/\d{2}/\d{2})',
        r'(\d{8})',
        r'(\d{4}年\d{1,2}月\d{1,2}日)',
    ]
    for pattern in patterns:
        match = re.search(pattern, filename)
        if match:
            date_str = match.group(1)
            # 标准化格式
            date_str = date_str.replace('/', '-')
            if len(date_str) == 8 and '-' not in date_str:
                date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            return date_str
    return ""


def _normalize_batch(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_normalize_report(it) for it in items]


# ---------------------------------------------------------------------------
# 分组 & 合并
# ---------------------------------------------------------------------------

def group_by_type(extracted: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """按 report_type 分组，每组按 report_date 排序。"""
    normalized = _normalize_batch(extracted)
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in normalized:
        rt = item.get('report_type', 'other') or 'other'
        groups[rt].append(item)
    for rt in groups:
        groups[rt].sort(key=lambda x: x.get('report_date', '') or '')
    return dict(groups)


def merge_lab_trends(lab_group: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把多份检验报告的同一指标合并成时间序列。"""
    trends: Dict[str, Any] = defaultdict(lambda: {'unit': '', 'ref_range': None, 'trend': []})

    for report in lab_group:
        date = report.get('report_date', '') or ''
        for lv in report.get('lab_values', []) or []:
            name = (lv.get('name') or '').strip()
            if not name:
                continue
            if not trends[name]['unit'] and lv.get('unit'):
                trends[name]['unit'] = lv['unit']
            ref_low = lv.get('ref_low')
            ref_high = lv.get('ref_high')
            if ref_low is not None and ref_high is not None:
                trends[name]['ref_range'] = [ref_low, ref_high]
            trends[name]['trend'].append({
                'date': date,
                'value': lv.get('value'),
                'unit': lv.get('unit'),
                'abnormal': lv.get('abnormal'),
                'source': report.get('_source_file', ''),
            })

    for name in trends:
        trends[name]['trend'].sort(key=lambda x: x.get('date', '') or '')

    return dict(trends)
