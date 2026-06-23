# HTML 报告生成提示词

> 用途：指导 Agent 生成符合设计规范的 HTML 报告
> 来源：对齐用户提供的两份报告截图格式

---

## 一、整体布局要求

1. **单文件输出**：所有 HTML/CSS/JS 内嵌在一个 `.html` 文件中
2. **移动端优先**：响应式布局，手机/平板/桌面都能正常显示
3. **打印友好**：折叠区域在打印时自动展开
4. **性能要求**：单文件 < 500KB，首屏渲染 < 1s

---

## 二、视觉设计规范

### 2.1 颜色方案

| 模块 | 标题颜色 | HEX |
|------|---------|-----|
| 患者基础信息 | 蓝色 | #2563eb |
| 手术病理结果 | 深蓝 | #1e40af |
| 免疫组化 & PD-L1 | 绿色 | #059669 |
| 基因检测结果 | 橙色 | #d97706 |
| 关注问题要点 | 红色 | #dc2626 |
| 用药方案 | 紫色 | #7c3aed |
| 影像检查 | 青色 | #0891b2 |

### 2.2 字体规范

- 字体栈：`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif`
- 页面标题：24px，字重 700
- 卡片标题：18px，字重 600
- 正文：14px，行高 1.6
- 辅助文字：12px

### 2.3 间距规范

- 卡片间距：16px
- 模块间距：24px
- 内边距：16px
- 圆角：8px

---

## 三、组件设计要求

### 3.1 卡片组件

```html
<div class="card">
  <div class="card-header" style="background-color: #2563eb;">
    <span class="icon">👤</span>
    <span class="title">患者基础信息</span>
  </div>
  <div class="card-body">
    <!-- 概要内容 -->
  </div>
</div>
```

**要求**：
- 白色背景，圆角 8px
- 顶部彩色标题栏，4px 高度
- 阴影：`0 2px 8px rgba(0,0,0,0.08)`

### 3.2 时间轴组件

```html
<div class="timeline">
  <div class="timeline-item">
    <div class="timeline-marker"></div>
    <div class="timeline-content">
      <div class="timeline-date">2026-01-20</div>
      <div class="timeline-title">皮肤发现黄斑</div>
      <div class="timeline-result">检查显示胰头占位</div>
      <span class="badge badge-primary">确诊</span>
    </div>
  </div>
</div>
```

**要求**：
- 垂直时间线，左侧绿色圆点（`#059669`）
- 疗效评估用颜色标签：CR(绿)/PR(蓝)/SD(黄)/PD(红)

### 3.3 折叠组件

```html
<div class="collapsible">
  <div class="collapsible-header" onclick="toggleCollapsible(this)">
    <div class="header-content">
      <span class="icon">💊</span>
      <span class="title">用药方案</span>
    </div>
    <span class="arrow">▼</span>
  </div>
  <div class="collapsible-body">
    <!-- 详细内容 -->
  </div>
</div>
```

**要求**：
- 默认折叠的模块：用药方案、影像检查、附件目录、问诊咨询建议
- 默认展开的模块：患者基础信息、时间线、病理结果、指标趋势、关注问题要点
- 动画：`max-height 0.3s ease`

### 3.4 表格组件

```html
<table class="data-table">
  <thead>
    <tr style="background-color: #059669;">
      <th>指标</th>
      <th>结果</th>
      <th>参考范围</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>CA199</td>
      <td class="abnormal">30.868</td>
      <td>0-37 U/mL</td>
    </tr>
  </tbody>
</table>
```

**要求**：
- 表头：彩色背景 + 白色文字
- 斑马纹：偶数行浅灰背景（`#f8f9fa`）
- 异常值：红色加粗
- 响应式：小屏幕横向滚动

### 3.5 趋势图表

**实现方式**：
- 优先使用 Chart.js CDN
- 备选：纯 SVG 折线图

**样式要求**：
- 折线图，平滑曲线
- 数据点：圆形标记，半径 4px
- 参考线：虚线表示正常范围
- 悬停提示：显示日期和数值

---

## 四、折叠规则

### 4.1 默认展开（Critical）

| 模块 | 原因 |
|------|------|
| 患者基础信息 | 核心信息，必须可见 |
| 就诊经历时间轴 | 病情走势核心 |
| 手术病理结果 | 关键诊断依据 |
| 检查指标趋势 | 直观展示病情变化 |
| 关注问题要点 | 警示信息 |

### 4.2 默认折叠（Secondary）

| 模块 | 原因 |
|------|------|
| 用药方案 | 详细数据，医生可按需查看 |
| 影像检查 | 详细描述，可折叠 |
| 基因检测结果 | 专业数据，可折叠 |
| 问诊咨询建议 | 辅助信息 |
| 附件目录 | 原始数据，非必需 |
| 信息缺口提示 | 提示信息 |

### 4.3 折叠交互

```javascript
function toggleCollapsible(header) {
  const body = header.nextElementSibling;
  const arrow = header.querySelector('.arrow');
  const isOpen = body.style.maxHeight && body.style.maxHeight !== '0px';
  
  if (isOpen) {
    body.style.maxHeight = '0px';
    arrow.textContent = '▼';
    header.classList.remove('open');
  } else {
    body.style.maxHeight = body.scrollHeight + 'px';
    arrow.textContent = '▲';
    header.classList.add('open');
  }
}
```

---

## 五、疗效评估标签

| 评估 | 背景色 | 文字色 | 含义 |
|------|--------|--------|------|
| CR | #d1fae5 | #065f46 | 完全缓解 |
| PR | #dbeafe | #1e40af | 部分缓解 |
| SD | #fef3c7 | #92400e | 疾病稳定 |
| PD | #fee2e2 | #991b1b | 疾病进展 |

```html
<span class="badge badge-cr">CR</span>
<span class="badge badge-pr">PR</span>
<span class="badge badge-sd">SD</span>
<span class="badge badge-pd">PD</span>
```

---

## 六、趋势图实现

### 6.1 数据结构

```javascript
const trendData = {
  labels: ['01-22', '01-28', '02-16', '03-13', '03-25', '05-07', '05-28'],
  values: [830.0, 907.0, 286.0, 113.0, 111.3, 48.5, 30.868],
  reference: { min: 0, max: 37 },
  unit: 'U/mL'
};
```

### 6.2 Chart.js 配置

```javascript
new Chart(ctx, {
  type: 'line',
  data: {
    labels: trendData.labels,
    datasets: [{
      label: 'CA199',
      data: trendData.values,
      borderColor: '#2563eb',
      backgroundColor: 'rgba(37, 99, 235, 0.1)',
      fill: true,
      tension: 0.4,
      pointRadius: 4,
      pointHoverRadius: 6
    }]
  },
  options: {
    responsive: true,
    plugins: {
      annotation: {
        annotations: {
          upper: {
            type: 'line',
            yMin: trendData.reference.max,
            yMax: trendData.reference.max,
            borderColor: '#dc2626',
            borderDash: [5, 5]
          }
        }
      }
    }
  }
});
```

---

## 七、生成提示词（给 Agent 的指令）

```
你是一个医疗报告 HTML 生成专家。请根据提供的病例数据，生成一个专业的 HTML 报告。

## 核心要求

1. **概要优先**：医生打开报告 10 秒内看到关键信息
2. **详情可折叠**：点击展开查看完整数据，不干扰主视图
3. **视觉分区**：不同模块用不同颜色区分
4. **响应式**：手机/平板/桌面都能正常显示
5. **打印友好**：折叠区域在打印时自动展开

## 模块顺序

1. 患者基础信息（蓝色卡片，默认展开）
2. 就诊经历时间轴（绿色时间线，默认展开）
3. 手术病理结果（深蓝卡片，默认展开，详情折叠）
4. 免疫组化 & PD-L1（绿色卡片，默认展开）
5. 基因检测结果（橙色卡片，默认折叠）
6. 检查指标趋势（图表 + 折叠表格）
7. 用药方案（紫色卡片，默认折叠）
8. 影像检查（青色卡片，默认折叠）
9. 关注问题要点（红色卡片，默认展开）
10. 问诊咨询建议（黄色卡片，默认折叠）
11. 附件目录（默认折叠）
12. 免责声明（固定底部）

## 技术实现

- 单 HTML 文件，内嵌 CSS 和 JavaScript
- 使用 CSS Grid + Flexbox 布局
- 折叠组件用原生 JavaScript 实现
- 趋势图使用 Chart.js（CDN 引入）
- 响应式断点：768px、1024px

## 数据填充

- 患者信息从 demographics 获取
- 时间线从 timeline 获取
- 指标趋势从 lab_trend 获取
- 病理从 pathology 获取
- 基因从 genetic_highlights 获取
- 用药从 medication 获取
- 影像从 imaging_summary 获取
- 关注问题从 key_concerns 获取
- 咨询问题从 consultation_questions 获取

## 样式规范

详见 references/html-report-design.md
```

---

## 八、当前实现 vs 新设计对比

| 特性 | 当前实现 | 新设计 |
|------|---------|--------|
| 布局 | 单页长列表 | 卡片式分区 |
| 折叠 | 无 | 详情可折叠 |
| 时间轴 | 文本列表 | 可视化时间线 |
| 图表 | 无 | Chart.js 趋势图 |
| 颜色 | 单色 | 模块化彩色 |
| 响应式 | 基础 | 完整响应式 |
| 打印 | 未优化 | 折叠自动展开 |

---

## 九、模板格式总结（速查）

### 9.1 模板整体结构

```
HTML 报告 = Header + 危急值横幅 + N 个卡片 + 免责声明
卡片 = 概要（默认可见）+ 详情（可折叠）
```

### 9.2 13 个模块的标准顺序

| 序号 | 模块 | 图标 | 主题色 | 默认状态 |
|------|------|------|--------|---------|
| 0 | 危急值警报 | 🆘 | 红 #dc2626 | 固定展开 |
| 1 | 患者基础信息 | 👤 | 蓝 #2563eb | 展开 |
| 2 | 诊疗时间线 | 📋 | 绿 #059669 | 展开 |
| 3 | 检查指标趋势 | 📊 | 青 #0891b2 | 展开（数据表折叠） |
| 4 | 病理报告 | 🔬 | 深蓝 #1e40af | 展开 |
| 5 | 基因检测 | 🧬 | 橙 #d97706 | 折叠 |
| 6 | 用药方案 | 💊 | 紫 #7c3aed | 折叠 |
| 7 | 影像检查 | 🏥 | 青 #0891b2 | 折叠 |
| 8 | 关注问题要点 | ⚠️ | 红 #dc2626 | 展开 |
| 9 | 问诊咨询建议 | 💬 | 黄 #f59e0b | 折叠 |
| 10 | 附件目录 | 📎 | 灰 #6b7280 | 折叠 |
| 11 | 信息缺口 | ⚠️ | 灰 | 折叠 |
| 12 | 免责声明 | — | 黄底 | 固定底部 |

### 9.3 三个核心组件

1. **Card（卡片）**：模块容器，彩色顶栏 + 标题 + 箭头，点击展开/收起
2. **Collapse（折叠详情）**：卡片内部的子折叠区，保留原始数据不丢失
3. **Timeline（时间轴）**：垂直时间线，绿点标记，日期+事件+结果

---

## 十、最终 Agent 提示词（精简版）

```
你是医疗报告 HTML 生成专家。根据病例数据生成单文件 HTML 报告。

【设计原则】
1. 概要优先：每模块顶部 3-5 条关键信息，医生 1 分钟掌握
2. 详情保留：完整原始数据放入折叠区，不丢弃任何信息
3. 三段结构：每个模块 = 概要(summary) + 折叠详情(collapse-body)
4. 打印友好：@media print 自动展开所有折叠区

【折叠规则】
- 默认展开：基础信息、时间线、指标趋势、病理、关注问题
- 默认折叠：基因、用药、影像、咨询、附件

【实现要求】
- 单 HTML 文件，CSS/JS 全部内嵌
- 使用 references/html-report-template.html 模板
- 样式和脚本来自 references/html-report-assets.md
- 响应式：移动端单列，桌面端最大 900px
- 趋势图：Chart.js CDN（可选）

【数据源映射】
demographics → 基础信息
timeline → 时间线
lab_trend → 指标趋势（图表+折叠表格）
pathology → 病理
genetic_highlights → 基因芯片+折叠详情
medication → 用药
imaging_summary → 影像
key_concerns → 关注问题
consultation_questions → 咨询建议
files → 附件目录
gaps → 信息缺口
critical_alerts → 危急值横幅
```

---

## 十一、实施计划

### Phase 1：基础组件
- [ ] 实现卡片组件（Card）
- [ ] 实现折叠组件（Collapsible）
- [ ] 实现表格组件（Table）
- [ ] 基础 CSS 样式

### Phase 2：核心模块
- [ ] 患者基础信息卡片
- [ ] 时间轴组件
- [ ] 病理结果卡片
- [ ] 基因检测卡片

### Phase 3：增强功能
- [ ] Chart.js 趋势图
- [ ] 响应式布局
- [ ] 打印样式
- [ ] 动画效果

### Phase 4：集成测试
- [ ] 与 pipeline 集成
- [ ] 真实数据测试
- [ ] 移动端测试
- [ ] 性能优化
