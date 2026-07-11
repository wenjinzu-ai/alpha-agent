"""自动洞察工具 —— 让 Agent 能"主动发现"而不是"被动回答"。

洞察类型：
1. 异常检测：涨跌幅异常、成交量异常放大、资金异动
2. 趋势发现：连续上涨/下跌、行业轮动信号
3. 数据质量：数据缺失、更新时间异常
4. 机会发现：突破信号、反转信号

核心思路：每次 execute_code 查询数据后，Agent 可以调用此工具做"二次分析"。
"""
from __future__ import annotations
import json
import traceback
from typing import Optional

import pandas as pd
import numpy as np
from langchain_core.tools import tool
from sqlalchemy import text

from alpha_agent.infra.db.database import SessionLocal
from alpha_agent.utils.logger import logger


@tool
def detect_anomalies(
    analysis_type: str = "market",
    top_n: int = 10,
) -> str:
    """自动检测数据中的异常和有趣模式。

    你不需要知道具体查什么，调用此工具会自动扫描数据库，发现：
    - 异常涨跌幅（超过2个标准差）
    - 成交量异常放大（超过均值3倍）
    - 连续涨跌信号
    - 数据最新状态

    analysis_type 可选值：
    - market: 全市场异常扫描（涨跌幅异常、成交量异常）
    - industry: 行业轮动检测
    - quality: 数据质量检查（缺失数据、过期数据）
    - all: 全部扫描

    Args:
        analysis_type: 分析类型（market/industry/quality/all）
        top_n: 返回前N条异常（默认10）
    """
    try:
        insights = []

        with SessionLocal() as db:
            # 获取最新交易日
            result = db.execute(text("SELECT MAX(trade_date) FROM daily_kline"))
            latest_date = result.fetchone()[0]
            if not latest_date:
                return "无法获取最新交易日，数据可能为空"

            if analysis_type in ("market", "all"):
                # 1. 涨跌幅异常检测
                result = db.execute(text(f"""
                    SELECT d.ts_code, s.name, d.pct_chg, d.amount, d.vol
                    FROM daily_kline d
                    JOIN stocks s ON d.ts_code = s.ts_code
                    WHERE d.trade_date = '{latest_date}'
                """))
                rows = result.fetchall()
                if rows:
                    df = pd.DataFrame(rows, columns=["ts_code", "name", "pct_chg", "amount", "vol"])
                    # 转换 Decimal 类型为 float
                    for col in ["pct_chg", "amount", "vol"]:
                        df[col] = df[col].astype(float)
                    pct_mean = df["pct_chg"].mean()
                    pct_std = df["pct_chg"].std()

                    # 超过2个标准差的异常
                    df["z_score"] = (df["pct_chg"] - pct_mean) / pct_std
                    anomalies = df[abs(df["z_score"]) > 2].sort_values("z_score", ascending=False)

                    if len(anomalies) > 0:
                        insights.append(f"## 涨跌幅异常检测（最新交易日: {latest_date}）\n")
                        insights.append(f"全市场均值: {pct_mean:.2f}%, 标准差: {pct_std:.2f}%\n")
                        top_anomalies = anomalies.head(top_n)
                        for _, row in top_anomalies.iterrows():
                            direction = "异常大涨" if row["pct_chg"] > 0 else "异常大跌"
                            insights.append(
                                f"- 🔴 **{row['name']}** ({row['ts_code']}): "
                                f"{row['pct_chg']:.2f}% ({direction}, Z={row['z_score']:.1f})"
                            )
                        insights.append("")

                    # 2. 成交量异常放大
                    result = db.execute(text(f"""
                        SELECT d.ts_code, s.name, d.vol, d.amount, d.pct_chg
                        FROM daily_kline d
                        JOIN stocks s ON d.ts_code = s.ts_code
                        WHERE d.trade_date = '{latest_date}'
                    """))
                    rows = result.fetchall()
                    df = pd.DataFrame(rows, columns=["ts_code", "name", "vol", "amount", "pct_chg"])
                    for col in ["vol", "amount", "pct_chg"]:
                        df[col] = df[col].astype(float)
                    vol_mean = df["vol"].mean()
                    vol_std = df["vol"].std()

                    vol_anomalies = df[df["vol"] > vol_mean + 2 * vol_std].sort_values("vol", ascending=False)
                    if len(vol_anomalies) > 0:
                        insights.append("## 成交量异常放大\n")
                        for _, row in vol_anomalies.head(top_n).iterrows():
                            ratio = row["vol"] / vol_mean if vol_mean > 0 else 0
                            insights.append(
                                f"- 📊 **{row['name']}** ({row['ts_code']}): "
                                f"成交量 {row['vol']:.0f}（正常{ratio:.1f}倍）, 涨跌 {row['pct_chg']:.2f}%"
                            )
                        insights.append("")

                # 3. 涨跌停附近
                result = db.execute(text(f"""
                    SELECT d.ts_code, s.name, d.pct_chg
                    FROM daily_kline d
                    JOIN stocks s ON d.ts_code = s.ts_code
                    WHERE d.trade_date = '{latest_date}'
                      AND (d.pct_chg >= 9.5 OR d.pct_chg <= -9.5)
                    ORDER BY d.pct_chg DESC
                """))
                rows = result.fetchall()
                if rows:
                    insights.append("## 涨跌停附近股票\n")
                    for row in rows:
                        tag = "涨停" if row.pct_chg >= 9.5 else "跌停"
                        insights.append(f"- {tag} **{row.name}** ({row.ts_code}): {row.pct_chg:.2f}%")
                    insights.append("")

            if analysis_type in ("industry", "all"):
                # 4. 行业轮动检测
                result = db.execute(text(f"""
                    SELECT industry, avg_pct_chg, up_count, down_count, stock_count
                    FROM industry_aggregation
                    WHERE trade_date = (SELECT MAX(trade_date) FROM industry_aggregation)
                    ORDER BY avg_pct_chg DESC
                """))
                rows = result.fetchall()
                if rows:
                    insights.append("## 行业表现排名\n")
                    for i, row in enumerate(rows):
                        try:
                            avg_pct = float(row.avg_pct_chg)
                        except (TypeError, ValueError):
                            avg_pct = 0.0
                        tag = "🟢" if avg_pct > 1 else ("🔴" if avg_pct < -1 else "⚪")
                        insights.append(
                            f"{i+1}. {tag} **{row.industry}**: {avg_pct:.2f}% "
                            f"(涨{row.up_count}/跌{row.down_count}/{row.stock_count}只)"
                        )
                    insights.append("")

                    # 行业轮动信号
                    top_3 = rows[:3]
                    bottom_3 = rows[-3:]
                    insights.append("## 行业轮动信号\n")
                    insights.append(f"🏆 领涨板块: {', '.join(r.industry for r in top_3)}")
                    insights.append(f"📉 领跌板块: {', '.join(r.industry for r in bottom_3)}")

                    top_avg = sum(float(r.avg_pct_chg) for r in top_3) / 3
                    bottom_avg = sum(float(r.avg_pct_chg) for r in bottom_3) / 3
                    spread = top_avg - bottom_avg
                    if spread > 5:
                        insights.append(f"⚠️ 行业分化严重（极差 {spread:.1f}%），市场风格切换信号")
                    insights.append("")

            if analysis_type in ("quality", "all"):
                # 5. 数据质量检查
                insights.append("## 数据质量检查\n")
                tables = ["stocks", "daily_kline", "financial_reports", "money_flow",
                          "industry_aggregation", "stock_factors", "macro_data", "sentiment_data"]
                for t in tables:
                    try:
                        result = db.execute(text(f"SELECT COUNT(*) FROM {t}"))
                        cnt = result.fetchone()[0]
                        status = "✅" if cnt > 0 else "❌ 空表"
                        insights.append(f"- {status} {t}: {cnt} 条")
                    except Exception:
                        insights.append(f"- ⚠️ {t}: 表不存在或无法访问")

                insights.append(f"\n- 最新K线日期: {latest_date}")
                insights.append(f"- 数据状态: 正常" if latest_date else "- 数据状态: 异常")

        return "\n".join(insights) if insights else "未发现异常"

    except Exception as e:
        logger.error(f"[insight_tools] 异常检测失败: {traceback.format_exc()}")
        return f"异常检测失败: {str(e)}"


@tool
def analyze_trend(
    ts_code: str = "",
    days: int = 20,
) -> str:
    """分析个股趋势和信号。

    自动检测：
    - 均线排列（多头/空头）
    - 连续涨跌天数
    - 成交量趋势
    - 突破/支撑信号

    Args:
        ts_code: 股票代码（如 000001.SZ），为空则分析全市场
        days: 回溯天数（默认20天）
    """
    try:
        with SessionLocal() as db:
            if ts_code:
                result = db.execute(text(f"""
                    SELECT trade_date, open, high, low, close, vol, pct_chg
                    FROM daily_kline
                    WHERE ts_code = '{ts_code}'
                    ORDER BY trade_date DESC
                    LIMIT {days + 30}
                """))
                rows = result.fetchall()
                if not rows:
                    return f"未找到 {ts_code} 的K线数据"

                df = pd.DataFrame(
                    rows, columns=["trade_date", "open", "high", "low", "close", "vol", "pct_chg"]
                ).sort_values("trade_date").tail(days)

                name = ts_code
                result = db.execute(
                    text("SELECT name FROM stocks WHERE ts_code = :code"),
                    {"code": ts_code}
                )
                stock_row = result.fetchone()
                if stock_row:
                    name = stock_row[0]

                return _analyze_single_stock(df, name, ts_code)
            else:
                return "请提供 ts_code 参数分析具体股票，或使用 detect_anomalies 分析全市场"

    except Exception as e:
        logger.error(f"[insight_tools] 趋势分析失败: {traceback.format_exc()}")
        return f"趋势分析失败: {str(e)}"


def _analyze_single_stock(df: pd.DataFrame, name: str, ts_code: str) -> str:
    """分析单只股票的趋势"""
    lines = [f"## {name} ({ts_code}) 趋势分析\n"]

    closes = df["close"].values
    vols = df["vol"].values
    pct_chgs = df["pct_chg"].values

    # 1. 当前价格位置
    latest_close = closes[-1]
    recent_high = df["high"].max()
    recent_low = df["low"].min()
    pos_pct = (latest_close - recent_low) / (recent_high - recent_low) * 100 if recent_high != recent_low else 50

    lines.append(f"**最新价**: {latest_close:.2f}")
    lines.append(f"**近期区间**: {recent_low:.2f} ~ {recent_high:.2f}")
    lines.append(f"**价格位置**: {pos_pct:.0f}% (0%=低点, 100%=高点)")

    # 2. 均线分析
    if len(closes) >= 20:
        ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else np.mean(closes)
        ma10 = np.mean(closes[-10:]) if len(closes) >= 10 else np.mean(closes)
        ma20 = np.mean(closes[-20:])

        lines.append(f"\n**均线**: MA5={ma5:.2f}, MA10={ma10:.2f}, MA20={ma20:.2f}")

        if latest_close > ma5 > ma10 > ma20:
            lines.append("📈 **多头排列** — 短期看涨")
        elif latest_close < ma5 < ma10 < ma20:
            lines.append("📉 **空头排列** — 短期看跌")
        elif latest_close > ma20:
            lines.append("📊 价格在均线上方，中期偏多")
        else:
            lines.append("📊 价格在均线下方，中期偏空")

    # 3. 连续涨跌
    up_streak = 0
    down_streak = 0
    for i in range(len(pct_chgs) - 1, -1, -1):
        if pct_chgs[i] > 0:
            down_streak = 0
            up_streak += 1
        elif pct_chgs[i] < 0:
            up_streak = 0
            down_streak += 1
        else:
            break
    if up_streak >= 3:
        lines.append(f"🔴 **连涨 {up_streak} 天** — 注意短期回调风险")
    if down_streak >= 3:
        lines.append(f"🟢 **连跌 {down_streak} 天** — 可能出现超跌反弹")

    # 4. 成交量分析
    avg_vol = np.mean(vols)
    latest_vol = vols[-1]
    vol_ratio = latest_vol / avg_vol if avg_vol > 0 else 1
    if vol_ratio > 2:
        lines.append(f"📊 **成交量异常放大**: 当前成交量是均值的 {vol_ratio:.1f} 倍")
    elif vol_ratio < 0.5:
        lines.append(f"📊 **成交量萎缩**: 当前成交量仅为均值的 {vol_ratio:.1f} 倍")

    # 5. 波动率
    volatility = np.std(pct_chgs) if len(pct_chgs) > 1 else 0
    lines.append(f"\n**波动率**: {volatility:.2f}% (日度)")

    return "\n".join(lines)


def get_insight_tools() -> list:
    return [detect_anomalies, analyze_trend]