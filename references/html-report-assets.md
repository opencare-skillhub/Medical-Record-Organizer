# HTML 报告组件库（CSS + JS）

> 用途：供 `html-report-template.html` 和 `render_report.py` 内嵌使用  
> 说明：全部代码零外部依赖（图表除外），单文件即可运行

---

## 一、完整 CSS

> 对齐 `pancreatic_cancer_case_template.html`：卡片采用**全边框 + 浅底色**，每种颜色对应一类内容。

```css
* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
  background: #f5f7fb;
  color: #263238;
  font-size: 14px;
  line-height: 1.6;
  padding: 24px;
}

.page {
  max-width: 900px;
  margin: 0 auto;
  background: #fff;
  padding: 18px;
  border-radius: 14px;
  box-shadow: 0 4px 18px rgba(0,0,0,.08);
}

/* ── 标题区 ── */
h1 {
  text-align: center;
  font-size: 22px;
  color: #1c3852;
  margin-bottom: 6px;
}
.patient-line {
  text-align: center;
  color: #5b6b78;
  font-size: 13px;
  margin-bottom: 16px;
}
h2 {
  font-size: 17px;
  border-bottom: 1px solid rgba(0,0,0,.18);
  padding-bottom: 7px;
  margin-bottom: 10px;
  color: #1d5f86;
}

/* ── 卡片：全边框 + 浅底色（对齐参考模板）── */
.card {
  border: 1.5px solid #7fa4c4;
  border-radius: 9px;
  padding: 14px 18px;
  margin-bottom: 14px;
  background: #fff;
}
.card.blue       { border-color: #7fa4c4; background: #f6faff; }
.card.blue h2    { color: #1d5f86; }
.card.green      { border-color: #7cbb78; background: #fbfffb; }
.card.green h2   { color: #26943a; }
.card.lightgreen { border-color: #8fd29d; background: #f2fff4; }
.card.lightgreen h2 { color: #1f8a3a; }
.card.red        { border-color: #d58b8b; background: #fffafa; }
.card.red h2     { color: #b23030; }
.card.purple     { border-color: #8a78bc; background: #fcfbff; }
.card.purple h2  { color: #5b45a1; }
.card.orange     { border-color: #d8aa55; background: #fffdf7; }
.card.orange h2  { color: #b07812; }
.card.gray       { border-color: #b8c0c9; background: #fafbfc; }
.card.gray h2    { color: #555f6d; }

/* ── 颜色图例表 ── */
.legend {
  border: 1px dashed #c4ccd6;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 14px;
  background: #f9fbfd;
}
.legend h2 { color: #4a5560; border-bottom-color: #dfe4ea; }
.legend-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.legend-table th, .legend-table td {
  border: 1px solid #e0e5ec;
  padding: 6px 10px;
  text-align: left;
}
.legend-table th { background: #eef2f7; color: #4a5560; }
.swatch {
  display: inline-block;
  width: 16px; height: 16px;
  border-radius: 3px;
  vertical-align: middle;
  margin-right: 6px;
}
.sw-blue       { background: #7fa4c4; }
.sw-green      { background: #7cbb78; }
.sw-red        { background: #d58b8b; }
.sw-purple     { background: #8a78bc; }
.sw-orange     { background: #d8aa55; }
.sw-gray       { background: #b8c0c9; }

/* ── 危急值横幅 ── */
.alert-banner {
  background: linear-gradient(135deg, #c0392b, #e74c3c);
  border: none;
  color: #fff;
  box-shadow: 0 4px 12px rgba(192,57,43,0.4);
}
.alert-banner h2 { color: #fff; border-bottom-color: rgba(255,255,255,.3); }
.alert-row { padding: 2px 0; font-size: 14px; }

/* ── 基础信息行 ── */
.basic { display: flex; gap: 18px; flex-wrap: wrap; font-size: 15px; }
.basic b, .kv b { color: #111; }
.kv { padding: 3px 0; }
.muted { color: #6b7280; font-size: 12px; }
.empty { color: #9ca3af; font-style: italic; padding: 8px 0; }

/* ── 时间轴（绿点，红色事件用红点）── */
.timeline { list-style: none; padding: 0; }
.timeline li {
  position: relative;
  padding-left: 26px;
  margin: 8px 0;
  font-size: 14px;
}
.timeline li::before {
  content: "";
  position: absolute;
  left: 0; top: 4px;
  width: 11px; height: 11px;
  border: 2px solid #4ba64e;
  border-radius: 50%;
  background: #fff;
}
.date { color: #13933c; font-weight: 700; margin-right: 8px; }

/* ── grid 要点布局（3 列卡片块）── */
.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.box {
  border: 1px solid #d7dce2;
  border-radius: 6px;
  padding: 10px 12px;
  min-height: 56px;
  background: linear-gradient(#fff, #fafafa);
  font-size: 14px;
}
.label { color: #4a5560; font-weight: 700; display: block; margin-bottom: 4px; }
.value { font-weight: 700; color: #333; }
.value.redtxt { color: #c83333; }

/* ── tag 标签（黄底胶囊）── */
.tag {
  display: inline-block;
  padding: 3px 8px;
  margin-top: 3px;
  border-radius: 999px;
  background: #fff1b8;
  color: #9b6b00;
  font-size: 12px;
  font-weight: 700;
}

/* ── 数据表格（绿底，最新行蓝底高亮）── */
.table-wrap { overflow-x: auto; }
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
  background: #f2fff4;
}
.data-table th, .data-table td {
  border: 1px solid #c8ebcf;
  padding: 8px 10px;
  text-align: center;
}
.data-table th { background: #d9f8df; color: #179338; }
.data-table tr.latest td { background: #dcecff; font-weight: 700; color: #1c5ca8; }
.data-table .abnormal { color: #dc2626; font-weight: 700; }

/* ── 折叠详情（原生 details，概要之上保留全部原始文字）── */
.detail { margin: 8px 0 4px; }
.detail details { border-left: 3px solid #d7dce2; padding-left: 12px; }
.detail summary {
  color: #2563eb;
  cursor: pointer;
  font-size: 13px;
  padding: 4px 0;
  user-select: none;
}
.detail summary:hover { text-decoration: underline; }
.detail-body { padding: 8px 0 4px; }

/* ── 趋势图（纯 SVG，无 JS 依赖）── */
.chart-wrap { text-align: center; }
.chart-title { font-weight: 800; font-size: 16px; margin: 2px 0 8px; }
.chart {
  width: 520px; max-width: 100%;
  height: 260px;
  margin: 0 auto 10px;
  border-left: 1px solid #ddd;
  border-bottom: 1px solid #ddd;
  background-image:
    linear-gradient(#eef1f5 1px, transparent 1px),
    linear-gradient(90deg, #eef1f5 1px, transparent 1px);
  background-size: 100% 25%, 12.5% 100%;
}
svg { overflow: visible; }

/* ── 免责声明 ── */
.disclaimer {
  background: #fffbeb;
  border: 1px solid #fcd34d;
  border-radius: 8px;
  padding: 12px 16px;
  margin-top: 14px;
  font-size: 13px;
  color: #92400e;
  text-align: center;
}

/* ── 响应式 ── */
@media (max-width: 720px) {
  body { padding: 10px; }
  .grid { grid-template-columns: 1fr; }
  .basic { gap: 8px; flex-direction: column; }
}

/* ── 打印：展开所有折叠区 ── */
@media print {
  details > div { display: block !important; }
  details summary::after { content: ""; }
  body { background: #fff; padding: 0; }
  .page { box-shadow: none; }
  .card { page-break-inside: avoid; }
}
```

---

## 二、完整 JavaScript

> 折叠改用原生 `<details>` 元素，无需 JS 即可工作。以下脚本仅用于趋势图绘制（可选）和打印时自动展开。

```javascript
// 打印前自动展开所有 <details>
window.addEventListener('beforeprint', function () {
  document.querySelectorAll('details').forEach(function (d) { d.open = true; });
});

// 趋势图数据驱动（可选）：读取 data-chart 属性绘制 SVG 折线
document.querySelectorAll('[data-chart]').forEach(function (el) {
  // el.dataset.chart 形如 "830,907,286,113,111.3,48.5,30.868"
  var values = el.dataset.chart.split(',').map(Number);
  // …绘制逻辑（略），或直接由后端预生成 SVG
});
```

---

## 三、Jinja2 宏定义（供模板复用）

> 模板采用「卡片 + 原生 details 折叠」双宏结构。卡片本身不折叠，折叠只用于详情子区域。

```jinja2
{# 卡片宏：icon=图标, title=标题, cls=颜色类（blue/green/red/purple/orange/gray/lightgreen）#}
{% macro card(icon, title, cls) %}
<section class="card {{ cls }}">
  <h2>{{ icon }} {{ title }}</h2>
{% endmacro %}

{% macro endcard() %}</section>{% endmacro %}

{# 折叠详情宏：使用原生 <details>，概要之上保留全部原始文字 #}
{% macro detail(label='展开完整详情') %}
<div class="detail">
  <details><summary>{{ label }} ▾</summary><div class="detail-body">
{% endmacro %}

{% macro enddetail() %}</div></details></div>{% endmacro %}
```

---

## 四、使用示例

```python
# render_report.py 集成示例
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader('references'), autoescape=True)
template = env.get_template('html-report-template.html')

html = template.render(
    CSS=open('references/html-report-assets.md').read_css(),  # 或直接内嵌字符串
    JS=open('references/html-report-assets.md').read_js(),
    demographics=manifest['demographics'],
    timeline=timeline,
    lab_trend=lab_trend,
    pathology=pathology,
    genetic_highlights=genetic_highlights,
    medication=medication,
    imaging_summary=imaging_summary,
    key_concerns=key_concerns,
    consultation_questions=consultation_questions,
    files=file_entries,
    gaps=gaps,
    has_critical=has_critical,
    critical_alerts=critical_alerts,
    created_at=manifest.get('created_at'),
    updated_at=manifest.get('updated_at'),
)
```

---

## 五、设计原则速查

| 原则 | 实现方式 |
|------|---------|
| 概要优先 | 每个卡片顶部显示 3-5 条概要 |
| 详情保留 | 原始数据放进 `.collapse-body`，不丢弃 |
| 1 分钟掌握 | 默认展开：基础信息、时间线、指标趋势、病理、关注问题 |
| 按需深读 | 默认折叠：基因、用药、影像、咨询、附件 |
| 打印友好 | `@media print` 自动展开所有折叠区 |
| 移动友好 | `@media (max-width:768px)` 单列布局 |
