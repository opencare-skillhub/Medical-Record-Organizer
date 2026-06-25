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
    _RT_LABELS = {
        'pathology': '病理报告', 'lab_results': '检验报告', 'imaging': '影像检查',
        'medication': '用药记录', 'clinical_records': '门诊/住院记录', 'basic_info': '基本信息',
    }
    timeline: List[Dict[str, Any]] = []
    for item in all_items:
        date = item.get('document_date') or item.get('report_date') or ''
        if not date:
            continue
        rt = item.get('report_type', '')
        # 更精确的标签：基因检测区别于普通病理
        if rt == 'pathology':
            label = '基因检测报告' if item.get('test_items') else '病理报告'
        else:
            label = _RT_LABELS.get(rt, item.get('_source_file', ''))
        note_parts = []
        # 优先用结论
        if item.get('conclusion'):
            note_parts.append(str(item['conclusion']))
        # 结构化 diagnoses
        for diag in (item.get('diagnoses') or []):
            if isinstance(diag, dict) and diag.get('name'):
                note_parts.append(f"诊断: {diag['name']}")
        # 关键突变摘要
        test_items = item.get('test_items') or []
        if test_items:
            genes_str = ', '.join(
                f"{g.get('gene_name','')} {g.get('detection_result','')}"[:40]
                for g in test_items[:6] if isinstance(g, dict)
            )
            if genes_str:
                note_parts.append(f"关键突变: {genes_str}")
        # CT 影像所见（裁短）
        findings = item.get('findings')
        if isinstance(findings, list):
            for f in findings:
                if isinstance(f, str) and len(f) > 10:
                    note_parts.append(f[:200])
        elif isinstance(findings, str) and len(findings) > 10:
            note_parts.append(findings[:200])
        note = '；'.join(note_parts)[:400]
        timeline.append({
            'dates': [date],
            'title': f"{date[:7]}: {label}",
            'category': rt,
            'note': note or '待添加',
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
            'summary': '；'.join(summary_parts) or '待添加',
            'findings': findings or [],
            'value': '',
            'is_critical': False,
        })

    # ---- 病理兜底：无结构化数据时从原文读取 ----
    if not any(p.get('findings') for p in pathology) and (groups.get('pathology') or []):
        for item in (groups.get('pathology') or []):
            fname = item.get('_source_file', '')
            src_dir = Path(profile.get('output_dir', '')) / 'sanitized' / fname
            if src_dir and src_dir.exists():
                raw = src_dir.read_text(encoding='utf-8')
                # 找病理诊断关键行
                import re
                diag_match = re.search(r'病理诊断[：:].*?(?=\n\n|\Z)', raw, re.DOTALL)
                if diag_match:
                    for p in pathology:
                        if p['label'] == fname:
                            p['summary'] = diag_match.group(0).strip()[:300]
                            p['value'] = raw[:500]
                            break

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
            # 证据等级分级标签
            tier = (gene.get('evidence_tier') or '').strip().upper()
            tier_label = ''
            if tier in ('1A', '1B'):
                tier_label = 'I类'
            elif tier in ('2A', '2B'):
                tier_label = 'II类'
            elif tier == '3':
                tier_label = 'III类'
            elif tier:
                tier_label = tier
            genetic_highlights.append({
                'category': 'gene',
                'gene': gene.get('gene_name', ''),
                'marker': gene.get('gene_name', ''),
                'mutation': result,
                'result': result,
                'pathogenic': pathogenic,
                'is_critical': pathogenic or False,
                'abundance': gene.get('abundance', ''),
                'evidence_tier': tier,
                'tier_label': tier_label,
                'tags': tags,
            })

    # 按证据等级排序：1A→1B→2A→2B→3→无
    _TIER_ORDER = {'1A': 1, '1B': 2, '2A': 3, '2B': 4, '3': 5}
    genetic_highlights.sort(key=lambda x: _TIER_ORDER.get(x.get('evidence_tier', ''), 99))

    # ---- genetic_highlights 兜底：LLM 返回空时用 parse_genetics 从原文提取 ----
    if not genetic_highlights and (groups.get('pathology') or []):
        from scripts.parse_genetics import parse_genetics
        combined = ''
        for item in (groups.get('pathology') or []):
            fname = item.get('_source_file', '')
            src_dir = Path(profile.get('output_dir', '')) / 'sanitized' / fname
            if src_dir and src_dir.exists():
                combined += '\n' + src_dir.read_text(encoding='utf-8')
        if combined:
            highlights = parse_genetics(combined)
            for h in highlights:
                genetic_highlights.append({
                    'category': 'gene', 'gene': h.gene,
                    'marker': h.gene, 'mutation': h.mutation or h.position,
                    'result': h.mutation or h.position,
                    'pathogenic': h.pathogenic,
                    'is_critical': h.pathogenic,
                    'abundance': h.abundance or '',
                    'evidence_tier': '',
                    'tier_label': '',
                    'tags': [h.drug_sensitivity] if h.drug_sensitivity else [],
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
                'fluctuation': tr.get('fluctuation', ''),
                'note': tr.get('note', ''),
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

    # ---- 通用检验指标表（非肿瘤标志物 + 单日期场景兜底） ----
    lab_flat: List[Dict[str, Any]] = []
    for indicator, data in lab_trends.items():
        if _is_tumor_marker(indicator):
            continue  # 肿瘤标志物已在 tumor_marker_tables 里
        for tr in data.get('trend', []):
            abnormal = tr.get('abnormal')
            lab_flat.append({
                'name': indicator,
                'value': tr.get('value', ''),
                'unit': tr.get('unit', ''),
                'date': tr.get('date', ''),
                'abnormal': bool(abnormal),
            })
            break  # 每个指标只取最近一个值

    # ---- 检验分区与异常卡片 ----
    _LAB_CATEGORIES = {
        '肿瘤标志物': {'CEA','CA199','CA125','CA724','CA242','CA50','CA153','AFP','PSA','糖类抗原','癌胚抗原'},
        '肝功能': {'ALT','AST','GGT','ALP','TBIL','DBIL','IBIL','TP','ALB','GLB','A/G','前白蛋白','甘胆酸','LDH','总胆红素','直接胆红素','白蛋白','转氨酶'},
        '肾功能': {'CREA','BUN','UREA','UA','eGFR','肌酐','尿素','尿酸','肾小球'},
        '血常规': {'WBC','RBC','Hb','HCT','PLT','NEU','LYM','MONO','EO','BASO','白细胞','红细胞','血红蛋白','血小板','中性粒','淋巴'},
        '电解质': {'K','Na','Cl','Ca','P','Mg','钾','钠','氯','钙','磷','镁','碳酸氢根'},
        '血脂血糖': {'TG','TC','HDL','LDL','GLU','血糖','甘油三酯','总胆固醇','脂蛋白','sd-LDL'},
        '凝血功能': {'PT','APTT','INR','D-二聚体','纤维蛋白原','FIB','TT'},
        '其他': set(),
    }

    def _classify_lab(name: str) -> str:
        upper = name.upper()
        for cat, keywords in _LAB_CATEGORIES.items():
            for kw in keywords:
                if kw in upper or kw in name:
                    return cat
        return '其他'

    # 指标分类
    categorized: Dict[str, List[Dict[str, Any]]] = {}
    for indicator, data in lab_trends.items():
        cat = _classify_lab(indicator)
        categorized.setdefault(cat, [])
        for tr in data.get('trend', []):
            categorized[cat].append({
                'name': indicator, 'value': tr.get('value',''), 'unit': tr.get('unit',''),
                'date': tr.get('date',''), 'abnormal': bool(tr.get('abnormal', False)),
                'flag': tr.get('flag',''), 'ref_low': data.get('ref_range',(None,None))[0] if isinstance(data.get('ref_range'), (tuple, list)) else None,
                'ref_high': data.get('ref_range',(None,None))[1] if isinstance(data.get('ref_range'), (tuple, list)) else None,
            })
            break
    # 去掉空分类
    categorized = {k: v for k, v in categorized.items() if v and k != '其他'}
    # 异常指标抢眼展示（卡片格式）
    lab_abnormal: List[Dict[str, Any]] = []
    for items in categorized.values():
        for it in items:
            if it['abnormal']:
                lab_abnormal.append(it)
    categorized_lab = [{'category': k, 'items': v} for k, v in categorized.items()]

    # ---- lab_analysis_conclusion (检验分析结论) ----
    lab_analysis_conclusion = ''
    for item in (groups.get('lab') or []):
        if item.get('lab_analysis_conclusion'):
            lab_analysis_conclusion = item['lab_analysis_conclusion']
            break

    # ---- clinical_summary (临床摘要) ----
    clinical_summary = ''
    for item in (groups.get('clinical') or []):
        if item.get('clinical_summary'):
            clinical_summary = item['clinical_summary']
            break

    # ---- pathology_diagnosis (病理诊断要点) ----
    pathology_diagnosis: Optional[Dict[str, Any]] = None
    for item in (groups.get('pathology') or []):
        pd = item.get('pathology_diagnosis')
        if pd:
            # LLM 有时返回 list/str 而非 dict，做防御性处理
            if not isinstance(pd, dict):
                logger.warning('pathology_diagnosis 非 dict (type=%s)，跳过: %s', type(pd).__name__, str(pd)[:100])
                continue
            pathology_diagnosis = pd
            break

    # ---- ihc_markers (免疫组化) ----
    ihc_items: List[Dict[str, Any]] = []
    for item in (groups.get('pathology') or []):
        for m in (item.get('ihc_markers') or []):
            if isinstance(m, dict):
                ihc_items.append(m)

    # ---- pd_l1 ----
    pd_l1: Optional[Dict[str, Any]] = None
    for item in (groups.get('pathology') or []):
        pl = item.get('pd_l1')
        if pl:
            if not isinstance(pl, dict):
                logger.warning('pd_l1 非 dict (type=%s)，跳过: %s', type(pl).__name__, str(pl)[:100])
                continue
            pd_l1 = pl
            break

    # ---- timeline_items (临床时间轴) ----
    timeline_items: List[Dict[str, Any]] = []
    for item in (groups.get('clinical') or []):
        for t in (item.get('timeline_items') or []):
            if isinstance(t, dict):
                timeline_items.append(t)

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
        'lab_flat': lab_flat,
        'lab_abnormal': lab_abnormal,
        'categorized_lab': categorized_lab,
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
        'lab_analysis_conclusion': lab_analysis_conclusion,
        'clinical_summary': clinical_summary,
        'pathology_diagnosis': pathology_diagnosis,
        'ihc_items': ihc_items,
        'pd_l1': pd_l1,
        'timeline_items': timeline_items,
        'pancreatic_consensus_link': 'https://mp.weixin.qq.com/s/Vpn2oH9cDgsOPg5oekvwCg',
        'pancreatic_consensus_text': '胰腺癌精准检测与分子诊断中国专家共识（2025版）',
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
