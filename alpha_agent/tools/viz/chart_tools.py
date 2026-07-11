"""图表工具 —— 让 Agent 能"画图"而不是"输出表格"。

支持图表类型：
- 饼图：涨跌分布、行业分布
- 柱状图：行业涨跌排名、资金流向排名
- 折线图：K线走势、资金趋势
- 热力图：行业轮动、因子相关性

输出：Base64 编码的 PNG 图片，可直接嵌入 Markdown 展示。
"""
from __future__ import annotations
import io
import base64
import traceback
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import pandas as pd
import numpy as np
from langchain_core.tools import tool

from alpha_agent.utils.logger import logger

# 设置中文字体
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _fig_to_base64(fig: plt.Figure) -> str:
    """将 matplotlib Figure 转为 base64 字符串"""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode("utf-8")
    plt.close(fig)
    return img_base64


@tool
def generate_chart(
    chart_type: str,
    data_json: str = "",
    title: str = "图表",
    x_label: str = "",
    y_label: str = "",
    top_n: int = 10,
) -> str:
    """将数据可视化为图表。支持多种图表类型。

    当用户想看"走势图"、"分布图"、"排名图"时调用此工具。

    Chart types:
    - pie: 饼图（适合涨跌分布、行业占比）
    - bar: 柱状图（适合排名、对比）
    - barh: 横向柱状图
    - line: 折线图（适合走势、趋势）
    - scatter: 散点图（适合相关性分析）

    data_json 格式（JSON 字符串）：
    - 饼图: [{"label": "上涨", "value": 1200}, {"label": "下跌", "value": 800}]
    - 柱状图: [{"label": "银行", "value": 3.5}, {"label": "医药", "value": -2.1}]
    - 折线图: [{"label": "2026-07-01", "value": 10.5}, {"label": "2026-07-02", "value": 10.8}]

    Args:
        chart_type: 图表类型（pie/bar/barh/line/scatter）
        data_json: JSON 格式的数据
        title: 图表标题
        x_label: X轴标签
        y_label: Y轴标签
        top_n: 柱状图最多显示前N条（默认10）
    """
    try:
        if not data_json:
            return "错误：请提供 data_json 参数"

        import json
        data = json.loads(data_json)

        if not isinstance(data, list) or len(data) == 0:
            return "错误：data_json 必须是非空数组"

        fig, ax = plt.subplots(figsize=(10, 6))

        labels = [d.get("label", str(i)) for i, d in enumerate(data)]
        values = [d.get("value", 0) for d in data]

        # 限制 top_n
        if chart_type in ("bar", "barh") and len(labels) > top_n:
            labels = labels[:top_n]
            values = values[:top_n]

        if chart_type == "pie":
            colors = plt.cm.RdYlGn(np.linspace(0.2, 0.8, len(labels)))
            wedges, texts, autotexts = ax.pie(
                values, labels=labels, autopct="%1.1f%%",
                colors=colors, startangle=90, pctdistance=0.85
            )
            for t in autotexts:
                t.set_fontsize(9)
            ax.set_title(title, fontsize=14, fontweight="bold")

        elif chart_type == "bar":
            colors = ["#e74c3c" if v < 0 else "#27ae60" for v in values]
            bars = ax.bar(labels, values, color=colors, edgecolor="white")
            for bar, val in zip(bars, values):
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + (0.5 if val >= 0 else -1.5),
                    f"{val:.2f}", ha="center", fontsize=9
                )
            ax.set_title(title, fontsize=14, fontweight="bold")
            ax.set_xlabel(x_label)
            ax.set_ylabel(y_label)
            ax.axhline(y=0, color="gray", linewidth=0.5)
            plt.xticks(rotation=45, ha="right")

        elif chart_type == "barh":
            colors = ["#e74c3c" if v < 0 else "#27ae60" for v in values]
            bars = ax.barh(labels, values, color=colors, edgecolor="white")
            for bar, val in zip(bars, values):
                ax.text(
                    bar.get_width() + (0.3 if val >= 0 else -1.5),
                    bar.get_y() + bar.get_height() / 2,
                    f"{val:.2f}", va="center", fontsize=9
                )
            ax.set_title(title, fontsize=14, fontweight="bold")
            ax.set_xlabel(x_label)
            ax.axvline(x=0, color="gray", linewidth=0.5)

        elif chart_type == "line":
            x = range(len(labels))
            ax.plot(x, values, marker="o", linewidth=2, markersize=6, color="#3498db")
            ax.fill_between(x, values, alpha=0.1, color="#3498db")
            ax.set_title(title, fontsize=14, fontweight="bold")
            ax.set_xlabel(x_label)
            ax.set_ylabel(y_label)
            ax.set_xticks(x[::max(1, len(x) // 10)])
            ax.set_xticklabels(labels[::max(1, len(labels) // 10)], rotation=45, ha="right")
            ax.grid(True, alpha=0.3)

        elif chart_type == "scatter":
            if len(data) > 0 and "x" in data[0] and "y" in data[0]:
                x_vals = [d.get("x", 0) for d in data]
                y_vals = [d.get("y", 0) for d in data]
                ax.scatter(x_vals, y_vals, alpha=0.6, c="#3498db", s=30)
                ax.set_title(title, fontsize=14, fontweight="bold")
                ax.set_xlabel(x_label)
                ax.set_ylabel(y_label)
                ax.grid(True, alpha=0.3)
            else:
                return "错误：散点图需要 data 中包含 x 和 y 字段"

        else:
            return f"不支持的图表类型: {chart_type}，支持的类型: pie, bar, barh, line, scatter"

        img_base64 = _fig_to_base64(fig)
        return f"图表已生成: {title}\n![{title}](data:image/png;base64,{img_base64})\n\n图表类型: {chart_type} | 数据点: {len(labels)}"

    except json.JSONDecodeError as e:
        return f"JSON 解析失败: {e}"
    except Exception as e:
        logger.error(f"[chart_tools] 图表生成失败: {traceback.format_exc()}")
        return f"图表生成失败: {str(e)}"


@tool
def generate_candlestick_chart(
    data_json: str = "",
    title: str = "K线走势图",
) -> str:
    """生成K线走势图（OHLC）。

    用于展示股票的价格走势，包含开盘价、收盘价、最高价、最低价。

    data_json 格式:
    [
        {"date": "2026-07-01", "open": 10.0, "close": 10.5, "high": 10.8, "low": 9.8, "vol": 1000000},
        {"date": "2026-07-02", "open": 10.5, "close": 10.2, "high": 10.7, "low": 10.1, "vol": 800000},
    ]

    Args:
        data_json: JSON 格式的 OHLC 数据
        title: 图表标题
    """
    try:
        import json
        data = json.loads(data_json)

        if not isinstance(data, list) or len(data) == 0:
            return "错误：data_json 必须是非空数组"

        dates = [d.get("date", str(i)) for i, d in enumerate(data)]
        opens = [d.get("open", 0) for d in data]
        closes = [d.get("close", 0) for d in data]
        highs = [d.get("high", 0) for d in data]
        lows = [d.get("low", 0) for d in data]

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(12, 8),
            gridspec_kw={"height_ratios": [3, 1]},
            sharex=True
        )

        x = range(len(dates))
        width = 0.6
        color_up = "#e74c3c"
        color_down = "#27ae60"

        for i in x:
            color = color_up if closes[i] >= opens[i] else color_down
            ax1.plot([i, i], [lows[i], highs[i]], color=color, linewidth=1)
            rect = plt.Rectangle(
                (i - width / 2, min(opens[i], closes[i])),
                width, abs(closes[i] - opens[i]),
                color=color, alpha=0.8
            )
            ax1.add_patch(rect)

        ax1.set_title(title, fontsize=14, fontweight="bold")
        ax1.set_ylabel("价格")
        ax1.grid(True, alpha=0.3)

        volumes = [d.get("vol", 0) for d in data]
        vol_colors = [
            color_up if closes[i] >= opens[i] else color_down
            for i in x
        ]
        ax2.bar(x, volumes, color=vol_colors, alpha=0.6, width=width)
        ax2.set_ylabel("成交量")
        ax2.grid(True, alpha=0.3)

        tick_step = max(1, len(dates) // 10)
        ax2.set_xticks(x[::tick_step])
        ax2.set_xticklabels(dates[::tick_step], rotation=45, ha="right")

        plt.tight_layout()
        img_base64 = _fig_to_base64(fig)
        return f"K线图已生成: {title}\n![{title}](data:image/png;base64,{img_base64})\n\n数据点: {len(dates)}"

    except json.JSONDecodeError as e:
        return f"JSON 解析失败: {e}"
    except Exception as e:
        logger.error(f"[chart_tools] K线图生成失败: {traceback.format_exc()}")
        return f"K线图生成失败: {str(e)}"


def get_chart_tools() -> list:
    return [generate_chart, generate_candlestick_chart]