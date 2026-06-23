# 病例档案模板

{% set demo = demographics or {} %}

============================================================
         患 病 情 档 案
============================================================

{% if has_critical %}
╔══════════════════════════════════════════════════════════╗
║  🆘 危急值警报 — 请立即就医！                        ║
╠══════════════════════════════════════════════════════════╣
{% for alert in critical_alerts if alert.level >= 4 %}
║  {{ alert.emoji }} {{ alert.message }}
{% endfor %}
╚══════════════════════════════════════════════════════════╝

{% endif %}

【基本信息】
  患者：{{ demo.name | default("XXX") }}
  性别：{{ demo.gender | default("男/女") }}
  年龄：{{ demo.age | default("XX") }}岁
  建档日期：{{ (created_at or "YYYY-MM-DD")[:10] }}
  最后更新：{{ (updated_at or "YYYY-MM-DD")[:10] }}
  主要诊断：{{ demo.primary_diagnosis | default("XXXXXXXXXX") }}

【近期病情重点提示】
{% if recent_focus %}
{% for item in recent_focus %}
  ⚡ {{ item }}
{% endfor %}
{% else %}
  （暂无近期重点提示）
{% endif %}

【诊疗时间线】
{% for item in timeline %}
  ─ {{ item.dates[0] if item.dates else "YYYY-MM-DD" }}  {{ item.title }}
{% else %}
  ─ （暂无时间线数据）
{% endfor %}

【检验指标趋势】
{% if lab_trend %}
  日期        CEA     CA125    ALT    AST    Cr
  {% for row in lab_trend %}
  {{ row.date }}  {{ row.cea }}  {{ row.ca125 }}  {{ row.alt }}  {{ row.ast }}  {{ row.cr }}
  {% endfor %}
{% else %}
  （暂无检验指标数据）
{% endif %}

【影像检查摘要】
{% if imaging_summary %}
{% for item in imaging_summary %}
  {{ item.date }} {{ item.modality }}：{{ item.findings }}
{% endfor %}
{% else %}
  （暂无影像检查数据）
{% endif %}

【用药方案】
{% if medication %}
  当前用药：
  {% for m in medication.current %}
    - {{ m }}
  {% endfor %}
  历史用药：
  {% for m in medication.history %}
    - {{ m }}
  {% endfor %}
{% else %}
  （暂无用药数据）
{% endif %}

【病理报告摘要】
{% if pathology %}
{% for item in pathology %}
  {{ item.date }} {{ item.type }}：{{ item.summary }}
{% endfor %}
{% else %}
  （暂无病理数据）
{% endif %}

【基因与病理重点提示】
{% if genetic_highlights %}
{% for gh in genetic_highlights %}
  - {% if gh.gene == '病理类型' %}**病理类型**：{{ gh.pathology_type }}
    {% elif gh.level == 'info' %}**药物代谢基因**：{{ gh.gene }}（{{ gh.raw_text or '见原始报告' }}）
    {% else %}**{{ gh.gene }}**{% if gh.position %} 点位 {{ gh.position }}{% endif %}{% if gh.abundance %} 丰度 {{ gh.abundance }}{% endif %}{% if gh.mutation %} 突变 {{ gh.mutation }}{% endif %}{% if gh.breakthrough_type %} 突破 {{ gh.breakthrough_type }}{% endif %}{% if gh.drug_sensitivity %} 药物敏感 {{ gh.drug_sensitivity }}{% endif %}{% if gh.immune_marker %} 免疫 {{ gh.immune_marker }}{% endif %}
  {% endif %}
{% endfor %}
{% else %}
  （暂无基因/病理重点提示，建议补充基因检测报告）
{% endif %}

【关注问题要点】
{% if key_concerns %}
{% for concern in key_concerns %}
  ⚠️ {{ concern }}
{% endfor %}
{% else %}
  （暂无关注问题要点）
{% endif %}

【问诊咨询建议】
{% if consultation_questions %}
{% for q in consultation_questions %}
  ❓ {{ q }}
{% endfor %}
{% else %}
  （暂无问诊咨询建议）
{% endif %}

【完整资料目录】
{% for f in files %}
  {{ loop.index }}. {{ f.title }}（{{ f.date or "日期待确认" }}） ............... 附件 P.{{ loop.index }}
{% endfor %}

【信息缺口提示】
{% if gaps %}
{% for g in gaps %}
  ⚠️ {{ g }}
{% endfor %}
{% else %}
  （暂无缺口提示）
{% endif %}

============================================================
⚠️ 免责声明
   本病例档案仅为医疗资料整理，不构成任何诊断或治疗建议。
   如有疑问请联系主治医师。
============================================================
