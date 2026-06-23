"""
HTML 报告渲染器 V2（卡片式布局 + 折叠详情）

基于 references/html-report-design.md 设计规范实现。
"""
from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "references"
_DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "output"


def _escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _meta_security_tags() -> str:
    return (
        '<meta http-equiv="Content-Security-Policy" '
        'content="default-src \'self\'; script-src \'self\' \'unsafe-inline\' https://cdn.jsdelivr.net; object-src \'none\'; base-uri \'none\'">\n'
        '  <meta name="robots" content="noindex,nofollow">'
    )


# ---------------------------------------------------------------------------
# 组件 HTML 生成器
# ---------------------------------------------------------------------------

def _card(title: str, body: str, icon: str = "", color: str = "#2563eb", default_open: bool = True) -> str:
    """生成卡片组件"""
    return f"""
<div class="card">
  <div class="card-header" style="background-color: {color};">
    <div class="header-content">
      <span class="icon">{icon}</span>
      <span class="title">{_escape(title)}</span>
    </div>
  </div>
  <div class="card-body" {'style="display:block;"' if default_open else 'style="display:none;"'}>
    {body}
  </div>
</div>"""


def _collapsible(title: str, body: str, icon: str = "", default_open: bool = False) -> str:
    """生成可折叠组件"""
    return f"""
<div class="collapsible">
  <div class="collapsible-header" onclick="toggleCollapsible(this)">
    <div class="header-content">
      <span class="icon">{icon}</span>
      <span class="title">{_escape(title)}</span>
    </div>
    <span class="arrow">{'▲' if default_open else '▼'}</span>
  </div>
  <div class="collapsible-body" {'style="max-height:5000px;"' if default_open else 'style="max-height:0px;"'}>
    <div class="collapsible-content">
      {body}
    </div>
  </div>
</div>"""


def _timeline_item(date: str, title: str, result: str = "", badge: str = "") -> str:
    """生成时间线条目"""
    badge_html = f'<span class="badge badge-{badge.lower()}">{_escape(badge)}</span>' if badge else ""
    return f"""
<div class="timeline-item">
  <div class="timeline-marker"></div>
  <div class="timeline-content">
    <div class="timeline-date">{_escape(date)}</div>
    <div class="timeline-title">{_escape(title)}</div>
    {f'<div class="timeline-result">{_escape(result)}</div>' if result else ''}
    {badge_html}
  </div>
</div>"""


def _trend_chart(labels: List[str], values: List[float], reference_max: float = 37, unit: str = "U/mL") -> str:
    """生成趋势图（使用 Chart.js CDN）"""
    labels_json = str(labels).replace("'", '"')
    values_json = str(values).replace("'", '"')
    return f"""
<div class="chart-container">
  <canvas id="trendChart" data-labels='{labels_json}' data-values='{values_json}' data-reference='{reference_max}' data-unit='{unit}'></canvas>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
(function(){{
  const canvas = document.getElementById('trendChart');
  if (!canvas) return;
  const labels = JSON.parse(canvas.dataset.labels || '[]');
  const values = JSON.parse(canvas.dataset.values || '[]');
  const ref = parseFloat(canvas.dataset.reference || '37');
  const unit = canvas.dataset.unit || '';
  new Chart(canvas, {{
    type: 'line',
    data: {{
      labels: labels,
      datasets: [{{
        label: '指标值 (' + unit + ')',
        data: values,
        borderColor: '#2563eb',
        backgroundColor: 'rgba(37, 99, 235, 0.1)',
        fill: true,
        tension: 0.4,
        pointRadius: 4,
        pointHoverRadius: 6
      }}]
    }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{
          callbacks: {{
            label: function(context) {{
              return context.parsed.y + ' ' + unit;
            }}
          }}
        }}
      }},
      scales: {{
        y: {{
          beginAtZero: false
        }}
      }}
    }}
  }});
}})();
</script>"""


# ---------------------------------------------------------------------------
# 主渲染函数
# ---------------------------------------------------------------------------

def render_html_v2(
    manifest: Dict[str, Any],
    *,
    timeline: Optional[List[Dict[str, Any]]] = None,
    output_path: Optional[Path] = None,
    extra: Optional[Dict[str, Any]] = None,
    report_context: Optional[Dict[str, Any]] = None,
) -> Path:
    """渲染 V2 HTML 报告（卡片式布局 + 折叠详情）"""
    if output_path is None:
        output_path = _DEFAULT_OUTPUT / "case_report_v2.html"

    # 构建上下文
    if report_context is not None:
        ctx = dict(report_context)
        if extra:
            for k, v in extra.items():
                if k not in ctx:
                    ctx[k] = v
    else:
        from scripts.render_report import compute_report_context
        ctx = compute_report_context(manifest, timeline=timeline, extracted_texts=extra.get("extracted_texts") if extra else None)

    demo = ctx.get("demographics", {}) or {}
    files = ctx.get("files", []) or []

    # ── 构建各模块 HTML ──

    # 1. 患者基础信息
    basic_info_body = f"""
      <div class="info-grid">
        <div class="info-item"><span class="info-label">患者</span><span class="info-value">{_escape(demo.get('name', 'XXX'))}</span></div>
        <div class="info-item"><span class="info-label">性别</span><span class="info-value">{_escape(demo.get('gender', '男/女'))}</span></div>
        <div class="info-item"><span class="info-label">年龄</span><span class="info-value">{_escape(str(demo.get('age', 'XX')))}岁</span></div>
        <div class="info-item"><span class="info-label">主要诊断</span><span class="info-value">{_escape(demo.get('primary_diagnosis', 'XXXXXXXXXX'))}</span></div>
      </div>"""
    basic_info_card = _card("患者基础信息", basic_info_body, icon="👤", color="#2563eb", default_open=True)

    # 2. 就诊经历时间轴
    timeline_items = ""
    for item in ctx.get("timeline", []) or []:
        date = item.get("dates", [""])[0] if item.get("dates") else "日期待确认"
        title = item.get("title", "")
        timeline_items += _timeline_item(date, title, badge="诊疗")

    timeline_body = f'<div class="timeline">{"".join(timeline_items) if timeline_items else "<p>暂无时间线数据</p>"}</div>'
    timeline_card = _card("就诊经历时间轴", timeline_body, icon="📋", color="#059669", default_open=True)

    # 3. 手术病理结果
    pathology_items = ""
    for item in ctx.get("pathology", []) or []:
        summary = item.get("summary", "")
        if summary:
            pathology_items += f"<p>{_escape(summary)}</p>"
    pathology_body = pathology_items if pathology_items else "<p>暂无病理数据</p>"
    pathology_card = _card("手术病理结果", pathology_body, icon="🔬", color="#1e40af", default_open=True)

    # 4. 免疫组化 & PD-L1
    ihc_body = "<p>详见附件原始报告</p>"
    ihc_card = _collapsible("免疫组化 & PD-L1", ihc_body, icon="🧪", default_open=False)

    # 5. 基因检测结果
    genetics_body = ""
    for gh in ctx.get("genetic_highlights", []) or []:
        if isinstance(gh, dict):
            gene = _escape(gh.get("gene", ""))
            mutation = _escape(gh.get("mutation", ""))
            position = _escape(gh.get("position", ""))
            genetics_body += f'<div class="gene-item"><strong>{gene}</strong>'
            if position:
                genetics_body += f' 点位 {position}'
            if mutation:
                genetics_body += f' 突变 {mutation}'
            genetics_body += "</div>"
    genetics_card = _collapsible("基因检测结果", genetics_body or "<p>暂无基因数据</p>", icon="🧬", default_open=False)

    # 6. 检查指标趋势
    lab_trend = ctx.get("lab_trend", []) or []
    if lab_trend:
        # 提取肿瘤标志物数据
        labels = [row.get("date", "") for row in lab_trend]
        values = [float(row.get("cea", 0) or 0) for row in lab_trend]
        trend_body = _trend_chart(labels, values, reference_max=37, unit="U/mL")
        trend_body += _collapsible("完整数据记录", "<table class='data-table'><thead><tr><th>日期</th><th>CA199</th><th>变化</th><th>备注</th></tr></thead><tbody></tbody></table>", default_open=False)
    else:
        trend_body = "<p>暂无指标趋势数据</p>"
    trend_card = _card("检查指标趋势", trend_body, icon="📊", color="#059669", default_open=True)

    # 7. 用药方案
    medication = ctx.get("medication", {}) or {}
    med_body = ""
    current = medication.get("current", []) or []
    history = medication.get("history", []) or []
    if current:
        med_body += "<h4>当前用药</h4><ul>"
        for m in current:
            med_body += f"<li>{_escape(str(m))}</li>"
        med_body += "</ul>"
    if history:
        med_body += "<h4>历史用药</h4><ul>"
        for m in history:
            med_body += f"<li>{_escape(str(m))}</li>"
        med_body += "</ul>"
    medication_card = _collapsible("用药方案", med_body or "<p>暂无用药数据</p>", icon="💊", default_open=False)

    # 8. 影像检查
    imaging_body = ""
    for item in ctx.get("imaging_summary", []) or []:
        findings = item.get("findings", "")
        date = item.get("date", "日期待确认")
        imaging_body += f"<p><strong>{_escape(date)}</strong>：{_escape(findings)}</p>"
    imaging_card = _collapsible("影像检查", imaging_body or "<p>暂无影像数据</p>", icon="🏥", default_open=False)

    # 9. 关注问题要点
    concerns_body = ""
    for c in ctx.get("key_concerns", []) or []:
        concerns_body += f"<p>⚠️ {_escape(c)}</p>"
    concerns_card = _card("关注问题要点", concerns_body or "<p>暂无关注问题</p>", icon="⚠️", color="#dc2626", default_open=True)

    # 10. 问诊咨询建议
    questions_body = ""
    for q in ctx.get("consultation_questions", []) or []:
        questions_body += f"<p>❓ {_escape(q)}</p>"
    consultation_card = _collapsible("问诊咨询建议", questions_body or "<p>暂无咨询建议</p>", icon="💬", default_open=False)

    # 11. 附件目录
    attachments_body = ""
    for i, f in enumerate(files, 1):
        title = f.get("title") or f.get("original_name", "")
        date = f.get("date_detected") or "日期待确认"
        category = f.get("category") or "未分类"
        attachments_body += f"<p>{i}. {_escape(title)}（{_escape(date)}） - {_escape(category)}</p>"
    attachments_card = _collapsible("附件目录", attachments_body or "<p>暂无附件</p>", icon="📎", default_open=False)

    # 12. 免责声明
    disclaimer = """
<div class="disclaimer">
  <p><strong>⚠️ 免责声明</strong></p>
  <p>本病例档案仅为医疗资料整理，不构成任何诊断或治疗建议。如有疑问请联系主治医师。</p>
</div>"""

    # ── 组装页面 ──
    page_title = f"患病情档案 — {_escape(demo.get('name', '患者'))}"

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  {_meta_security_tags()}
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{page_title}</title>
  <style>
    /* 全局样式 */
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
      max-width: 900px;
      margin: 0 auto;
      padding: 16px;
      line-height: 1.6;
      color: #333;
      background: #f5f5f5;
    }}

    /* 页面标题 */
    .page-header {{
      text-align: center;
      padding: 24px 0;
      border-bottom: 2px solid #e5e7eb;
      margin-bottom: 24px;
    }}
    .page-title {{
      font-size: 24px;
      font-weight: 700;
      color: #1f2937;
    }}
    .page-subtitle {{
      font-size: 14px;
      color: #6b7280;
      margin-top: 4px;
    }}

    /* 卡片组件 */
    .card {{
      background: white;
      border-radius: 8px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
      margin-bottom: 16px;
      overflow: hidden;
    }}
    .card-header {{
      padding: 12px 16px;
      color: white;
      display: flex;
      align-items: center;
    }}
    .header-content {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .icon {{
      font-size: 18px;
    }}
    .title {{
      font-size: 16px;
      font-weight: 600;
    }}
    .card-body {{
      padding: 16px;
    }}

    /* 折叠组件 */
    .collapsible {{
      background: white;
      border-radius: 8px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
      margin-bottom: 16px;
      overflow: hidden;
    }}
    .collapsible-header {{
      padding: 12px 16px;
      background: #f9fafb;
      border-bottom: 1px solid #e5e7eb;
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      align-items: center;
      user-select: none;
      transition: background 0.2s;
    }}
    .collapsible-header:hover {{
      background: #f3f4f6;
    }}
    .collapsible-body {{
      max-height: 0;
      overflow: hidden;
      transition: max-height 0.3s ease, padding 0.3s ease;
    }}
    .collapsible.open .collapsible-body {{
      max-height: 5000px;
      padding: 16px;
    }}
    .collapsible.open .arrow {{
      transform: rotate(180deg);
    }}
    .arrow {{
      transition: transform 0.3s ease;
      font-size: 12px;
      color: #6b7280;
    }}

    /* 信息网格 */
    .info-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 12px;
    }}
    .info-item {{
      display: flex;
      flex-direction: column;
    }}
    .info-label {{
      font-size: 12px;
      color: #6b7280;
      margin-bottom: 2px;
    }}
    .info-value {{
      font-size: 14px;
      font-weight: 500;
      color: #111827;
    }}

    /* 时间轴 */
    .timeline {{
      position: relative;
      padding-left: 24px;
    }}
    .timeline::before {{
      content: '';
      position: absolute;
      left: 8px;
      top: 0;
      bottom: 0;
      width: 2px;
      background: #e5e7eb;
    }}
    .timeline-item {{
      position: relative;
      margin-bottom: 16px;
    }}
    .timeline-marker {{
      position: absolute;
      left: -20px;
      top: 4px;
      width: 12px;
      height: 12px;
      border-radius: 50%;
      background: #059669;
      border: 2px solid white;
      box-shadow: 0 0 0 2px #059669;
    }}
    .timeline-date {{
      font-size: 12px;
      color: #6b7280;
      margin-bottom: 2px;
    }}
    .timeline-title {{
      font-size: 14px;
      font-weight: 500;
      color: #111827;
      margin-bottom: 2px;
    }}
    .timeline-result {{
      font-size: 13px;
      color: #4b5563;
    }}

    /* 标签 */
    .badge {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 12px;
      font-weight: 500;
      margin-left: 8px;
    }}
    .badge-cr {{ background: #d1fae5; color: #065f46; }}
    .badge-pr {{ background: #dbeafe; color: #1e40af; }}
    .badge-sd {{ background: #fef3c7; color: #92400e; }}
    .badge-pd {{ background: #fee2e2; color: #991b1b; }}
    .badge-primary {{ background: #dbeafe; color: #1e40af; }}

    /* 表格 */
    .data-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    .data-table th {{
      background: #059669;
      color: white;
      padding: 8px 12px;
      text-align: left;
    }}
    .data-table td {{
      padding: 8px 12px;
      border-bottom: 1px solid #e5e7eb;
    }}
    .data-table tr:nth-child(even) {{
      background: #f8f9fa;
    }}
    .data-table .abnormal {{
      color: #dc2626;
      font-weight: 600;
    }}
    .data-table .normal {{
      color: #059669;
    }}

    /* 基因项 */
    .gene-item {{
      padding: 8px 0;
      border-bottom: 1px solid #f3f4f6;
    }}
    .gene-item:last-child {{
      border-bottom: none;
    }}

    /* 图表容器 */
    .chart-container {{
      position: relative;
      height: 300px;
      margin-bottom: 16px;
    }}

    /* 免责声明 */
    .disclaimer {{
      background: #fff3cd;
      border: 1px solid #ffc107;
      border-radius: 8px;
      padding: 16px;
      margin-top: 24px;
      font-size: 13px;
      color: #856404;
    }}

    /* 打印优化 */
    @media print {{
      .collapsible-body {{
        max-height: none !important;
        display: block !important;
      }}
      .arrow {{
        display: none;
      }}
      body {{
        background: white;
      }}
      .card, .collapsible {{
        box-shadow: none;
        border: 1px solid #e5e7eb;
        break-inside: avoid;
      }}
    }}

    /* 响应式 */
    @media (max-width: 768px) {{
      body {{
        padding: 12px;
      }}
      .page-title {{
        font-size: 20px;
      }}
      .info-grid {{
        grid-template-columns: 1fr;
      }}
      .chart-container {{
        height: 250px;
      }}
    }}
  </style>
</head>
<body>
  <div class="page-header">
    <div class="page-title">患病情档案</div>
    <div class="page-subtitle">患者：{_escape(demo.get('name', 'XXX'))} | 生成日期：{_escape(ctx.get('updated_at', 'YYYY-MM-DD')[:10])}</div>
  </div>

  {basic_info_card}
  {timeline_card}
  {trend_card}
  {pathology_card}
  {ihc_card}
  {genetics_card}
  {medication_card}
  {imaging_card}
  {concerns_card}
  {consultation_card}
  {attachments_card}

  {disclaimer}

  <script>
    function toggleCollapsible(header) {{
      const body = header.nextElementSibling;
      const arrow = header.querySelector('.arrow');
      const isOpen = body.style.maxHeight && body.style.maxHeight !== '0px';
      
      if (isOpen) {{
        body.style.maxHeight = '0px';
        arrow.textContent = '▼';
        header.parentElement.classList.remove('open');
      }} else {{
        body.style.maxHeight = body.scrollHeight + 'px';
        arrow.textContent = '▲';
        header.parentElement.classList.add('open');
      }}
    }}
  </script>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    logger.info("V2 HTML 报告已生成: %s", output_path)
    return output_path
