"""
AI-MDT 多学科关注问题分析。

目标：把已有的结构化分析结果（lab / imaging / pathology / medication / timeline）
交给多个专科角色分别分析，再由 MDT 主席整合为不重叠、可执行的关注要点。

说明：
- 这是报告级别的资料整理与结构化分析，不做诊断。
- 输出尽量保持可解释、可追溯，优先给出跨学科结论而不是数据罗列。
- 任一专科失败时，返回空结果或降级结果，不中断整体报告生成。
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from scripts.llm_client import call_llm_with_retry

logger = logging.getLogger(__name__)


SPECIALTY_ORDER = [
    'oncology',
    'radiology',
    'pathology',
    'pharmacy',
    'nursing',
]

SPECIALTY_LABELS = {
    'oncology': '肿瘤内科',
    'radiology': '影像科',
    'pathology': '病理科',
    'pharmacy': '临床药学',
    'nursing': '护理',
}


MDT_SPECIALTY_SCHEMA: Dict[str, Any] = {
    'type': 'object',
    'properties': {
        'concerns': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'title': {'type': 'string'},
                    'analysis': {'type': 'string'},
                    'priority': {'type': 'string'},
                    'discipline': {'type': 'string'},
                    'evidence': {'type': 'array', 'items': {'type': 'string'}},
                    'suggested_direction': {'type': 'string'},
                },
            },
        },
    },
}

MDT_SYNTHESIS_SCHEMA: Dict[str, Any] = {
    'type': 'object',
    'properties': {
        'concerns': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'title': {'type': 'string'},
                    'analysis': {'type': 'string'},
                    'priority': {'type': 'string'},
                    'disciplines': {'type': 'array', 'items': {'type': 'string'}},
                    'suggested_direction': {'type': 'string'},
                    'evidence': {'type': 'array', 'items': {'type': 'string'}},
                },
            },
        },
        'consultation_questions': {
            'type': 'array',
            'items': {'type': 'string'},
            'description': '基于异常发现，提出3-5条下次问诊时需向医生确认的关键问题',
        },
    },
}


ONCOLOGY_PROMPT = """你是一位资深肿瘤内科 MDT 专家，正在参加多学科会诊。
你只从【肿瘤内科】视角分析，不做影像读片、不做病理诊断、不调整具体剂量。

【患者信息】
{patient_info}

【检验指标趋势】
{lab_trends}

【检验指标分析（含连续上升次数/趋势/预警级别）】
{lab_analysis}

【最近疗效与治疗线索】
{medication_timeline}

【时间线】
{timeline}

【任务】
请基于以上结构化数据，提炼 2-3 条最值得关注的肿瘤内科问题。
要求：
1. 标题要带**具体指标 + 起始时间/方向**（如"CEA 趋势：自 2025-07 起连续上升 N 次"），禁止空泛类目标题。
2. 利用 lab_analysis 里的 consecutive_rises/trend_summary：若某指标连续上升，直接点明"自 X 月起连续上升 N 次"。
3. 若多个指标同向变化，请指出是否支持疾病活动度变化。
4. 若当前疗效稳定或下降，请明确写出"与影像/治疗线索是否一致"。
5. 每条 analysis 限 1-2 句，要像会诊发言，不要堆数值。
6. 只输出 JSON。

输出格式：
{
  "concerns": [
    {
      "title": "带指标+时间的具体判断",
      "analysis": "跨数据分析结论",
      "priority": "high|medium|low",
      "discipline": "oncology",
      "evidence": ["证据1", "证据2"],
      "suggested_direction": "建议关注方向"
    }
  ]
}
"""

RADIOLOGY_PROMPT = """你是一位资深影像科 MDT 专家，正在参加多学科会诊。
你只从【影像科】视角分析，不做临床诊断下结论。

【患者信息】
{patient_info}

【影像摘要】
{imaging_summary}

【影像叙事】
{imaging_narrative}

【时间线】
{timeline}

【任务】
请输出 2-3 条影像学层面的关注问题。
要求：
1. 聚焦原发灶、转移灶、积液、缩小/增大、稳定/进展。
2. 强调与前片对比，不要复述每一条原文。
3. 若病灶趋势与肿瘤标志物趋势一致/不一致，请指出。
4. 只输出 JSON。

输出格式同上，discipline 固定为 radiology。
"""

PATHOLOGY_PROMPT = """你是一位资深病理科 MDT 专家，正在参加多学科会诊。
你只从【病理科】视角分析，不作临床诊断。

【患者信息】
{patient_info}

【病理摘要】
{pathology}

【基因/免疫组化】
{genetics}

【任务】
请输出 2-3 条病理与分子层面的关注问题。
要求：
1. 聚焦组织学类型、免疫表型、驱动/致病突变、药物代谢风险。
2. 若有 UGT1A1 / ATM / KRAS / PD-L1 / MSI / TMB 等，请结合治疗风险或分层意义表述。
3. 不要解释成诊断结论，要写成“关注点”。
4. 只输出 JSON。
"""

PHARMACY_PROMPT = """你是一位资深临床药师 MDT 专家，正在参加多学科会诊。
你只从【药学】视角分析，不直接调整处方。

【患者信息】
{patient_info}

【用药方案】
{medication_timeline}

【基因/毒性提示】
{genetics}

【任务】
请输出 2-3 条药学关注问题。
要求：
1. 聚焦方案持续性、累计疗程、副作用、药物毒性风险、支持治疗。
2. 识别可能影响后续方案选择的毒性线索。
3. 关注药物代谢基因与潜在毒性/剂量风险之间的关系。
4. 只输出 JSON。
"""

NURSING_PROMPT = """你是一位资深肿瘤护理 MDT 专家，正在参加多学科会诊。
你只从【护理】视角分析，关注症状管理、依从性、风险监测。

【患者信息】
{patient_info}

【症状/不良反应】
{toxicities}

【信息缺口】
{gaps}

【任务】
请输出 2-3 条护理关注问题。
要求：
1. 聚焦症状负担、生活质量、导管/置管、营养、神经毒性、依从性。
2. 结合缺口信息指出还需要追问/补充什么。
3. 不要泛泛而谈。
4. 只输出 JSON。
"""

SYNTHESIS_PROMPT = """你是 MDT 会诊主席，正在做最后的总结发言。
下面有 5 个专科的关注要点。请整合成一份**少而精、不重复**的核心关注问题清单。

参考这种“历史满意版”的语气——标题就是一个带日期/数值的判断，分析紧跟一句证据+方向：
- “CEA 趋势：2025-07 起逐步升高，10 月后虽回落但仍需密切监测”
- “CA199 趋势：自 2025-10 起持续缓慢上升，需结合影像继续评估”
- “药物毒性：UGT1A1 纯合，后续若涉及伊立替康需警惕毒性风险”
- “护理重点：手脚麻木提示周围神经毒性，支持治疗与症状管理应持续关注”

【专科结果】
{specialty_reports}

【整合原则】
1. **只输出 4-6 条**，宁缺毋滥；相近问题必须合并，不要凑数。
2. 标题（title）必须是一个**具体的、带时间或数值的判断**，禁止用“病情观察”“综合管理”这类空泛类目。
3. 分析（analysis）限 1-2 句：给出跨学科证据（哪几个学科、哪些数据关联），再给一个关注方向。禁止堆砌原始数值。
4. 优先级排序：high > medium > low；真正影响决策的放 high。
5. disciplines 填入涉及到的专科（英文 key：oncology/radiology/pathology/pharmacy/nursing），跨学科问题写多个。

【输出格式】
{{
  "concerns": [
    {{
      "title": "带日期/数值的具体判断标题",
      "analysis": "1-2 句跨学科证据 + 关注方向",
      "priority": "high|medium|low",
      "disciplines": ["oncology", "radiology"],
      "suggested_direction": "建议关注方向",
      "evidence": ["证据1", "证据2"]
    }}
  ]
}}
"""


def _safe_text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def _build_patient_info(profile: Dict[str, Any]) -> str:
    demographics = profile.get('demographics') or {}
    items = [
        f"姓名：{demographics.get('name', '')}",
        f"性别：{demographics.get('gender', '')}",
        f"年龄：{demographics.get('age', '')}",
        f"主要诊断：{demographics.get('primary_diagnosis', '')}",
        f"疾病编码：{demographics.get('icd_code', '')}",
    ]
    return '\n'.join(items)


def _resolve_demographics(profile: Dict[str, Any], groups: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """优先用 profile.demographics；缺失时从 groups[basic_info/demographics] 抽。

    pipeline_v2 传入的 profile 草稿 demographics 为空，真实信息在 groups 里，
    这里兜底抽取，避免 MDT 文案拿不到患者背景（P0）。
    """
    demographics = dict(profile.get('demographics') or {})
    if demographics.get('name') or demographics.get('gender') or demographics.get('age'):
        return demographics
    for key in ('demographics', 'basic_info'):
        for item in (groups.get(key) or []):
            if isinstance(item, dict):
                candidate = item.get('demographics')
                if isinstance(candidate, dict) and candidate:
                    demographics.update(candidate)
                    if demographics.get('name') or demographics.get('gender') or demographics.get('age'):
                        return demographics
    return demographics


def _build_data_bundle(profile: Dict[str, Any], groups: Dict[str, List[Dict[str, Any]]]) -> Dict[str, str]:
    med_timeline = profile.get('medication_timeline') or {}
    imaging_narr = profile.get('imaging_narrative') or {}
    lab_trends = profile.get('lab_trends') or {}
    lab_analysis = profile.get('lab_analysis') or {}
    pathology = groups.get('pathology') or []
    imaging = groups.get('imaging') or []
    med_group = groups.get('medication') or []
    demographics = _resolve_demographics(profile, groups)
    bundle_profile = {**profile, 'demographics': demographics}

    pathology_summary = []
    genetics_summary = []
    for item in pathology:
        pathology_summary.append({
            'date': item.get('document_date') or item.get('report_date') or '',
            'summary': item.get('conclusion') or item.get('findings') or '',
            'specimen_type': item.get('specimen_type', ''),
            'test_items': item.get('test_items') or [],
        })
        for gene in item.get('test_items') or []:
            if isinstance(gene, dict):
                genetics_summary.append(gene)

    imaging_summary = []
    for item in imaging:
        imaging_summary.append({
            'date': item.get('document_date') or item.get('report_date') or '',
            'modality': item.get('modality', ''),
            'findings': item.get('findings') or [],
            'conclusion': item.get('conclusion', ''),
        })

    toxicities = med_timeline.get('toxicities') or []
    response_assessments = med_timeline.get('response_assessments') or []

    return {
        'patient_info': _build_patient_info(bundle_profile),
        'lab_trends': _safe_text(lab_trends),
        'lab_analysis': _safe_text(lab_analysis),
        'medication_timeline': _safe_text({
            'regimens': med_timeline.get('regimens', []),
            'cycles': med_timeline.get('cycles', []),
            'response_assessments': response_assessments,
            'toxicities': toxicities,
            'timeline': med_timeline.get('timeline', []),
        }),
        'timeline': _safe_text(profile.get('timeline') or []),
        'imaging_summary': _safe_text(imaging_summary),
        'imaging_narrative': _safe_text(imaging_narr),
        'pathology': _safe_text(pathology_summary),
        'genetics': _safe_text(genetics_summary),
        'toxicities': _safe_text(toxicities),
        'gaps': _safe_text(profile.get('gaps') or []),
        'med_group': _safe_text(med_group),
    }


def _call_role(prompt: str, data: Dict[str, str], *, model: Optional[str] = None) -> Dict[str, Any]:
    messages = [{
        'role': 'user',
        'content': prompt.format(**data),
    }]
    result = call_llm_with_retry(messages, MDT_SPECIALTY_SCHEMA, model=model)
    if not isinstance(result, dict):
        return {'concerns': []}
    concerns = result.get('concerns') or []
    if not isinstance(concerns, list):
        concerns = []
    return {'concerns': concerns}


def _fallback_specialty(role: str, data: Dict[str, str]) -> Dict[str, Any]:
    concerns: List[Dict[str, Any]] = []
    if role == 'oncology':
        concerns.append({
            'title': '标志物与影像是否一致',
            'analysis': '肿瘤标志物趋势与影像总体评估需要联合判断，避免只看单一指标。',
            'priority': 'high',
            'discipline': 'oncology',
            'evidence': ['lab_trends', 'imaging_narrative'],
            'suggested_direction': '继续结合近期影像和连续指标趋势观察病情活动度。',
        })
    elif role == 'radiology':
        concerns.append({
            'title': '影像上是否仍以稳定/缩小为主',
            'analysis': '当前影像需重点判断原发灶与腹膜/转移灶是否继续缩小或出现反弹。',
            'priority': 'high',
            'discipline': 'radiology',
            'evidence': ['imaging_summary', 'imaging_narrative'],
            'suggested_direction': '重点关注与前片对比的变化是否一致。',
        })
    elif role == 'pathology':
        concerns.append({
            'title': '病理与分子提示是否影响后续分层',
            'analysis': '免疫表型与基因/药物代谢信息会影响后续治疗风险评估与方案选择。',
            'priority': 'medium',
            'discipline': 'pathology',
            'evidence': ['pathology', 'genetics'],
            'suggested_direction': '关注驱动/致病突变及药物代谢风险。',
        })
    elif role == 'pharmacy':
        concerns.append({
            'title': '累计化疗与毒性是否需要支持治疗强化',
            'analysis': '长期化疗下，神经毒性、营养风险及药物代谢背景需要综合考虑。',
            'priority': 'high',
            'discipline': 'pharmacy',
            'evidence': ['medication_timeline', 'genetics'],
            'suggested_direction': '关注毒性积累与支持治疗是否充分。',
        })
    else:
        concerns.append({
            'title': '症状与依从性是否需要追问',
            'analysis': '护理层面应持续关注神经毒性、营养、置管与症状负担。',
            'priority': 'medium',
            'discipline': 'nursing',
            'evidence': ['toxicities', 'gaps'],
            'suggested_direction': '补充症状和生活质量信息。',
        })
    return {'concerns': concerns}


def _synthesis_fallback_concerns() -> List[Dict[str, Any]]:
    """整合失败时的兜底关注问题：少而精、跨学科、更像会诊总结而非大锅饭。"""
    return [
        {
            'title': '肿瘤标志物趋势与影像变化需联合判断',
            'analysis': 'CEA、CA199 等指标若出现同向或连续变化，应结合近期影像复查是否一致，避免只看单一指标下结论。',
            'priority': 'high',
            'disciplines': ['oncology', 'radiology'],
            'suggested_direction': '关注近期标志物趋势与影像复查是否同步。',
            'evidence': ['lab_trends', 'imaging_narrative'],
        },
        {
            'title': '累计化疗后的毒性与支持治疗需持续关注',
            'analysis': '长期化疗下神经毒性、营养风险与药物代谢背景（如 UGT1A1）共同影响耐受性，应综合评估支持治疗是否充分。',
            'priority': 'medium',
            'disciplines': ['pharmacy', 'nursing'],
            'suggested_direction': '继续关注神经毒性、营养状态与导管维护。',
            'evidence': ['medication_timeline', 'genetics', 'toxicities'],
        },
        {
            'title': '症状管理：手脚麻木/营养/置管等护理重点',
            'analysis': '护理层面应持续追踪症状负担、依从性与生活质量，并及时补充缺失信息。',
            'priority': 'medium',
            'disciplines': ['nursing'],
            'suggested_direction': '补充症状与生活质量信息，加强随访。',
            'evidence': ['toxicities', 'gaps'],
        },
    ]


def run_mdt_analysis(profile: Dict[str, Any], groups: Dict[str, List[Dict[str, Any]]], *, model: Optional[str] = None) -> Dict[str, Any]:
    """执行 MDT 多专科分析并整合为关注问题。

    返回结构（始终包含 4 个 key，便于 pipeline 落盘 JSON）：
      {
        'specialty_reports': {role: {'concerns': [...]}},
        'concerns': [...],              # 整合后的核心关注问题
        'fallback_used': {role: bool, ..., 'synthesis': bool},
        'error': str | None,
      }
    任何异常都不会抛出，最坏情况返回带 error 的兜底结构。
    """
    fallback_used: Dict[str, bool] = {role: False for role in SPECIALTY_ORDER}
    fallback_used['synthesis'] = False

    try:
        data = _build_data_bundle(profile, groups)
    except Exception as exc:
        logger.exception('MDT 数据打包失败：%s', exc)
        return {
            'specialty_reports': {},
            'concerns': _synthesis_fallback_concerns(),
            'fallback_used': {**fallback_used, 'synthesis': True},
            'error': f'data_bundle_failed: {exc}',
        }

    specialty_results: Dict[str, Dict[str, Any]] = {}
    prompts = {
        'oncology': ONCOLOGY_PROMPT,
        'radiology': RADIOLOGY_PROMPT,
        'pathology': PATHOLOGY_PROMPT,
        'pharmacy': PHARMACY_PROMPT,
        'nursing': NURSING_PROMPT,
    }

    with ThreadPoolExecutor(max_workers=len(prompts)) as executor:
        future_map = {
            executor.submit(_call_role, prompt, data, model=model): role
            for role, prompt in prompts.items()
        }
        for future in as_completed(future_map):
            role = future_map[future]
            try:
                specialty_results[role] = future.result()
            except Exception as exc:
                logger.warning('MDT 专科分析失败 role=%s: %s', role, exc)
                fallback_used[role] = True
                specialty_results[role] = _fallback_specialty(role, data)

    # 若某专科 LLM 返回空 concerns，也视为降级
    for role in SPECIALTY_ORDER:
        items = (specialty_results.get(role) or {}).get('concerns')
        if not items:
            fallback_used[role] = True

    synthesis_messages = [{
        'role': 'user',
        'content': SYNTHESIS_PROMPT.format(
            specialty_reports=json.dumps(specialty_results, ensure_ascii=False, indent=2)
        ),
    }]
    concerns: List[Dict[str, Any]] = []
    try:
        synthesis = call_llm_with_retry(synthesis_messages, MDT_SYNTHESIS_SCHEMA, model=model)
        raw = synthesis.get('concerns') if isinstance(synthesis, dict) else None
        questions = synthesis.get('consultation_questions') if isinstance(synthesis, dict) else None
        if isinstance(raw, list):
            concerns = [c for c in raw if isinstance(c, dict)]
    except Exception as exc:
        logger.warning('MDT 整合失败，回退为专科结果拼接: %s', exc)

    if not concerns:
        fallback_used['synthesis'] = True
        # 优先拼接专科结果，再退到统一兜底
        for role in SPECIALTY_ORDER:
            for item in (specialty_results.get(role) or {}).get('concerns') or []:
                if isinstance(item, dict):
                    concerns.append({
                        'title': item.get('title', ''),
                        'analysis': item.get('analysis', ''),
                        'priority': item.get('priority', 'medium'),
                        'disciplines': [item.get('discipline', role)] if item.get('discipline', role) else [role],
                        'suggested_direction': item.get('suggested_direction', ''),
                        'evidence': item.get('evidence', []),
                    })
        if not concerns:
            concerns = _synthesis_fallback_concerns()

    # 规范化 priority，避免模板渲染出意外值
    for c in concerns:
        if c.get('priority') not in ('high', 'medium', 'low'):
            c['priority'] = 'medium'

    return {
        'specialty_reports': specialty_results,
        'concerns': concerns,
        'consultation_questions': questions if isinstance(questions, list) and questions else [],
        'fallback_used': fallback_used,
        'error': None,
    }
