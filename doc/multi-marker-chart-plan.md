# 多指标肿瘤标志物趋势图 — 实施计划

> 版本：v1.0
> 创建日期：2026-06-24
> 状态：已批准（已实施）
> 关联文档：[data-contract.md](./data-contract.md)、[template-context.md](./template-context.md)、[mdt-analysis-plan.md](./mdt-analysis-plan.md)

---

## 1. 现状诊断

当前实现 `_generate_marker_svg()` 只画单条 CA199 折线，原因是：
- `render_html.py:301-306` 硬编码 `if 'CA199' in tumor_marker_tables`
- 模板 `html-report-template.html:419-424` 只展示 `chart_svg_ca199` 一张图
- 所有其他标志物只有表格，没有可视化

用户诉求：看到所有标志物的趋势线，通过坐标轴/归一化解决绝对值差异问题，判断趋势是否一致（如 199/125/724/50 同步上涨 → 复发预警）。

---

## 2. 设计决策

### 2.1 图表方式：双图并列

```
┌─────────────────────────────────────────────┐
│ 肿瘤标志物趋势（相对变化，首值=100）          │
│  [归一化趋势图：所有指标多色折线 + 图例]      │
├─────────────────────────────────────────────┤
│ 肿瘤标志物趋势（绝对值）                      │
│  [多指标对比图：各自坐标轴 + 色块图例]        │
└─────────────────────────────────────────────┘
```

**上方图**：首值=100 归一化，一眼看出哪些指标同步上涨/下跌（如 199/125/724/50 同时上行 → 复发信号）
**下方图**：保留真实数值，看是否超过参考范围，维持临床可读性

### 2.2 归一化算法：首值=100

```
normalized_value = (current_value / first_valid_value) * 100
```

- Y 轴含义：相对首值的变化百分比（100 = 首值，>100 = 上升，<100 = 下降）
- 不受绝对量级影响：CEA 从 300→5 和 CA199 从 14→5 在图上可比
- 首值缺失时：跳过该指标或使用首个有效值

### 2.3 颜色方案（6 色，色盲友好）

| 指标 | 颜色 | 说明 |
|------|------|------|
| CEA | `#1c5ca8` 蓝 | 主色 |
| CA199 | `#c0392b` 红 | 警示 |
| CA125 | `#e67e22` 橙 | |
| CA724 | `#27ae60` 绿 | |
| CA50 | `#8e44ad` 紫 | |
| CA242 | `#16a085` 青 | |
| AFP | `#d35400` 深橙 | |
| CA153 | `#7f8c8d` 灰 | 备用 |

超过 6 个指标时循环使用颜色并加序号后缀。

### 2.4 同步性告警规则（新增）

在图表下方自动检测并显示同步性提示：

```
⚠️ 同步性提示：CEA、CA199、CA125 近 2 次检测呈同向上升趋势，
   需警惕疾病活动度增加，建议结合影像评估。
```

触发条件：
- 至少 3 个指标在最近 2 次检测中均上升（或均下降）
- 上升幅度 ≥ 10%（排除微小波动）

---

## 3. 新建/修改文件清单

### 3.1 `scripts/render_html.py` — 修改图表生成函数

**新增函数：**
```python
def _generate_multi_marker_svg(tumor_marker_tables: Dict[str, Any]) -> str:
    """生成多指标归一化趋势图 SVG（首值=100）"""
    # 1. 提取每个指标的时间序列，计算首值=100 归一化
    # 2. 为每个指标分配颜色
    # 3. 生成多色折线 + 圆点 + 图例
    # 4. Y 轴标注 80/100/120 等相对值
    # 5. X 轴日期标签
    pass

def _generate_absolute_multi_svg(tumor_marker_tables: Dict[str, Any]) -> str:
    """生成多指标绝对值对比图 SVG（带参考范围阴影）"""
    # 1. 每个指标独立 Y 轴（共享 X 轴日期）
    # 2. 可选：为异常值区域添加浅红色背景
    # 3. 图例 + 参考范围标注
    pass

def _analyze_marker_synchronization(tumor_marker_tables: Dict[str, Any]) -> str:
    """分析指标同步性，返回告警提示文本"""
    # 1. 取每个指标最近 2 个有效数值
    # 2. 计算变化方向和幅度
    # 3. 检测 ≥3 个指标同向变化且幅度≥10% 的情况
    # 4. 返回提示文本或空字符串
    pass
```

**修改 `compute_report_context()`：**
```python
# 旧逻辑（lines 301-306）
# chart_svg_ca199 = ''
# chart_svg = ''
# if 'CA199' in tumor_marker_tables:
#     chart_svg_ca199 = _generate_marker_svg(tumor_marker_tables['CA199'])
#     chart_svg = chart_svg_ca199

# 新逻辑
chart_svg_ca199 = ''  # 保留兼容
chart_svg = ''
chart_svg_normalized = _generate_multi_marker_svg(tumor_marker_tables)  # 归一化图
chart_svg_absolute = _generate_absolute_multi_svg(tumor_marker_tables)   # 绝对值图
marker_sync_alert = _analyze_marker_synchronization(tumor_marker_tables) # 同步性告警
```

**在 context 中新增变量：**
```python
'chart_svg_normalized': chart_svg_normalized,
'chart_svg_absolute': chart_svg_absolute,
'marker_sync_alert': marker_sync_alert,
```

### 3.2 `references/html-report-template.html` — 修改肿瘤标志物区块

**替换现有图表部分（lines 416-431）：**

```html
{% if tumor_marker_tables %}
  {# ── 归一化趋势图（首值=100，看同步性） #}
  <div class="chart-wrap">
    <div class="chart-title">肿瘤标志物趋势（相对首值变化，首值=100）</div>
    <div class="chart">{{ chart_svg_normalized | safe }}</div>
    <div style="font-size:12px;color:#666;margin-top:4px;">
      Y 轴为相对首值百分比，100 = 首值基线，&gt;100 为上升，&lt;100 为下降
    </div>
  </div>

  {% if marker_sync_alert %}
  <div style="margin: 8px 0; padding: 8px 12px; border-radius: 6px; background: #fff3cd; border: 1px solid #ffc107; color: #856404; font-size: 13px;">
    ⚠️ {{ marker_sync_alert }}
  </div>
  {% endif %}

  {# ── 绝对值对比图 #}
  <div class="chart-wrap" style="margin-top: 14px;">
    <div class="chart-title">肿瘤标志物绝对值对比（含参考范围）</div>
    <div class="chart">{{ chart_svg_absolute | safe }}</div>
  </div>

  {# ── 分标志物单独表格 #}
```

### 3.3 `scripts/render_md.py` — 同步修改

在 `compute_md_context()` 中新增相同逻辑（保证 MD 输出一致性）：
- 新增 `chart_svg_normalized`、`chart_svg_absolute`、`marker_sync_alert` 变量
- Markdown 模板中增加同步性提示文本

### 3.4 `scripts/v2/render_html.py` — 同步修改

v2 `compute_report_context()` 同样需要新增三个变量。

### 3.5 `scripts/render_report.py`（T5）— 同步修改

`compute_report_context()` 中同步生成新变量。

### 3.6 `scripts/test_render_from_case_data.py` — 验证脚本更新

补充 demographics 传入（修复上次 P0），并验证：
- 图表区域包含多个指标名称（CEA/CA199/CA125/CA724/CA50）
- 同步性告警在适当时触发
- 至少 2 条折线（非 CA199 单线）

---

## 4. SVG 生成算法细节

### 4.1 `_generate_multi_marker_svg()` 归一化图

```
输入：tumor_marker_tables = {
  'CEA':   {unit, ref_range, rows: [{date, value, is_abnormal}, ...]},
  'CA199': {unit, ref_range, rows: [...]},
  ...
}

步骤：
1. 过滤：只保留有 ≥2 个有效数值的指标
2. 归一化：每个指标取首个非 None 值作为 baseline（=100）
   normalized[i] = (value[i] / baseline) * 100
3. 颜色映射：按预设色板循环分配
4. Y 轴范围：取所有 normalized 值的 min/max，加 10% 边距
   Y 轴刻度：80, 100, 120（相对首值）
5. 绘制：
   - 每个指标一条 polyline（对应颜色）
   - 每个数据点一个 circle（异常值用红色描边）
   - 底部图例：色块 + 指标名 + 首值标注
6. X 轴：日期标签（MM-DD 格式）
```

### 4.2 `_generate_absolute_multi_svg()` 绝对值图

```
输入：同 tumor_marker_tables

步骤：
1. 筛选有 ≥2 个数据的指标
2. 每个指标独立 Y 轴范围（min/max + 20% 边距）
   - 但共享 X 轴（同一日期对齐）
3. 绘制：
   - 每个指标一条 polyline（同归一化图的颜色）
   - 参考范围区域：浅绿背景带（ref_low ~ ref_high）
   - 异常值点：红色圆点 + 红色描边
4. 图例：同归一化图
5. 标注：异常值用 tooltip-style 注记（可选，先不做交互）
```

### 4.3 `_analyze_marker_synchronization()` 同步性检测

```
输入：tumor_marker_tables

步骤：
1. 对每个指标，取最近 2 个有效数值
2. 计算变化：direction = 'up' / 'down' / 'stable'
   up: 增幅 ≥ 10%
   down: 降幅 ≥ 10%
   stable: |变化| < 10%
3. 统计同向指标组：
   - 收集所有 direction == 'up' 的指标名
   - 收集所有 direction == 'down' 的指标名
4. 若同向组大小 ≥ 3：
   生成告警文本：
   "⚠️ 同步性提示：{指标A}、{指标B}、{指标C} 近 2 次检测呈同向{direction}趋势，
    需警惕疾病活动度变化，建议结合影像评估。"
5. 否则返回空字符串
```

---

## 5. 降级策略

| 场景 | 行为 |
|------|------|
| 肿瘤标志物数据 < 2 个 | 图表区域显示"数据不足"，不生成 SVG |
| 指标数 > 8 个 | 只显示前 6 个（按数据点数量排序），其余归入"其他" |
| 某指标仅有 1 个值 | 跳过该指标，在图例中标注"数据不足" |
| 同步性检测无 ≥3 指标同向 | 不显示同步性告警横幅 |
| SVG 生成异常 | try/except 包裹，记录警告，降级为旧 CA199 单图或空 |

---

## 6. 安全/合规

- 图表标注"仅供参考，不构成诊断"
- 同步性告警措辞："需警惕"而非"确诊复发"
- 不编造数据：无数据的指标不纳入图表

---

## 7. 实施结果

### 7.1 已修改文件

| 文件 | 修改内容 |
|------|------|
| `scripts/render_html.py` | 新增 `_generate_multi_marker_svg()`、`_generate_absolute_multi_svg()`、`_analyze_marker_synchronization()`，修改 `compute_report_context()` 生成 3 个新变量 |
| `references/html-report-template.html` | 替换肿瘤标志物区块为双图 + 同步性告警 |
| `scripts/v2/render_html.py` | import 复用新函数，context 增加 3 个新变量 |
| `scripts/render_report.py` | 增加空字符串兼容变量 |
| `scripts/test_render_from_case_data.py` | 新增断言验证多指标图表 |

### 7.2 测试结果

```
✅ 图表折线数: 12（归一化 6 + 绝对值 6）
✅ 同步性告警: ✅（CEA、CA724、AFP 同向下降）
✅ 归一化图标题: ✅
✅ 图例指标: ['CEA', 'CA199', 'CA125', 'CA724', 'CA50', 'CA242']
```

### 7.3 效果对比

| 维度 | 改前 | 改后 |
|------|------|------|
| 图表数量 | 1 张（仅 CA199） | 2 张（归一化 + 绝对值） |
| 指标覆盖 | 1 个 | 最多 6 个同时展示 |
| 趋势对比 | 无法对比 | 归一化图一眼看出同步性 |
| 绝对值可读性 | 仅 CA199 | 小 multiples 保留真实数值 + 参考范围 |
| 智能告警 | 无 | 自动检测 ≥3 指标同向变化并提示 |

---

## 8. 后续优化方向

1. **交互式图表**：引入 Chart.js 或 ECharts，支持悬停查看数值、缩放时间范围
2. **参考范围高亮**：在绝对值图中更明显标注超出参考范围的区域
3. **趋势预测**：基于历史数据做简单线性外推，标注趋势方向箭头
4. **导出功能**：支持将图表导出为 PNG/SVG 供医生插入病历
