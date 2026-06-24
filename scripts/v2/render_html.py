"""
v2 HTML 报告渲染器（D1）

职责：
- compute_report_context(): 把 v2 profile/groups 转换为 html-report-template.html 所需的 context
- render_html_report(): 用 Jinja2 渲染模板，输出 report.html

对应 dev/docs/template-context.md。
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    _JINJA2_AVAILABLE = True
except ImportError:
    _JINJA2_AVAILABLE = False


# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_TEMPLATE_PATH = _PROJECT_ROOT / 'references' / 'html-report-template.html'

# 肿瘤标志物中文名 → 标准缩写
_MARKER_ALIASES = {
    '癌胚抗原': 'CEA',
    '糖类抗原19-9': 'CA199', '糖类抗原19-9(高值)': 'CA199', 'ca199': 'CA199', 'ca19-9': 'CA199',
    '糖类抗原125': 'CA125', 'ca125': 'CA125',
    '糖类抗原15-3': 'CA153', '糖类抗原153': 'CA153', 'ca15-3': 'CA153', 'ca153': 'CA153',
    '糖类抗原724': 'CA724', '糖类抗原72-4': 'CA724', 'ca724': 'CA724', 'ca72-4': 'CA724',
    '甲胎蛋白': 'AFP', 'afp': 'AFP',
    '前列腺特异性抗原': 'PSA', 'psa': 'PSA',
    '糖类抗原242': 'CA242', 'ca242': 'CA242',
    '糖类抗原50': 'CA50', 'ca50': 'CA50',
}


def _standard_marker_name(name: str) -> str:
    """把中文标志物名映射为标准缩写。"""
    if not name:
        return ''
    lower = name.strip()
    if lower in _MARKER_ALIASES:
        return _MARKER_ALIASES[lower]
    for cn, std in _MARKER_ALIASES.items():
        if cn in lower:
            return std
    # 英文缩写直接保留大写
    if lower.isascii():
        return lower.upper()
    return name


def _is_tumor_marker(name: str) -> bool:
    """判断是否为肿瘤标志物。"""
    std = _standard_marker_name(name)
    return std in {'CEA', 'CA199', 'CA125', 'CA153', 'CA724', 'AFP', 'PSA', 'CA242', 'CA50'}


def _format_change(current: Any, prev: Any) -> str:
    """计算变化格式：'↑ 50 (50%)' / '↓ 10 (5%)' / '—'。"""
    if current is None or prev is None:
        return '—'
    try:
        c = float(current)
        p = float(prev)
    except (ValueError, TypeError):
        return '—'
    if p == 0:
        return f'{"↑" if c > 0 else "↓"} {abs(c):.2f}'
    diff = c - p
    pct = abs(diff) / abs(p) * 100
    arrow = '↑' if diff > 0 else ('↓' if diff < 0 else '→')
    return f'{arrow} {abs(diff):.2f} ({pct:.0f}%)'


# ---------------------------------------------------------------------------
# 核心：compute_report_context
# ---------------------------------------------------------------------------
def compute_report_context(profile: Dict[str, Any], groups: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """把 v2 profile + groups 转换为模板所需的 context dict。

    对应 dev/docs/template-context.md 中的所有变量。
    """
    all_items: List[Dict[str, Any]] = []
    for items in groups.values():
        if isinstance(items, list):
            all_items.extend(items)

    # ---- demographics ----
    demographics = {'name': '', 'gender': '', 'age': '', 'primary_diagnosis': '', 'icd_code': ''}
    for item in all_items:
        if item.get('report_type') == 'basic_info':
            demo = item.get('demographics') or {}
            if isinstance(demo, dict):
                demographics.update({
                    'name': demo.get('name', '') or '',
                    'gender': demo.get('gender', '') or '',
                    'age': demo.get('age', '') or '',
                })
                break
    # 从 diagnoses 补 primary_diagnosis
    for item in all_items:
        for diag in (item.get('diagnoses') or []):
            if isinstance(diag, dict) and diag.get('name'):
                demographics['primary_diagnosis'] = diag['name']
                demographics['icd_code'] = diag.get('icd10', '') or diag.get('stage', '') or ''
                break
        if demographics['primary_diagnosis']:
            break

    # ---- timeline ----
    timeline: List[Dict[str, Any]] = []
    for item in all_items:
        date = item.get('document_date') or item.get('report_date') or ''
        if not date:
            continue
        note_parts = []
        findings = item.get('findings')
        if isinstance(findings, list):
            note_parts.extend(str(f) for f in findings if f)
        elif isinstance(findings, str) and findings:
            note_parts.append(findings)
        if item.get('conclusion'):
            note_parts.append(str(item['conclusion']))
        timeline.append({
            'dates': [date],
            'title': item.get('_source_file', ''),
            'category': item.get('report_type', ''),
            'note': '；'.join(note_parts)[:200],
        })
    timeline.sort(key=lambda x: x['dates'][0] if x['dates'] else '')

    # ---- pathology ----
    pathology: List[Dict[str, Any]] = []
    for item in (groups.get('pathology') or []):
        date = item.get('document_date') or item.get('report_date') or '日期待确认'
        summary_parts = []
        findings = item.get('findings')
        if isinstance(findings, list):
            summary_parts.extend(str(f) for f in findings if f)
        if item.get('conclusion'):
            summary_parts.append(str(item['conclusion']))
        pathology.append({
            'label': item.get('_source_file', ''),
            'type': item.get('specimen_type', '') or '病理',
            'date': date,
            'summary': '；'.join(summary_parts) or '详见报告',
            'findings': findings or [],
            'value': '',
            'is_critical': False,
        })

    # ---- genetic_highlights ----
    genetic_highlights: List[Dict[str, Any]] = []
    for item in (groups.get('pathology') or []):
        for gene in (item.get('test_items') or []):
            if not isinstance(gene, dict):
                continue
            result = gene.get('detection_result', '') or gene.get('result', '') or ''
            pathogenic = gene.get('is_pathogenic')
            if pathogenic is None:
                pathogenic = any(k in result for k in ['致病', 'pathogenic', '突变'])
            tags = []
            if gene.get('clinical_significance'):
                tags.append(gene['clinical_significance'])
            genetic_highlights.append({
                'category': 'gene',
                'gene': gene.get('gene_name', ''),
                'marker': gene.get('gene_name', ''),
                'mutation': result,
                'result': result,
                'pathogenic': pathogenic,
                'is_critical': pathogenic or False,
                'tags': tags,
            })

    # ---- medication ----
    medication_summary: List[Dict[str, Any]] = []
    medication_table: List[Dict[str, Any]] = []
    med_tl = profile.get('medication_timeline') or {}
    for med in (med_tl.get('timeline') or []):
        name = med.get('name', '') or med.get('drug', '')
        medication_summary.append({
            'label': name,
            'value': med.get('dosage') or med.get('dose', '') or '',
            'is_critical': False,
        })
        medication_table.append({
            'name': name,
            'dose': med.get('dosage') or med.get('dose', ''),
            'route': med.get('route', ''),
            'purpose': med.get('purpose', '') or med.get('type', ''),
        })
    medication_prescription_date = ''
    if med_tl.get('timeline'):
        medication_prescription_date = med_tl['timeline'][0].get('start_date', '') or ''

    # ---- imaging_summary ----
    imaging_summary: List[Dict[str, Any]] = []
    for item in (groups.get('imaging') or []):
        findings = item.get('findings')
        if isinstance(findings, list):
            findings_text = '；'.join(str(f) for f in findings if f)
        elif isinstance(findings, str):
            findings_text = findings
        else:
            findings_text = item.get('conclusion', '') or ''
        imaging_summary.append({
            'date': item.get('document_date') or item.get('report_date') or '日期待确认',
            'modality': item.get('modality', '') or _infer_modality(item.get('_source_file', '')),
            'findings': findings_text,
        })
    # 从 imaging_narrative 补充
    img_narr = profile.get('imaging_narrative') or {}
    if img_narr.get('primary_lesion_timeline') and not imaging_summary:
        imaging_summary.append({
            'date': '综合',
            'modality': '影像演变',
            'findings': str(img_narr['primary_lesion_timeline']),
        })

    # ---- tumor_marker_tables + lab_trend + chart_svg ----
    lab_trends = profile.get('lab_trends') or {}
    tumor_marker_tables: Dict[str, Any] = {}
    lab_trend_rows: List[Dict[str, Any]] = []

    all_dates = set()
    indicator_to_std: Dict[str, str] = {}
    for indicator in lab_trends:
        std = _standard_marker_name(indicator)
        indicator_to_std[indicator] = std
        for row in lab_trends[indicator].get('trend', []):
            all_dates.add(row.get('date', ''))
    all_dates = sorted(d for d in all_dates if d)

    # tumor_marker_tables
    for indicator, data in lab_trends.items():
        if not _is_tumor_marker(indicator):
            continue
        std_name = indicator_to_std[indicator]
        unit = data.get('unit', '')
        ref = data.get('ref_range')
        if isinstance(ref, (list, tuple)) and len(ref) == 2:
            ref_range_str = f'{ref[0]}–{ref[1]} {unit}'.strip()
        else:
            ref_range_str = ''
        rows = []
        prev_val = None
        for tr in data.get('trend', []):
            val = tr.get('value')
            rows.append({
                'date': tr.get('date', ''),
                'value': val,
                'change': _format_change(val, prev_val),
                'note': '异常' if tr.get('abnormal') else '',
                'is_abnormal': bool(tr.get('abnormal')),
            })
            prev_val = val
        tumor_marker_tables[std_name] = {
            'unit': unit,
            'ref_range': ref_range_str,
            'rows': rows,
        }

    # lab_trend（旧格式兜底：每行一个日期，每列一个指标）
    for date in all_dates:
        row = {'date': date}
        for indicator in lab_trends:
            std = indicator_to_std[indicator]
            for tr in lab_trends[indicator].get('trend', []):
                if tr.get('date') == date:
                    row[std] = tr.get('value', '')
                    break
        lab_trend_rows.append(row)

    # chart_svg_ca199（保留兼容）
    chart_svg_ca199 = ''
    chart_svg = ''
    if 'CA199' in tumor_marker_tables:
        chart_svg_ca199 = _generate_marker_svg(tumor_marker_tables['CA199'])
        chart_svg = chart_svg_ca199

    # 多指标趋势图（归一化 + 绝对值 + 同步性告警）
    from scripts.render_html import (
        _generate_multi_marker_svg,
        _generate_absolute_multi_svg,
        _analyze_marker_synchronization,
    )
    chart_svg_normalized = _generate_multi_marker_svg(tumor_marker_tables)
    chart_svg_absolute = _generate_absolute_multi_svg(tumor_marker_tables)
    marker_sync_alert = _analyze_marker_synchronization(tumor_marker_tables)

    # ---- critical_alerts ----
    critical_alerts: List[Dict[str, Any]] = []
    lab_analysis = profile.get('lab_analysis') or {}
    for indicator, analysis in lab_analysis.items():
        level = analysis.get('alert_level', 'normal')
        if level == 'critical':
            critical_alerts.append({
                'item_name': indicator,
                'message': analysis.get('clinical_inference', '') or f'{indicator} 指标危急',
                'level': 5,
                'emoji': '🔴',
                'action': '建议立即联系主治医生',
            })
    # 补充异常检验值
    for indicator, data in lab_trends.items():
        for tr in data.get('trend', []):
            if tr.get('abnormal') and _is_tumor_marker(indicator):
                std = indicator_to_std.get(indicator, indicator)
                if not any(a['item_name'] == std for a in critical_alerts):
                    critical_alerts.append({
                        'item_name': std,
                        'message': f'{std}: {tr.get("value", "")} {tr.get("unit", "")}（异常）',
                        'level': 3,
                        'emoji': '🟡',
                        'action': '下次就诊告知医生',
                    })
    has_critical = any(a['level'] >= 4 for a in critical_alerts)

    # ---- key_concerns ----
    priority_labels = {'high': '高', 'medium': '中', 'low': '低'}
    key_concerns: List[Any] = []
    mdt_analysis = profile.get('mdt_analysis') or {}
    mdt_concerns = mdt_analysis.get('concerns') or []
    if mdt_concerns:
        for item in mdt_concerns:
            if isinstance(item, dict):
                priority = item.get('priority') or 'medium'
                key_concerns.append({
                    'text': item.get('title') or item.get('analysis') or '',
                    'analysis': item.get('analysis') or '',
                    'priority': priority,
                    'priority_label': priority_labels.get(priority, '中'),
                    'disciplines': item.get('disciplines') or ([item.get('discipline')] if item.get('discipline') else []),
                    'suggested_direction': item.get('suggested_direction') or '',
                })
            else:
                key_concerns.append({'text': str(item), 'priority': 'medium'})
    else:
        for a in critical_alerts:
            key_concerns.append(a['message'])
        if img_narr.get('data_limitation'):
            key_concerns.append(img_narr['data_limitation'])

    # ---- consultation_questions ----
    consultation_questions: List[str] = [
        '建议补充历次肿瘤标志物结果以完善趋势分析',
        '建议补充用药方案详细信息（药物、剂量、周期）',
        '建议补充病理报告（组织学类型、免疫组化）',
    ]
    if not imaging_summary:
        consultation_questions.insert(0, '建议补充影像检查报告')

    # ---- files ----
    files: List[Dict[str, Any]] = []
    for item in all_items:
        files.append({
            'title': item.get('_source_file', ''),
            'date': item.get('document_date') or item.get('report_date') or '日期待确认',
            'category': item.get('report_type', '未分类'),
        })

    # ---- gaps ----
    gaps: List[str] = []
    if not lab_trends:
        gaps.append('缺少检验指标趋势数据')
    if not med_tl.get('timeline'):
        gaps.append('缺少用药方案记录')
    if not pathology:
        gaps.append('缺少病理报告')
    if not demographics.get('name'):
        gaps.append('缺少患者基本信息')

    # ---- report_title ----
    primary_dx = demographics.get('primary_diagnosis', '')
    report_title = f'{primary_dx}患者病情概览' if primary_dx else '患者病情概览'

    ctx = {
        'demographics': demographics,
        'has_critical': has_critical,
        'critical_alerts': critical_alerts,
        'timeline': timeline,
        'pathology': pathology,
        'pathology_tag': None,
        'genetic_highlights': genetic_highlights,
        'ihc_note': None,
        'medication_summary': medication_summary,
        'medication_table': medication_table,
        'medication_prescription_date': medication_prescription_date,
        'medication': {
            'current': [m['label'] for m in medication_summary],
            'history': [m['label'] for m in medication_summary],
        },
        'imaging_summary': imaging_summary,
        'tumor_marker_tables': tumor_marker_tables,
        'lab_trend': lab_trend_rows,
        'chart_svg_ca199': chart_svg_ca199,
        'chart_svg': chart_svg,
        'chart_svg_normalized': chart_svg_normalized,
        'chart_svg_absolute': chart_svg_absolute,
        'marker_sync_alert': marker_sync_alert,
        'key_concerns': key_concerns,
        'consultation_questions': consultation_questions,
        'files': files,
        'gaps': gaps,
        'updated_at': profile.get('generated_at', ''),
        'report_title': report_title,
    }
    return ctx


def _infer_modality(filename: str) -> str:
    """从文件名推断影像模态。"""
    lower = (filename or '').lower()
    if 'ct' in lower:
        return 'CT'
    if 'mri' in lower or '核磁' in lower:
        return 'MRI'
    if 'pet' in lower:
        return 'PET-CT'
    if '超声' in lower or 'b超' in lower or 'us' in lower:
        return '超声'
    if 'x线' in lower or 'dr' in lower:
        return 'X线'
    return '影像'


def _generate_marker_svg(marker_data: Dict[str, Any]) -> str:
    """用纯字符串模板生成 SVG 折线图。"""
    rows = marker_data.get('rows', [])
    if not rows:
        return ''
    # 数据点
    values = []
    dates = []
    for r in rows:
        try:
            v = float(r.get('value'))
            values.append(v)
            dates.append(r.get('date', ''))
        except (ValueError, TypeError):
            continue
    if not values:
        return ''

    width, height = 360, 160
    padding = 40
    max_val = max(values) if values else 1
    min_val = min(values)
    y_range = max(max_val - min_val, max_val * 0.2, 1)
    y_max = max_val + y_range * 0.2

    def to_x(i):
        if len(values) == 1:
            return width - padding
        return padding + (width - 2 * padding) * i / (len(values) - 1)

    def to_y(v):
        if y_max == 0:
            return height - padding
        return height - padding - (height - 2 * padding) * (v / y_max)

    points = [f'{to_x(i):.1f},{to_y(v):.1f}' for i, v in enumerate(values)]
    polyline = ' '.join(points)

    # 圆点
    dots = []
    for i, v in enumerate(values):
        cx, cy = to_x(i), to_y(v)
        is_abn = rows[i].get('is_abnormal') if i < len(rows) else False
        fill = '#e74c3c' if is_abn else '#1c5ca8'
        dots.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" fill="{fill}"/>')

    # 参考线
    ref_line = ''
    ref = marker_data.get('ref_range', '')

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'style="max-width:100%;height:auto;">'
        f'<rect width="{width}" height="{height}" fill="#fafbfc"/>'
        f'<polyline points="{polyline}" fill="none" stroke="#1c5ca8" stroke-width="2"/>'
        f'{"".join(dots)}'
    )
    # X 轴日期标签
    for i, d in enumerate(dates):
        label = d[5:] if len(d) >= 10 else d  # MM-DD
        svg += f'<text x="{to_x(i):.1f}" y="{height - 10}" font-size="9" fill="#6b7280" text-anchor="middle">{label}</text>'
    svg += '</svg>'
    return svg


# ---------------------------------------------------------------------------
# 渲染入口
# ---------------------------------------------------------------------------
def render_html_report(
    profile: Dict[str, Any],
    groups: Dict[str, List[Dict[str, Any]]],
    output_dir: Path,
) -> Optional[Path]:
    """渲染 HTML 报告。返回输出路径，失败返回 None。"""
    output_path = Path(output_dir) / 'report.html'

    if not _JINJA2_AVAILABLE:
        logger.warning('Jinja2 未安装，跳过 HTML 渲染')
        return None

    if not _TEMPLATE_PATH.exists():
        logger.warning('模板文件不存在: %s', _TEMPLATE_PATH)
        return None

    ctx = compute_report_context(profile, groups)

    try:
        env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_PATH.parent)),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        # 注册 raw filter 用于 chart_svg
        env.filters['raw'] = lambda x: x if isinstance(x, str) else ''
        template = env.get_template(_TEMPLATE_PATH.name)
        html = template.render(**ctx)
        output_path.write_text(html, encoding='utf-8')
        logger.info('HTML 报告已生成: %s', output_path)
        return output_path
    except Exception as exc:
        logger.exception('模板渲染失败: %s', exc)
        return None
