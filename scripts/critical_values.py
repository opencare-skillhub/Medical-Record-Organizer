"""
危急值识别与分级（1 期 MVP）

覆盖血钾、血红蛋白、血小板、白细胞、中性粒细胞等核心危急项。
分级参考 CTCAE v5.0 简化版 + 临床急诊阈值。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── 分级定义 ──────────────────────────────────────────────

LEVEL_1 = 1  # 正常 / 轻度异常
LEVEL_2 = 2  # 轻度异常
LEVEL_3 = 3  # 中度异常
LEVEL_4 = 4  # 重度异常
LEVEL_5 = 5  # 极危急

LEVEL_COLORS = {
    LEVEL_1: "#28a745",
    LEVEL_2: "#ffc107",
    LEVEL_3: "#fd7e14",
    LEVEL_4: "#dc3545",
    LEVEL_5: "#dc3545",
}
LEVEL_EMOJIS = {
    LEVEL_1: "🟢",
    LEVEL_2: "🟡",
    LEVEL_3: "🟠",
    LEVEL_4: "🔴",
    LEVEL_5: "🆘",
}
LEVEL_LABELS = {
    LEVEL_1: "正常",
    LEVEL_2: "轻度异常",
    LEVEL_3: "中度异常",
    LEVEL_4: "重度异常",
    LEVEL_5: "极危急",
}

# Ⅳ/Ⅴ 级视为需要立即提醒的危急值
_CRITICAL_THRESHOLD = LEVEL_4


# ── 数据模型 ──────────────────────────────────────────────

@dataclass
class CriticalAlert:
    item_name: str          # 指标名称（标准化）
    value: float            # 数值
    unit: str               # 单位
    level: int              # 1-5
    level_label: str        # 中文分级标签
    message: str            # 完整提示语
    color: str              # 颜色 hex
    emoji: str              # emoji
    action: str             # 建议动作
    category: str = ""      # 所属类别（电解质/血常规等）


# ── 阈值规则 ──────────────────────────────────────────────

_RULES = [
    # 血钾（mmol/L）
    {
        "name": "血钾",
        "aliases": ["血钾", "血清钾", "K+", "钾离子", "K"],
        "unit": "mmol/L",
        "category": "电解质",
        "levels": [
            (7.0, float("inf"), LEVEL_5, "🆘", "血钾极高，立即拨打 120"),
            (6.0, 7.0, LEVEL_4, "🔴", "血钾严重升高，立即就医"),
            (5.5, 6.0, LEVEL_3, "🟠", "血钾升高，尽快就诊"),
            (3.5, 5.5, LEVEL_1, "🟢", "血钾正常"),
            (3.0, 3.5, LEVEL_2, "🟡", "血钾轻度降低，关注"),
            (2.5, 3.0, LEVEL_3, "🟠", "血钾降低，建议就诊"),
            (0.0, 2.5, LEVEL_4, "🔴", "血钾严重降低，立即就医"),
        ],
    },
    # 血红蛋白（g/L）
    {
        "name": "血红蛋白",
        "aliases": ["血红蛋白", "HGB", "Hb", "血红蛋白浓度", "血红蛋白(g/L)"],
        "unit": "g/L",
        "category": "血常规",
        "levels": [
            (float("inf"), float("inf"), LEVEL_5, "🆘", "血红蛋白极低，立即输血/急诊"),
            (0, 60, LEVEL_5, "🆘", "血红蛋白极低，立即输血/急诊"),
            (60, 90, LEVEL_4, "🔴", "血红蛋白重度降低，需紧急处理"),
            (90, 120, LEVEL_3, "🟠", "血红蛋白中度降低，建议尽快就诊"),
            (120, 160, LEVEL_1, "🟢", "血红蛋白正常"),
            (0, 120, LEVEL_2, "🟡", "血红蛋白轻度降低，关注"),
        ],
    },
    # 血小板（×10^9/L）
    {
        "name": "血小板",
        "aliases": ["血小板", "PLT", "血小板计数", "血小板(×10^9/L)"],
        "unit": "×10^9/L",
        "category": "血常规",
        "levels": [
            (0, 10, LEVEL_5, "🆘", "血小板极低，立即止血/急诊"),
            (10, 50, LEVEL_4, "🔴", "血小板重度降低，需紧急处理"),  # 22 应为 Ⅳ级
            (50, 100, LEVEL_3, "🟠", "血小板中度降低，避免磕碰"),
            (100, 300, LEVEL_1, "🟢", "血小板正常"),
            (300, float("inf"), LEVEL_2, "🟡", "血小板升高，关注"),
        ],
    },
    # 白细胞（×10^9/L）
    {
        "name": "白细胞",
        "aliases": ["白细胞", "WBC", "白细胞计数", "白细胞(WBC)", "WBC(×10^9/L)"],
        "unit": "×10^9/L",
        "category": "血常规",
        "levels": [
            (0, 0.5, LEVEL_5, "🆘", "白细胞极低，立即抗感染/急诊"),
            (0.5, 1.0, LEVEL_5, "🆘", "白细胞极低，立即抗感染/急诊"),  # 0.8 应为 Ⅴ级
            (1.0, 2.0, LEVEL_3, "🟠", "白细胞中度降低，预防感染"),
            (2.0, 4.0, LEVEL_2, "🟡", "白细胞轻度降低，关注"),
            (4.0, 10.0, LEVEL_1, "🟢", "白细胞正常"),
            (10.0, float("inf"), LEVEL_2, "🟡", "白细胞升高，关注"),
        ],
    },
    # 中性粒细胞（×10^9/L）
    {
        "name": "中性粒细胞",
        "aliases": ["中性粒细胞", "ANC", "中性粒细胞计数", "中性粒", "NEU"],
        "unit": "×10^9/L",
        "category": "血常规",
        "levels": [
            (0, 0.5, LEVEL_5, "🆘", "中性粒细胞极低，立即抗感染/急诊"),
            (0.5, 1.0, LEVEL_4, "🔴", "中性粒细胞重度降低，需紧急处理"),
            (1.0, 1.5, LEVEL_3, "🟠", "中性粒细胞中度降低，预防感染"),
            (1.5, 2.0, LEVEL_2, "🟡", "中性粒细胞轻度降低，关注"),
            (2.0, 7.0, LEVEL_1, "🟢", "中性粒细胞正常"),
            (7.0, float("inf"), LEVEL_2, "🟡", "中性粒细胞升高，关注"),
        ],
    },
]


# ── 核心逻辑 ──────────────────────────────────────────────

def _parse_value_and_unit(text: str) -> List[tuple]:
    """从文本中提取 (数值, 单位, 原始匹配串)"""
    results = []
    # 匹配模式：指标名 + 数值 + 可选单位
    pattern = re.compile(
        r"(?P<name>[A-Za-z\u4e00-\u9fa5()（）/]+?)"
        r"[：:＝=]?\s*"
        r"(?P<value>[0-9]+(?:\.[0-9]+)?)"
        r"\s*(?P<unit>[^\s\n]*)"
    )
    for m in pattern.finditer(text):
        name = m.group("name").strip()
        try:
            value = float(m.group("value"))
        except ValueError:
            continue
        unit = m.group("unit").strip()
        results.append((name, value, unit, m.group(0)))
    return results


def _match_rule(name: str, rule: dict) -> bool:
    """判断指标名是否命中某条规则"""
    return any(alias in name for alias in rule["aliases"])


def _level_for(rule: dict, value: float) -> tuple:
    """根据数值返回 (level, emoji, action)"""
    for low, high, level, emoji, action in rule["levels"]:
        if low <= value < high:
            return level, emoji, action
    # 兜底
    return LEVEL_3, "🟠", "建议咨询医生"


def check_critical_values(text: str) -> List[CriticalAlert]:
    """扫描文本，返回 CriticalAlert 列表（按 level 降序）"""
    alerts: List[CriticalAlert] = []
    seen = set()

    for name, value, unit, raw in _parse_value_and_unit(text):
        for rule in _RULES:
            if not _match_rule(name, rule):
                continue
            level, emoji, action = _level_for(rule, value)
            if level < _CRITICAL_THRESHOLD:
                continue
            key = (rule["name"], round(value, 2))
            if key in seen:
                continue
            seen.add(key)
            alerts.append(CriticalAlert(
                item_name=rule["name"],
                value=value,
                unit=unit or rule["unit"],
                level=level,
                level_label=LEVEL_LABELS[level],
                message=f"{rule['name']} {value}{unit or rule['unit']} {LEVEL_EMOJIS[level]} {LEVEL_LABELS[level]}，{action}",
                color=LEVEL_COLORS[level],
                emoji=emoji,
                action=action,
                category=rule["category"],
            ))

    # 按 level 降序
    alerts.sort(key=lambda a: a.level, reverse=True)
    return alerts


def has_critical_alerts(alerts) -> bool:
    """是否存在 Ⅳ/Ⅴ 级告警（支持 list[CriticalAlert] 或 list[dict]）"""
    for a in alerts:
        level = a.level if hasattr(a, "level") else a.get("level")
        if level is not None and level >= _CRITICAL_THRESHOLD:
            return True
    return False


def format_alerts_md(alerts) -> str:
    """Markdown 格式（支持 list[CriticalAlert] 或 list[dict]）"""
    if not alerts:
        return ""
    lines = ["# 🚨 危急值提醒\n"]
    for a in alerts:
        if hasattr(a, "item_name"):
            item_name, value, unit, emoji, level_label, action = (
                a.item_name, a.value, a.unit, a.emoji, a.level_label, a.action
            )
        else:
            item_name = a.get("item_name", "")
            value = a.get("value", "")
            unit = a.get("unit", "")
            emoji = a.get("emoji", "🆘")
            level_label = a.get("level_label", "")
            action = a.get("action", "")
        lines.append(f"- {emoji} **{item_name}** {value}{unit} — {level_label}：{action}")
    return "\n".join(lines)


def format_alerts_html(alerts) -> str:
    """HTML 格式（内联样式，可直接嵌入报告）"""
    if not alerts:
        return ""
    items = []
    for a in alerts:
        if hasattr(a, "item_name"):
            item_name, value, unit, level, message, action = (
                a.item_name, a.value, a.unit, a.level, a.message, a.action
            )
            color = a.color
            emoji = a.emoji
        else:
            item_name = a.get("item_name", "")
            value = a.get("value", "")
            unit = a.get("unit", "")
            level = a.get("level", 0)
            message = a.get("message", "")
            action = a.get("action", "")
            color = a.get("color", "#dc3545")
            emoji = a.get("emoji", "🆘")
        # 对动态字段做 HTML 转义，防止 XSS
        item_name_safe = _html_escape(str(item_name))
        value_safe = _html_escape(str(value))
        unit_safe = _html_escape(str(unit))
        message_safe = _html_escape(str(message))
        action_safe = _html_escape(str(action))
        items.append(
            f'<div class="critical-banner alert-level-{level}" role="alert" style="background:{color};color:#fff;padding:0.75em;margin:0.5em 0;border-radius:4px;">'
            f"{emoji} <strong>{item_name_safe}</strong> {value_safe}{unit_safe} — {message_safe}：{action_safe}"
            f"</div>"
        )
    return "\n".join(items)


def _html_escape(text: str) -> str:
    """HTML 转义，防止 XSS"""
    import html as _html
    return _html.escape(str(text), quote=True)
