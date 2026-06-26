"""
HTML 报告渲染器

职责：
- compute_report_context(): 把 profile/groups 转换为 html-report-template.html 所需的 context
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
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE_PATH = _PROJECT_ROOT / 'references' / 'html-report-template.html'

# 肿瘤标志物中文名 → 标准缩写
# 注意：LLM 有时输出"糖链抗原"（医院写法差异），统一归一化
_MARKER_ALIASES = {
    '癌胚抗原': 'CEA', 'cea': 'CEA',
    '糖类抗原19-9': 'CA199', '糖链抗原19-9': 'CA199',
    '糖类抗原19-9(高值)': 'CA199', '糖链抗原19-9(高值)': 'CA199',
    'ca199': 'CA199', 'ca19-9': 'CA199',
    '糖类抗原125': 'CA125', '糖链抗原125': 'CA125', 'ca125': 'CA125',
    '糖类抗原15-3': 'CA153', '糖链抗原15-3': 'CA153',
    '糖类抗原153': 'CA153', '糖链抗原153': 'CA153',
    'ca15-3': 'CA153', 'ca153': 'CA153',
    '糖类抗原724': 'CA724', '糖类抗原72-4': 'CA724',
    '糖链抗原724': 'CA724', '糖链抗原72-4': 'CA724',
    'ca724': 'CA724', 'ca72-4': 'CA724',
    '甲胎蛋白': 'AFP', 'afp': 'AFP',
    '前列腺特异性抗原': 'PSA', 'psa': 'PSA',
    '糖类抗原242': 'CA242', '糖链抗原242': 'CA242', 'ca242': 'CA242',
    '糖类抗原50': 'CA50', '糖链抗原50': 'CA50', 'ca50': 'CA50',
}


def _normalize_marker_text(name: str) -> str:
    """把医院常见写法差异（糖链→糖类，空格→无）归一化。"""
    if not name:
        return ''
    s = name.strip()
    if s.startswith('糖链'):
        s = '糖类' + s[2:]
    return s.lower()


def _standard_marker_name(name: str) -> str:
    """把中文标志物名映射为标准缩写。"""
    if not name:
        return ''
    name = _normalize_marker_text(name)
    if name in _MARKER_ALIASES:
        return _MARKER_ALIASES[name]
    for cn, std in _MARKER_ALIASES.items():
        if cn in name:
            return std
    # 英文缩写直接保留大写
    if name.isascii():
        return name.upper()
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
def compute_report_context(
    profile: Dict[str, Any],
    groups: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    *,
    timeline: Optional[List[Dict[str, Any]]] = None,
    extracted_texts: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """把 profile + groups 转换为模板所需的 context dict。

    兼容两种调用方式：
    1. compute_report_context(profile, groups) — 新 pipeline 方式
    2. compute_report_context(manifest, timeline=..., extracted_texts=...) — 旧测试兼容

    对应 dev/docs/template-context.md 中的所有变量。
    """
    # 向后兼容：如果 groups 为 None 且 profile 看起来像 manifest，走旧路径
    if groups is None and _is_manifest(profile):
        return _compute_context_from_manifest(
            profile, timeline=timeline, extracted_texts=extracted_texts, extra=extra
        )

    all_items: List[Dict[str, Any]] = []
    for items in (groups or {}).values():
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

    # 去重：相同日期+类别+前80字摘要的去重
    seen = set()
    deduped = []
    for t in timeline:
        key = (t['dates'][0] if t['dates'] else '', t['category'], t['note'][:80])
        if key not in seen:
            seen.add(key)
            deduped.append(t)
    timeline = deduped

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
    # 仅保留有临床意义的突变：致病性明确 或 证据等级≥III类
    # 排除野生型/良性变异/意义未明，不展示"突变"字样弱信号
    _PATHOGENIC_WORDS = {'致病', '移码', '缺失', '插入', '无义', 'stop', 'frameshift',
                         'deletion', 'nonsense', '截断', '错义', '扩增', '重排',
                         '失活', '功能丧失', '扩增', 'pathogenic', '突变'}
    _BENIGN_WORDS = {'野生型', '野生', 'wild', '无突变', '阴性', '未检测到', '未检出',
                     '阴性正常', '(-)', '无意义', 'not detected'}
    genetic_highlights: List[Dict[str, Any]] = []
    for item in (groups.get('pathology') or []):
        for gene in (item.get('test_items') or []):
            if not isinstance(gene, dict):
                continue
            result = gene.get('detection_result', '') or gene.get('result', '') or ''
            result_lower = result.lower()
            pathogenic = gene.get('is_pathogenic')
            tier = (gene.get('evidence_tier') or '').strip().upper()

            # 跳过明确良性的
            if any(w in result for w in _BENIGN_WORDS):
                continue
            # 跳过只有"突变"字眼但无强致病信号的弱匹配（如"同义突变""SNP""变异"等）
            if not pathogenic and tier not in ('1A', '1B', '2A', '2B', '3'):
                pathogenic = any(w in result_lower for w in _PATHOGENIC_WORDS)
                if not pathogenic:
                    continue  # 无致病信号 → 不展示

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
                'tags': [],
            })

    # ---- medication ----
    medication_summary: List[Dict[str, Any]] = []
    medication_table: List[Dict[str, Any]] = []
    med_tl = profile.get('medication_timeline') or {}
    seen_meds: set = set()

    def _add_med(name: str, dose: str, route: str = '', purpose: str = '') -> None:
        if not name:
            return
        key = (name.strip().lower(), str(dose).strip())
        if key in seen_meds:
            return
        seen_meds.add(key)
        medication_summary.append({'label': name, 'value': dose, 'is_critical': False})
        medication_table.append({'name': name, 'dose': dose, 'route': route, 'purpose': purpose})

    # 主来源：medication_timeline（reduce_medication_history 的输出）
    for med in (med_tl.get('timeline') or []):
        _add_med(
            med.get('name', '') or med.get('drug', ''),
            med.get('dosage') or med.get('dose', '') or '',
            med.get('route', ''),
            med.get('purpose', '') or med.get('type', ''),
        )

    # 补充来源：clinical 记录中的 medications（门诊/出院小结里的用药方案）
    for item in (groups.get('clinical') or []):
        for m in (item.get('medications') or []):
            if isinstance(m, dict):
                _add_med(
                    m.get('name', '') or m.get('drug', ''),
                    m.get('dosage') or m.get('dose', '') or '',
                    m.get('route', ''),
                    m.get('purpose', '') or m.get('type', ''),
                )
            elif isinstance(m, str):
                _add_med(m, '')

    # 补充来源：medication 组中的 medications
    for item in (groups.get('medication') or []):
        for m in (item.get('medications') or []):
            if isinstance(m, dict):
                _add_med(
                    m.get('name', '') or m.get('drug', ''),
                    m.get('dosage') or m.get('dose', '') or '',
                    m.get('route', ''),
                    m.get('purpose', '') or m.get('type', ''),
                )

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
    key_concerns: List[Any] = []
    mdt_analysis = profile.get('mdt_analysis') or {}
    mdt_concerns = mdt_analysis.get('concerns') or []
    if mdt_concerns:
        for item in mdt_concerns:
            if isinstance(item, dict):
                key_concerns.append({
                    'text': item.get('title') or item.get('analysis') or '',
                    'analysis': item.get('analysis') or '',
                    'priority': item.get('priority') or 'medium',
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

    # ---- 通用检验指标表（非肿瘤标志物 + 单日期场景兜底） ----
    lab_flat: List[Dict[str, Any]] = []
    for indicator, data in lab_trends.items():
        if _is_tumor_marker(indicator):
            continue  # 肿瘤标志物已在 tumor_marker_tables 里
        trend = data.get('trend', [])
        if trend:
            # 取最新一条（trend 已按日期升序排列，取最后一个）
            tr = trend[-1]
            lab_flat.append({
                'name': indicator,
                'value': tr.get('value', ''),
                'unit': tr.get('unit', ''),
                'date': tr.get('date', ''),
                'abnormal': bool(tr.get('abnormal')),
            })

    # ---- 检验分区与异常卡片 ----
    _LAB_CATEGORIES = {
        '肿瘤标志物': {'CEA','CA199','CA125','CA724','CA242','CA50','CA153','AFP','PSA','糖类抗原','糖链抗原','癌胚抗原'},
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
            # LLM 有时返回 list/str 而非 dict
            if isinstance(pd, list):
                for e in pd:
                    if isinstance(e, dict):
                        pd = e
                        break
                else:
                    logger.warning('pathology_diagnosis 为 list 且无 dict 元素，跳过')
                    continue
            if isinstance(pd, str):
                # 字符串格式 "胰腺穿刺标本，查见肿瘤，建议免疫组化协助分析"
                logger.info('pathology_diagnosis 为 str，转换为 dict: %s', pd[:80])
                pd_dict: Dict[str, Any] = {'pathology_diagnosis': pd}
                # 尝试从原文中提取更多字段
                raw_text = ' '.join([d.get('summary', '') or '' for d in (item.get('findings') or [])])
                if 'T' in raw_text.upper() and 'N' in raw_text.upper() and 'M' in raw_text.upper():
                    import re
                    tnm = re.search(r'(T\d[ab]?N\d[ab]?M\d[ab]?)', raw_text)
                    if tnm:
                        pd_dict['tnm_stage'] = tnm.group(1)
                pd = pd_dict
            if isinstance(pd, dict):
                pathology_diagnosis = pd
                break
            logger.warning('pathology_diagnosis 非 dict/str/list (type=%s)，跳过', type(pd).__name__)

    # ---- ihc_markers (免疫组化) ----
    ihc_items: List[Dict[str, Any]] = []
    for item in (groups.get('pathology') or []):
        for m in (item.get('ihc_markers') or []):
            if isinstance(m, dict):
                ihc_items.append(m)
    # 兜底：LLM 未提取免疫组化时，从 sanitized 原文正则提取常见标记物
    if not ihc_items and (groups.get('pathology') or []):
        import re
        _IHC_PATTERN = re.compile(
            r'(CK\d+|CD\d+|CDX2|SATB2|P40|P53|TTF-?1|Napsin\s*A|NapsinA|'
            r'Ki-?67|SMAD4|Her-?2|HER-?2|ER|PR|AR|Vimentin|VIM|EMA|'
            r'CgA|Syn|SMA|Desmin|MSH2|MSH6|MLH1|PMS2|S100|MUC\d*|'
            r'PD-?L1|PD-L1|CK7|CK19|CK20|CA19-9|GATA3|PAX8|'
            r'CD3|CD4|CD8|CD20|CD68|CD163|FoxP3)\s*[\(（]?\s*[-+±%0-9.]+\s*[)）]?',
            re.IGNORECASE
        )
        for item in (groups.get('pathology') or []):
            fname = item.get('_source_file', '')
            src = Path(profile.get('output_dir', '')) / 'sanitized' / fname
            if src.exists():
                raw = src.read_text(encoding='utf-8')
                for m in _IHC_PATTERN.finditer(raw):
                    ihc_items.append({
                        'marker': m.group(1),
                        'result': m.group(0)[len(m.group(1)):].strip(),
                    })

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

    # ---- consultation_questions ----
    # 从 MDT 分析中获取 LLM 生成的咨询建议，失败时根据数据缺口动态生成
    mdt_analysis = profile.get('mdt_analysis') or {}
    consultation_questions = mdt_analysis.get('consultation_questions') or []
    if not consultation_questions:
        questions = []
        if not imaging_summary:
            questions.append('建议补充历次影像检查报告（CT/MRI/PET-CT），以对照评估病灶变化')
        if not tumor_marker_tables:
            questions.append('建议补充历次肿瘤标志物结果以完善趋势分析')
        if not medication_table:
            questions.append('建议补充用药方案详细信息（药物、剂量、周期、疗效评估）')
        if not pathology_diagnosis:
            questions.append('建议补充病理报告（组织学类型、TNM分期、免疫组化、基因检测结果）')
        else:
            if not ihc_items:
                questions.append('建议补充免疫组化结果（MSI/MMR状态、HER2、PD-L1等）')
        if questions:
            consultation_questions = questions
        else:
            consultation_questions = ['根据现有资料，病情档案已较为完整。建议线下就诊时携带全部检查资料。']

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
# 多指标肿瘤标志物趋势图（新增）
# ---------------------------------------------------------------------------
_MARKER_COLORS = [
    '#1c5ca8', '#c0392b', '#e67e22', '#27ae60',
    '#8e44ad', '#16a085', '#d35400', '#7f8c8d',
]


def _generate_multi_marker_svg(tumor_marker_tables: Dict[str, Any]) -> str:
    """生成多指标归一化趋势图 SVG（首值=100）。

    每个指标以首次有效值为基线(=100)，便于比较趋势方向和同步性。
    """
    if not tumor_marker_tables:
        return ''

    # 过滤有效指标（>=2 个有效数值），最多保留 6 个
    valid_series: List[tuple[str, str, List[tuple[str, float, bool]]]] = []
    for idx, (name, data) in enumerate(tumor_marker_tables.items()):
        rows = data.get('rows') or []
        points: List[tuple[str, float, bool]] = []
        baseline = None
        valid = 0
        for r in rows:
            try:
                v = float(r.get('value'))  # type: ignore[arg-type]
            except (ValueError, TypeError):
                continue
            date = r.get('date', '') or ''
            if baseline is None:
                baseline = v if v != 0 else 1.0
            norm = (v / baseline) * 100
            points.append((date, norm, bool(r.get('is_abnormal'))))
            valid += 1
        if valid >= 2 and baseline is not None:
            color = _MARKER_COLORS[idx % len(_MARKER_COLORS)]
            valid_series.append((name, color, points))
    if not valid_series:
        return ''
    if len(valid_series) > 6:
        valid_series = valid_series[:6]

    # 统一日期轴
    all_dates = sorted({d for _, _, pts in valid_series for d, _, _ in pts if d})
    if not all_dates:
        return ''
    date_to_x = {d: i for i, d in enumerate(all_dates)}

    width, height = 520, 220
    pad_left, pad_right = 55, 20
    pad_top, pad_bottom = 20, 70
    cw = width - pad_left - pad_right
    ch = height - pad_top - pad_bottom

    def to_x(date: str) -> float:
        if len(all_dates) <= 1:
            return pad_left + cw / 2
        return pad_left + (cw / (len(all_dates) - 1)) * date_to_x.get(date, 0)

    # Y 轴范围
    all_norm = [n for _, _, pts in valid_series for _, n, _ in pts]
    if not all_norm:
        return ''
    y_min = min(all_norm)
    y_max = max(all_norm)
    y_range = max(y_max - y_min, 20)
    y_margin = y_range * 0.15
    y_low = y_min - y_margin
    y_high = y_max + y_margin
    y_range = y_high - y_low

    def to_y(v: float) -> float:
        if y_range == 0:
            return pad_top + ch / 2
        return pad_top + ch - ((v - y_low) / y_range) * ch

    parts: List[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'style="max-width:100%;height:auto;">'
    )
    parts.append(f'<rect width="{width}" height="{height}" fill="#fafbfc"/>')
    # 图标题
    parts.append(
        f'<text x="{width / 2:.1f}" y="{pad_top - 2:.1f}" font-size="12" '
        f'fill="#333" text-anchor="middle" font-weight="700">'
        f'相对首值变化，首值=100</text>'
    )

    # Y 轴网格 + 标签（80/100/120）
    for tick in (80, 100, 120):
        if y_low <= tick <= y_high:
            y = to_y(tick)
            parts.append(f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width - pad_right}" y2="{y:.1f}" stroke="#e5e7eb" stroke-width="1"/>')
            parts.append(f'<text x="{pad_left - 5}" y="{y + 4:.1f}" font-size="9" fill="#6b7280" text-anchor="end">{int(tick)}</text>')

    # 首值基线（100）高亮
    if y_low <= 100 <= y_high:
        y100 = to_y(100)
        parts.append(
            f'<line x1="{pad_left}" y1="{y100:.1f}" x2="{width - pad_right}" y2="{y100:.1f}" '
            f'stroke="#9ca3af" stroke-width="1" stroke-dasharray="4,2"/>'
        )

    # X 轴日期
    for i, d in enumerate(all_dates):
        x = to_x(d)
        label = d[5:] if len(d) >= 10 else d
        parts.append(f'<text x="{x:.1f}" y="{height - 10}" font-size="9" fill="#6b7280" text-anchor="middle">{label}</text>')

    # 折线 + 圆点
    for name, color, pts in valid_series:
        line_pts = [f'{to_x(d):.1f},{to_y(n):.1f}' for d, n, _ in pts]
        if line_pts:
            parts.append(f'<polyline points="{" ".join(line_pts)}" fill="none" stroke="{color}" stroke-width="2"/>')
        for d, n, abn in pts:
            cx = to_x(d)
            cy = to_y(n)
            stroke = '#e74c3c' if abn else color
            sw = 2 if abn else 1
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" fill="{color}" stroke="{stroke}" stroke-width="{sw}"/>')

    # 图例
    for i, (name, color, _) in enumerate(valid_series):
        ly = pad_top + 5 + i * 16
        parts.append(f'<rect x="{pad_left + 10}" y="{ly}" width="12" height="12" fill="{color}" rx="2"/>')
        parts.append(f'<text x="{pad_left + 26}" y="{ly + 9}" font-size="10" fill="#333">{name}</text>')

    parts.append('</svg>')
    return ''.join(parts)


def _generate_absolute_multi_svg(tumor_marker_tables: Dict[str, Any]) -> str:
    """生成多指标绝对值对比图 SVG（小 multiples 布局）。

    每个指标独立 Y 轴，共享 X 轴日期，便于观察真实数值与参考范围。
    """
    if not tumor_marker_tables:
        return ''

    # 过滤有效指标（>=2 个有效数值），最多保留 6 个
    valid_series: List[tuple[str, str, Dict[str, Any], List[tuple[str, float, bool]]]] = []
    for idx, (name, data) in enumerate(tumor_marker_tables.items()):
        rows = data.get('rows') or []
        points: List[tuple[str, float, bool]] = []
        valid = 0
        for r in rows:
            try:
                v = float(r.get('value'))  # type: ignore[arg-type]
            except (ValueError, TypeError):
                continue
            date = r.get('date', '') or ''
            points.append((date, v, bool(r.get('is_abnormal'))))
            valid += 1
        if valid >= 2:
            color = _MARKER_COLORS[idx % len(_MARKER_COLORS)]
            valid_series.append((name, color, data, points))
    if not valid_series:
        return ''
    if len(valid_series) > 6:
        valid_series = valid_series[:6]

    # 统一日期轴
    all_dates = sorted({d for _, _, _, pts in valid_series for d, _, _ in pts if d})
    if not all_dates:
        return ''
    date_to_x = {d: i for i, d in enumerate(all_dates)}

    # 小 multiples 布局：每行最多 3 个
    cols = min(3, len(valid_series))
    rows_needed = (len(valid_series) + cols - 1) // cols

    cell_w = 160
    cell_h = 100
    gap = 16
    legend_h = 20
    width = max(520, cols * cell_w + (cols + 1) * gap)
    height = rows_needed * (cell_h + gap) + legend_h + 40

    def to_x(date: str, offset_x: float) -> float:
        if len(all_dates) <= 1:
            return offset_x + cell_w / 2
        return offset_x + (cell_w / (len(all_dates) - 1)) * date_to_x.get(date, 0)

    parts: List[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'style="max-width:100%;height:auto;">'
    )
    parts.append(f'<rect width="{width}" height="{height}" fill="#fafbfc"/>')

    # 绘制每个指标的小图
    for i, (name, color, data, pts) in enumerate(valid_series):
        col = i % cols
        row = i // cols
        ox = gap + col * (cell_w + gap)
        oy = gap + row * (cell_h + gap)

        values = [v for _, v, _ in pts]
        v_min = min(values)
        v_max = max(values)
        v_range = max(v_max - v_min, v_max * 0.2, 1)
        v_low = v_min - v_range * 0.1
        v_high = v_max + v_range * 0.1
        v_range = v_high - v_low

        def cell_to_y(v: float) -> float:
            if v_range == 0:
                return oy + cell_h / 2
            return oy + cell_h - ((v - v_low) / v_range) * cell_h

        # 背景
        parts.append(f'<rect x="{ox}" y="{oy}" width="{cell_w}" height="{cell_h}" fill="#fff" stroke="#e5e7eb" stroke-width="1" rx="4"/>')

        # 参考范围阴影
        ref = data.get('ref_range')
        if isinstance(ref, (list, tuple)) and len(ref) == 2:
            try:
                r_low = float(ref[0])
                r_high = float(ref[1])
                y1 = cell_to_y(max(r_high, v_high))
                y2 = cell_to_y(min(r_low, v_low))
                parts.append(f'<rect x="{ox + 1}" y="{min(y1, y2):.1f}" width="{cell_w - 2}" height="{abs(y2 - y1):.1f}" fill="#d4edda" opacity="0.4"/>')
            except (ValueError, TypeError):
                pass

        # 折线
        line_pts = [f'{to_x(d, ox):.1f},{cell_to_y(v):.1f}' for d, v, _ in pts]
        if line_pts:
            parts.append(f'<polyline points="{" ".join(line_pts)}" fill="none" stroke="{color}" stroke-width="1.5"/>')

        # 圆点
        for d, v, abn in pts:
            cx = to_x(d, ox)
            cy = cell_to_y(v)
            stroke = '#e74c3c' if abn else color
            sw = 2 if abn else 1
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.5" fill="{color}" stroke="{stroke}" stroke-width="{sw}"/>')

        # 指标名称
        parts.append(f'<text x="{ox + 4}" y="{oy + 12}" font-size="10" font-weight="700" fill="#333">{name}</text>')

    parts.append('</svg>')
    return ''.join(parts)


def _analyze_marker_synchronization(tumor_marker_tables: Dict[str, Any]) -> str:
    """分析指标同步性，返回告警提示文本或空字符串。"""
    if not tumor_marker_tables:
        return ''

    directions: Dict[str, str] = {}
    for name, data in tumor_marker_tables.items():
        rows = data.get('rows') or []
        vals: List[float] = []
        for r in rows:
            try:
                vals.append(float(r.get('value')))  # type: ignore[arg-type]
            except (ValueError, TypeError):
                continue
        if len(vals) < 2:
            continue
        last = vals[-1]
        prev = vals[-2]
        if prev == 0:
            continue
        pct = (last - prev) / abs(prev) * 100
        if pct >= 10:
            directions[name] = '上升'
        elif pct <= -10:
            directions[name] = '下降'

    up_items = [k for k, v in directions.items() if v == '上升']
    down_items = [k for k, v in directions.items() if v == '下降']

    if len(up_items) >= 3:
        names = '、'.join(up_items[:5])
        return f'同步性提示：{names} 近 2 次检测呈同向上升趋势，需警惕疾病活动度增加，建议结合影像评估。'
    if len(down_items) >= 3:
        names = '、'.join(down_items[:5])
        return f'同步性提示：{names} 近 2 次检测呈同向下降趋势，提示病情缓解趋势，请继续监测。'
    return ''


def _is_manifest(data: Dict[str, Any]) -> bool:
    """判断是否为 manifest 结构（旧格式）。"""
    return bool(
        data.get('categories_summary')
        or data.get('files')
        or ('demographics' in data and 'name' in (data.get('demographics') or {}))
    )


def _compute_context_from_manifest(
    manifest: Dict[str, Any],
    *,
    timeline: Optional[List[Dict[str, Any]]] = None,
    extracted_texts: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """从 manifest 结构构建 context（旧测试兼容路径）。"""
    demographics = manifest.get('demographics', {}) or {}
    files = manifest.get('files', []) or []

    # 简化 timeline
    simple_tl: List[Dict[str, Any]] = []
    if timeline:
        for item in timeline:
            simple_tl.append({
                'dates': item.get('dates', []),
                'title': item.get('title') or item.get('file', ''),
                'category': item.get('category', ''),
            })

    # 检验指标（旧测试无 lab_trends，留空）
    lab_trend: List[Dict[str, Any]] = []
    tumor_marker_tables: Dict[str, Any] = {}

    # 影像
    imaging_summary: List[Dict[str, Any]] = []
    categories = manifest.get('categories_summary', {}) or {}
    if 'imaging' in categories:
        for fe in files:
            cat = fe.get('category', '')
            if cat and cat.startswith('imaging'):
                imaging_summary.append({
                    'date': fe.get('date_detected') or '日期待确认',
                    'modality': fe.get('title', '') or '影像',
                    'findings': '',
                })

    # 病理
    pathology: List[Dict[str, Any]] = []
    if 'pathology' in categories:
        for fe in files:
            cat = fe.get('category', '')
            if cat and cat.startswith('pathology'):
                pathology.append({
                    'label': fe.get('title', ''),
                    'type': '病理',
                    'date': fe.get('date_detected') or '日期待确认',
                    'summary': '详见报告',
                    'findings': [],
                    'value': '',
                    'is_critical': False,
                })

    # 用药
    medication: Dict[str, List[str]] = {'current': [], 'history': []}
    if 'medication' in categories:
        for fe in files:
            cat = fe.get('category', '')
            if cat and cat.startswith('medication'):
                medication['current'].append(fe.get('title', ''))
                medication['history'].append(fe.get('title', ''))

    # 基因检测
    genetic_highlights: List[Dict[str, Any]] = []
    combined_text = '\n'.join(extracted_texts or [])
    if extra and extra.get('extracted_texts'):
        combined_text = '\n'.join(extra['extracted_texts'])

    from scripts.parse_genetics import parse_genetics, format_genetic_highlights_md
    highlights = parse_genetics(combined_text)
    for h in highlights:
        genetic_highlights.append({
            'category': 'gene',
            'gene': h.gene,
            'marker': h.gene,
            'mutation': h.mutation or h.position,
            'result': h.mutation or h.position,
            'pathogenic': h.pathogenic,
            'is_critical': h.pathogenic or False,
            'tags': [h.drug_sensitivity] if h.drug_sensitivity else [],
        })

    # 危急值
    critical_alerts: List[Dict[str, Any]] = []
    if combined_text:
        from scripts.critical_values import check_critical_values
        alerts = check_critical_values(combined_text)
        for a in alerts:
            critical_alerts.append({
                'item_name': a.item_name,
                'value': a.value,
                'unit': a.unit,
                'level': a.level,
                'message': a.message,
                'emoji': a.emoji,
                'action': a.action,
            })
    has_critical = any(a['level'] >= 4 for a in critical_alerts)

    # 关注问题
    key_concerns: List[str] = [a['message'] for a in critical_alerts]

    # 咨询问题
    consultation_questions: List[str] = [
        '建议补充历次肿瘤标志物结果以完善趋势分析',
        '建议补充用药方案详细信息（药物、剂量、周期）',
        '建议补充病理报告（组织学类型、免疫组化）',
    ]
    if not imaging_summary:
        consultation_questions.insert(0, '建议补充影像检查报告')

    # 文件列表
    files_list: List[Dict[str, Any]] = []
    for fe in files:
        files_list.append({
            'title': fe.get('title') or fe.get('original_name', ''),
            'date': fe.get('date_detected') or '日期待确认',
            'category': fe.get('category', '未分类'),
        })

    # 缺口
    gaps: List[str] = []
    if not lab_trend and not tumor_marker_tables:
        gaps.append('缺少检验指标趋势数据')
    if not medication.get('current'):
        gaps.append('缺少用药方案记录')
    if not pathology:
        gaps.append('缺少病理报告')
    if not demographics.get('name'):
        gaps.append('缺少患者基本信息')

    # 用药概要
    medication_summary: List[Dict[str, Any]] = [
        {'label': '当前用药', 'value': f"{len(medication.get('current', []))} 种", 'is_critical': False},
        {'label': '历史用药', 'value': f"{len(medication.get('history', []))} 种", 'is_critical': False},
    ]
    medication_table: List[Dict[str, Any]] = []

    primary_dx = demographics.get('primary_diagnosis', '')
    report_title = f'{primary_dx}患者病情概览' if primary_dx else '患者病情概览'

    return {
        'demographics': demographics,
        'has_critical': has_critical,
        'critical_alerts': critical_alerts,
        'timeline': simple_tl,
        'pathology': pathology,
        'pathology_tag': None,
        'genetic_highlights': genetic_highlights,
        'ihc_note': None,
        'medication_summary': medication_summary,
        'medication_table': medication_table,
        'medication_prescription_date': manifest.get('updated_at', '')[:10] if manifest.get('updated_at') else '',
        'medication': medication,
        'imaging_summary': imaging_summary,
        'tumor_marker_tables': tumor_marker_tables,
        'lab_trend': lab_trend,
        'chart_svg_ca199': '',
        'chart_svg': '',
        'key_concerns': key_concerns,
        'consultation_questions': consultation_questions,
        'files': files_list,
        'gaps': gaps,
        'updated_at': manifest.get('updated_at', ''),
        'report_title': report_title,
    }


def _sanitize_report_context(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """递归 sanitize report_context 中的动态字符串，防止 XSS"""
    import re
    from copy import deepcopy

    ctx = deepcopy(ctx)
    # 移除事件处理器属性
    _ON_EVENT_RE = re.compile(r'\s*on\w+\s*=\s*("[^"]*"|\'[^\']*\')')

    def _clean_value(v):
        if isinstance(v, str):
            # 移除事件处理器
            v = _ON_EVENT_RE.sub('', v)
            return v
        if isinstance(v, dict):
            return {k: _clean_value(val) for k, val in v.items()}
        if isinstance(v, list):
            return [_clean_value(item) for item in v]
        return v

    # 重点字段 sanitize
    for key in [
        "report_title",
        "consultation_questions",
        "key_concerns",
        "files",
        "timeline",
        "genetic_highlights",
        "critical_alerts",
    ]:
        if key in ctx:
            ctx[key] = _clean_value(ctx[key])

    # demographics
    if "demographics" in ctx and isinstance(ctx["demographics"], dict):
        ctx["demographics"] = _clean_value(ctx["demographics"])

    return ctx


# ---------------------------------------------------------------------------
# 渲染入口
# ---------------------------------------------------------------------------
def render_html_report(
    profile: Dict[str, Any],
    groups: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    output_dir: Optional[Path] = None,
    *,
    output_path: Optional[Path] = None,
    timeline: Optional[List[Dict[str, Any]]] = None,
    extra: Optional[Dict[str, Any]] = None,
    report_context: Optional[Dict[str, Any]] = None,
) -> Optional[Path]:
    """渲染 HTML 报告。返回输出路径，失败返回 None。

    兼容两种调用方式：
    1. render_html_report(profile, groups, output_dir) — 新 pipeline 方式
    2. render_html_report(manifest, timeline=..., output_path=...) — 旧测试兼容
    """
    # 向后兼容：如果 output_path 提供，优先使用
    if output_path is not None:
        _output_path = Path(output_path)
    elif output_dir is not None:
        _output_path = Path(output_dir) / 'report.html'
    else:
        _output_path = _PROJECT_ROOT / 'output' / 'report.html'

    if not _JINJA2_AVAILABLE:
        logger.warning('Jinja2 未安装，跳过 HTML 渲染')
        return None

    if not _TEMPLATE_PATH.exists():
        logger.warning('模板文件不存在: %s', _TEMPLATE_PATH)
        return None

    # 如果提供了 report_context，优先使用
    if report_context is not None:
        ctx = report_context
    else:
        ctx = compute_report_context(
            profile, groups=groups, timeline=timeline, extracted_texts=None, extra=extra
        )

    # 最终兜底：渲染前再 sanitize 一遍动态字段，防止绕过
    safe_ctx = _sanitize_report_context(ctx)

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
        html = template.render(**safe_ctx)
        _output_path.write_text(html, encoding='utf-8')
        logger.info('HTML 报告已生成: %s', _output_path)
        return _output_path
    except Exception as exc:
        logger.exception('模板渲染失败: %s', exc)
        return None
