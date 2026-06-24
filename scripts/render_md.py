"""
Markdown 报告渲染器

职责：
- compute_md_context(): 把 profile/groups（或 manifest）转换为 case-report-template.md 所需的 context
- render_md(): 用 Jinja2 渲染 Markdown 模板，输出 .md 文件

模板：references/case-report-template.md
对应 dev/docs/template-context.md。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.parse_genetics import (
    parse_genetics,
    format_genetic_highlights_md,
)

logger = logging.getLogger(__name__)

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    _JINJA2_AVAILABLE = True
except ImportError:
    _JINJA2_AVAILABLE = False

# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE_PATH = _PROJECT_ROOT / 'references' / 'case-report-template.md'

# 肿瘤标志物中文名 → 标准缩写
_MARKER_ALIASES = {
    '癌胚抗原': 'CEA',
    '糖类抗原19-9': 'CA199', '糖类抗原19-9(高值)': 'CA199',
    'ca199': 'CA199', 'ca19-9': 'CA199',
    '糖类抗原125': 'CA125', 'ca125': 'CA125',
    '糖类抗原15-3': 'CA153', '糖类抗原153': 'CA153',
    'ca15-3': 'CA153', 'ca153': 'CA153',
    '糖类抗原724': 'CA724', '糖类抗原72-4': 'CA724',
    'ca724': 'CA724', 'ca72-4': 'CA724',
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
    if lower.isascii():
        return lower.upper()
    return name


def _is_tumor_marker(name: str) -> bool:
    """判断是否为肿瘤标志物。"""
    std = _standard_marker_name(name)
    return std in {'CEA', 'CA199', 'CA125', 'CA153', 'CA724', 'AFP', 'PSA', 'CA242', 'CA50'}


def _is_manifest(profile: Dict[str, Any]) -> bool:
    """判断传入的 profile 是否为 manifest 结构（旧格式，供测试兼容）。"""
    return bool(
        profile.get('categories_summary')
        or profile.get('files')
        or ('demographics' in profile and 'name' in (profile.get('demographics') or {}))
    )


# ---------------------------------------------------------------------------
# 核心：compute_md_context
# ---------------------------------------------------------------------------
def compute_md_context(
    profile: Dict[str, Any],
    groups: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    *,
    timeline: Optional[List[Dict[str, Any]]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把 profile + groups 转换为 case-report-template.md 所需的 context dict。

    兼容两种输入格式：
    1. profile/groups（v2 pipeline 结构）
    2. profile 为 manifest 结构（旧测试格式，此时 groups=None）
    """
    manifest_style = _is_manifest(profile) and groups is None

    # ── demographics ──────────────────────────────────────────────────────
    if manifest_style:
        demographics = dict(profile.get('demographics', {}) or {})
        created_at = profile.get('created_at', '')
        updated_at = profile.get('updated_at', '')
        all_items: List[Dict[str, Any]] = []
        for fe in (profile.get('files') or []):
            all_items.append({
                '_source_file': fe.get('title') or fe.get('original_name', ''),
                'document_date': fe.get('date_detected') or '',
                'report_date': fe.get('date_detected') or '',
                'report_type': (fe.get('category') or 'other').split('.')[0],
                'findings': [],
                'conclusion': '',
                'test_items': [],
            })
    else:
        demographics: Dict[str, Any] = {
            'name': '', 'gender': '', 'age': '',
            'primary_diagnosis': '', 'icd_code': '',
        }
        all_items: List[Dict[str, Any]] = []
        for items in (groups or {}).values():
            if isinstance(items, list):
                all_items.extend(items)

        for item in all_items:
            if item.get('report_type') == 'basic_info':
                demo = item.get('demographics') or {}
                if isinstance(demo, dict):
                    demographics.update({
                        'name': demo.get('name', '') or demographics['name'],
                        'gender': demo.get('gender', '') or demographics['gender'],
                        'age': demo.get('age', '') or demographics['age'],
                    })
                    break

        for item in all_items:
            for diag in (item.get('diagnoses') or []):
                if isinstance(diag, dict) and diag.get('name'):
                    demographics['primary_diagnosis'] = diag['name']
                    demographics['icd_code'] = (
                        diag.get('icd10', '') or diag.get('stage', '') or ''
                    )
                    break
            if demographics['primary_diagnosis']:
                break

        created_at = profile.get('generated_at', '')
        updated_at = profile.get('generated_at', '')

    # ── timeline ──────────────────────────────────────────────────────────
    if timeline:
        simple_tl: List[Dict[str, Any]] = []
        for item in timeline:
            simple_tl.append({
                'dates': item.get('dates', []),
                'title': item.get('title') or item.get('file', ''),
                'category': item.get('category', ''),
            })
    else:
        simple_tl = []
        for item in all_items:
            date = item.get('document_date') or item.get('report_date') or ''
            if not date:
                continue
            note_parts: List[str] = []
            findings = item.get('findings')
            if isinstance(findings, list):
                note_parts.extend(str(f) for f in findings if f)
            elif isinstance(findings, str) and findings:
                note_parts.append(findings)
            if item.get('conclusion'):
                note_parts.append(str(item['conclusion']))
            simple_tl.append({
                'dates': [date],
                'title': item.get('_source_file', ''),
                'category': item.get('report_type', ''),
                'note': '；'.join(note_parts)[:200],
            })
        simple_tl.sort(key=lambda x: x['dates'][0] if x['dates'] else '')

    # ── lab_trend（Markdown 表格行） ──────────────────────────────────────
    md_lab_trend: List[Dict[str, Any]] = []
    lab_trends = profile.get('lab_trends') or {}
    all_dates = set()
    indicator_to_std: Dict[str, str] = {}
    for indicator in lab_trends:
        std = _standard_marker_name(indicator)
        indicator_to_std[indicator] = std
        for row in lab_trends[indicator].get('trend', []):
            all_dates.add(row.get('date', ''))
    all_dates_sorted = sorted(d for d in all_dates if d)

    if all_dates_sorted:
        for date in all_dates_sorted:
            row: Dict[str, Any] = {'date': date}
            for indicator in lab_trends:
                std = indicator_to_std[indicator]
                for tr in lab_trends[indicator].get('trend', []):
                    if tr.get('date') == date:
                        row[std] = tr.get('value', '')
                        break
            md_lab_trend.append(row)

    # ── imaging_summary ───────────────────────────────────────────────────
    imaging_summary: List[Dict[str, Any]] = []
    if manifest_style:
        pass  # manifest 格式暂不填充 imaging
    else:
        for item in (groups or {}).get('imaging') or []:
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
        if not imaging_summary:
            img_narr = profile.get('imaging_narrative') or {}
            if img_narr.get('primary_lesion_timeline'):
                imaging_summary.append({
                    'date': '综合', 'modality': '影像演变',
                    'findings': str(img_narr['primary_lesion_timeline']),
                })

    # ── pathology ────────────────────────────────────────────────────────
    pathology: List[Dict[str, Any]] = []
    if manifest_style:
        pass  # manifest 格式暂不填充 pathology
    else:
        for item in (groups or {}).get('pathology') or []:
            date = item.get('document_date') or item.get('report_date') or '日期待确认'
            summary_parts: List[str] = []
            findings = item.get('findings')
            if isinstance(findings, list):
                summary_parts.extend(str(f) for f in findings if f)
            if item.get('conclusion'):
                summary_parts.append(str(item['conclusion']))
            pathology.append({
                'date': date,
                'type': item.get('specimen_type', '') or '病理',
                'summary': '；'.join(summary_parts) or '详见报告',
            })

    # ── medication ────────────────────────────────────────────────────────
    med_current: List[str] = []
    med_history: List[str] = []
    med_timeline_list: List[Dict[str, Any]] = []
    if manifest_style:
        pass  # manifest 格式暂不填充 medication
    else:
        med_tl = profile.get('medication_timeline') or {}
        for med in (med_tl.get('timeline') or []):
            name = med.get('name', '') or med.get('drug', '')
            med_timeline_list.append(med)
            med_current.append(name)
            med_history.append(name)

    # ── genetic_highlights（文本块，供模板 for 循环） ─────────────────────
    combined_text = '\n'.join(
        extra.get('extracted_texts', []) if extra else []
    )
    if manifest_style and extra:
        combined_text = '\n'.join(extra.get('extracted_texts', []))

    highlights = parse_genetics(combined_text)
    genetic_md = format_genetic_highlights_md(highlights)

    # ── critical_alerts ──────────────────────────────────────────────────
    critical_alerts: List[Dict[str, Any]] = []
    if manifest_style and extra:
        from scripts.critical_values import check_critical_values
        alerts = check_critical_values(combined_text)
        for a in alerts:
            critical_alerts.append({
                'item_name': a.item_name,
                'value': a.value,
                'unit': a.unit,
                'level': a.level,
                'level_label': a.level_label,
                'message': a.message,
                'color': a.color,
                'emoji': a.emoji,
                'action': a.action,
            })
    else:
        lab_analysis = profile.get('lab_analysis') or {}
        for indicator, analysis in lab_analysis.items():
            level = analysis.get('alert_level', 'normal')
            if level == 'critical':
                critical_alerts.append({
                    'item_name': indicator,
                    'value': '',
                    'unit': '',
                    'level': 5,
                    'level_label': '危急',
                    'message': analysis.get('clinical_inference', '') or f'{indicator} 指标危急',
                    'color': 'red',
                    'emoji': '🔴',
                    'action': '建议立即联系主治医生',
                })
        for indicator, data in lab_trends.items():
            if not _is_tumor_marker(indicator):
                continue
            for tr in data.get('trend', []):
                if tr.get('abnormal'):
                    std = indicator_to_std.get(indicator, indicator)
                    if not any(a['item_name'] == std for a in critical_alerts):
                        critical_alerts.append({
                            'item_name': std,
                            'value': tr.get('value', ''),
                            'unit': tr.get('unit', ''),
                            'level': 3,
                            'level_label': '异常',
                            'message': f'{std}: {tr.get("value", "")} {tr.get("unit", "")}（异常）',
                            'color': 'orange',
                            'emoji': '🟡',
                            'action': '下次就诊告知医生',
                        })

    has_critical = any(a['level'] >= 4 for a in critical_alerts)

    # ── key_concerns ─────────────────────────────────────────────────────
    key_concerns: List[Any] = []
    mdt_analysis = profile.get('mdt_analysis') or {}
    mdt_concerns = mdt_analysis.get('concerns') or []
    if mdt_concerns:
        for item in mdt_concerns:
            if isinstance(item, dict):
                title = item.get('title') or item.get('analysis') or ''
                analysis = item.get('analysis') or ''
                priority = item.get('priority') or 'medium'
                disciplines = item.get('disciplines') or ([item.get('discipline')] if item.get('discipline') else [])
                priority_label = {'high': '高', 'medium': '中', 'low': '低'}.get(priority, '中')
                prefix = '⚠️' if priority == 'high' else ('⚪' if priority == 'low' else '•')
                if disciplines:
                    title = f"{title}（{'/'.join([d for d in disciplines if d])}）"
                line = f"{prefix} [优先级:{priority_label}] {title}"
                key_concerns.append(f"{line}：{analysis}" if analysis else line)
            else:
                key_concerns.append(str(item))
    else:
        for a in critical_alerts:
            key_concerns.append(a['message'])
        if not manifest_style:
            img_narr = profile.get('imaging_narrative') or {}
            if img_narr.get('data_limitation'):
                key_concerns.append(img_narr['data_limitation'])

    # ── consultation_questions ───────────────────────────────────────────
    consultation_questions: List[str] = [
        '建议补充历次肿瘤标志物结果以完善趋势分析',
        '建议补充用药方案详细信息（药物、剂量、周期）',
        '建议补充病理报告（组织学类型、免疫组化）',
    ]
    if not imaging_summary:
        consultation_questions.insert(0, '建议补充影像检查报告')

    # ── files ────────────────────────────────────────────────────────────
    files_list: List[Dict[str, Any]] = []
    for item in all_items:
        files_list.append({
            'title': item.get('_source_file', ''),
            'date': item.get('document_date') or item.get('report_date') or '日期待确认',
        })
    if manifest_style:
        files_list = []
        for fe in (profile.get('files') or []):
            files_list.append({
                'title': fe.get('title') or fe.get('original_name', ''),
                'date': fe.get('date_detected') or '日期待确认',
            })

    # ── gaps ─────────────────────────────────────────────────────────────
    gaps: List[str] = []
    if not lab_trends:
        gaps.append('缺少检验指标趋势数据')
    if not med_timeline_list and not med_current:
        gaps.append('缺少用药方案记录')
    if not pathology:
        gaps.append('缺少病理报告')
    if not demographics.get('name'):
        gaps.append('缺少患者基本信息')

    # ── report_title ─────────────────────────────────────────────────────
    primary_dx = demographics.get('primary_diagnosis', '')
    report_title = f'{primary_dx}患者病情概览' if primary_dx else '患者病情概览'

    ctx: Dict[str, Any] = {
        'demographics': demographics,
        'created_at': created_at,
        'updated_at': updated_at,
        'report_title': report_title,
        'has_critical': has_critical,
        'critical_alerts': critical_alerts,
        'recent_focus': key_concerns,
        'timeline': simple_tl,
        'lab_trend': md_lab_trend,
        'imaging_summary': imaging_summary,
        'pathology': pathology,
        'medication': {'current': med_current, 'history': med_history},
        'medication_timeline': med_timeline_list,
        'genetic_highlights_md': genetic_md,
        'key_concerns': key_concerns,
        'consultation_questions': consultation_questions,
        'files': files_list,
        'gaps': gaps,
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


# ---------------------------------------------------------------------------
# 渲染入口
# ---------------------------------------------------------------------------
def render_md(
    profile: Dict[str, Any],
    groups: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    output_path: Optional[Path] = None,
    *,
    timeline: Optional[List[Dict[str, Any]]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Path:
    """渲染 Markdown 报告。

    参数：
        profile: v2 profile dict（含 lab_trends / medication_timeline 等）
                 或 manifest dict（旧格式，供测试兼容；此时需设 groups=None）
        groups: 分类后的 items dict，profile/groups 模式下必传
        output_path: 输出路径，默认 output/case_report.md
        timeline: 可选时间线列表（覆盖从 profile/groups 自动构建的）
        extra: 附加数据（如 extracted_texts 用于危急值/基因检测解析）
    """
    if output_path is None:
        output_path = _PROJECT_ROOT / 'output' / 'case_report.md'

    if not _JINJA2_AVAILABLE:
        raise RuntimeError('Jinja2 未安装，请运行: pip install jinja2')

    if not _TEMPLATE_PATH.exists():
        raise FileNotFoundError(f'模板文件不存在: {_TEMPLATE_PATH}')

    ctx = compute_md_context(profile, groups=groups, timeline=timeline, extra=extra)

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_PATH.parent)),
        autoescape=select_autoescape(enabled_extensions=('md',)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(_TEMPLATE_PATH.name)
    content = template.render(**ctx)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding='utf-8')
    logger.info('Markdown 报告已生成: %s', output_path)
    return output_path
