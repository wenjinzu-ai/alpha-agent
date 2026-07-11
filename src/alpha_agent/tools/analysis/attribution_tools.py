"""归因分析工具 —— 让 Agent 能回答"为什么"，而不只是"是什么"。

归因类型：
1. 个股归因：为什么涨/跌？→ 财务、新闻、资金流向、行业联动
2. 行业归因：为什么板块涨/跌？→ 成分股表现、政策、资金流向
3. 市场归因：为什么大盘涨/跌？→ 板块贡献、资金面、情绪面

核心流程：数据 → 下钻 → 搜索 → 综合
"""
from __future__ import annotations
import traceback
from typing import Optional

import pandas as pd
from langchain_core.tools import tool
from sqlalchemy import text

from alpha_agent.infra.db.database import SessionLocal
from alpha_agent.utils.logger import logger


@tool
def attribute_stock_movement(
    ts_code: str = "",
    days: int = 5,
) -> str:
    """归因分析：解释某只股票为什么涨/跌。

    自动分析：
    1. 近期走势和涨跌幅
    2. 同行业对比（是否行业联动）
    3. 资金流向（是否有主力资金进出）
    4. 成交量变化（是否放量）
    5. 相关新闻（外部搜索）

    Args:
        ts_code: 股票代码（如 000001.SZ、600519.SH）
        days: 回溯天数（默认5天）
    """
    if not ts_code:
        return "请提供股票代码 ts_code（如 000001.SZ）"

    try:
        with SessionLocal() as db:
            # 1. 获取股票基本信息
            result = db.execute(
                text("SELECT name, industry, area FROM stocks WHERE ts_code = :code"),
                {"code": ts_code}
            )
            stock = result.fetchone()
            if not stock:
                return f"未找到股票 {ts_code}"

            name, industry, area = stock

            # 2. 获取近期K线
            result = db.execute(text(f"""
                SELECT trade_date, open, high, low, close, vol, pct_chg, amount
                FROM daily_kline
                WHERE ts_code = '{ts_code}'
                ORDER BY trade_date DESC
                LIMIT {days + 5}
            """))
            rows = result.fetchall()
            if not rows:
                return f"未找到 {name} 的K线数据"

            df = pd.DataFrame(
                rows, columns=["trade_date", "open", "high", "low", "close", "vol", "pct_chg", "amount"]
            ).sort_values("trade_date")
            for col in ["open", "high", "low", "close", "vol", "pct_chg", "amount"]:
                df[col] = df[col].astype(float)

            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else None

            lines = [f"## {name} ({ts_code}) 归因分析\n"]

            # 走势描述
            total_pct = df["pct_chg"].tail(days).sum()
            direction = "上涨" if total_pct > 0 else "下跌"
            lines.append(f"**近{days}日走势**: {direction} {total_pct:.2f}%")
            lines.append(f"**最新价**: {latest['close']:.2f} | 涨跌幅: {latest['pct_chg']:.2f}%")
            if prev is not None:
                lines.append(f"**前一日**: {prev['pct_chg']:.2f}%")

            # 成交量分析
            avg_vol = df["vol"].tail(10).mean() if len(df) >= 10 else df["vol"].mean()
            vol_ratio = latest["vol"] / avg_vol if avg_vol > 0 else 1
            if vol_ratio > 2:
                lines.append(f"**成交量**: {vol_ratio:.1f}倍放量（异常信号）")
            elif vol_ratio > 1.5:
                lines.append(f"**成交量**: {vol_ratio:.1f}倍放量")
            elif vol_ratio < 0.5:
                lines.append(f"**成交量**: 缩量至{vol_ratio:.1f}倍")

            lines.append(f"**行业**: {industry} | **地区**: {area}")

            # 3. 同行业对比
            if industry:
                latest_date = str(df.iloc[-1]["trade_date"])
                result = db.execute(text(f"""
                    SELECT d.ts_code, s.name, d.pct_chg
                    FROM daily_kline d
                    JOIN stocks s ON d.ts_code = s.ts_code
                    WHERE s.industry = '{industry}'
                      AND d.trade_date = '{latest_date}'
                    ORDER BY d.pct_chg DESC
                """))
                industry_rows = result.fetchall()
                if industry_rows:
                    industry_pcts = [float(r.pct_chg) for r in industry_rows]
                    industry_avg = sum(industry_pcts) / len(industry_pcts)
                    rank = sum(1 for p in industry_pcts if p > float(latest["pct_chg"])) + 1

                    lines.append(f"\n## 行业对比: {industry}")
                    lines.append(f"**行业均值**: {industry_avg:.2f}% | **行业排名**: {rank}/{len(industry_pcts)}")
                    lines.append(f"**行业领涨**: {industry_rows[0].name} ({float(industry_rows[0].pct_chg):.2f}%)")
                    lines.append(f"**行业领跌**: {industry_rows[-1].name} ({float(industry_rows[-1].pct_chg):.2f}%)")

                    diff_from_industry = float(latest["pct_chg"]) - industry_avg
                    if abs(diff_from_industry) > 2:
                        if diff_from_industry > 0:
                            lines.append(f"⚠️ 强于行业 {diff_from_industry:.1f}%，可能存在个股独立利好")
                        else:
                            lines.append(f"⚠️ 弱于行业 {abs(diff_from_industry):.1f}%，可能受个股利空影响")
                    elif abs(diff_from_industry) < 0.5:
                        lines.append(f"📊 与行业走势一致，主要受行业整体影响")

            # 4. 资金流向
            result = db.execute(text(f"""
                SELECT trade_date, main_net_inflow, super_large_net_inflow, large_net_inflow
                FROM money_flow
                WHERE ts_code = '{ts_code}'
                ORDER BY trade_date DESC
                LIMIT {days}
            """))
            flow_rows = result.fetchall()
            if flow_rows:
                main_flows = [float(r.main_net_inflow) for r in flow_rows]
                total_main_flow = sum(main_flows)
                lines.append(f"\n## 资金流向")
                lines.append(f"**近{days}日主力净流入**: {total_main_flow/10000:.0f}万元")
                if total_main_flow > 0:
                    lines.append("📈 主力资金净流入，资金面偏多")
                else:
                    lines.append("📉 主力资金净流出，资金面偏空")

            # 5. 归因总结
            lines.append(f"\n## 归因总结")
            factors = []

            if total_pct > 1:
                factors.append(f"近{days}日累计上涨{total_pct:.1f}%")
            elif total_pct < -1:
                factors.append(f"近{days}日累计下跌{abs(total_pct):.1f}%")

            if vol_ratio > 2:
                factors.append("成交量异常放大，多空分歧加剧")
            elif vol_ratio < 0.5:
                factors.append("缩量运行，市场关注度低")

            if industry and abs(float(latest["pct_chg"]) - industry_avg) > 2:
                factors.append("个股走势独立于行业，存在个股层面因素")

            if flow_rows:
                if total_main_flow > 0:
                    factors.append("主力资金净流入，有资金关注")
                else:
                    factors.append("主力资金净流出，资金撤离")

            for i, f in enumerate(factors, 1):
                lines.append(f"{i}. {f}")

            lines.append(f"\n💡 建议通过 web_search 搜索 **{name}** 相关新闻，获取更多归因信息。")

            return "\n".join(lines)

    except Exception as e:
        logger.error(f"[attribution_tools] 个股归因失败: {traceback.format_exc()}")
        return f"归因分析失败: {str(e)}"


@tool
def attribute_industry_movement(
    industry: str = "",
) -> str:
    """归因分析：解释某个行业为什么涨/跌。

    自动分析：
    1. 行业整体涨跌幅
    2. 成分股表现（领涨/领跌/拖累）
    3. 资金流向
    4. 行业轮动位置

    Args:
        industry: 行业名称（如 银行、医药、半导体）
    """
    if not industry:
        return "请提供行业名称 industry（如 银行、医药、半导体）"

    try:
        with SessionLocal() as db:
            # 获取最新交易日
            result = db.execute(text("SELECT MAX(trade_date) FROM daily_kline"))
            latest_date = result.fetchone()[0]

            # 1. 行业聚合数据
            result = db.execute(text(f"""
                SELECT trade_date, avg_pct_chg, up_count, down_count, stock_count,
                       total_amount, total_volume
                FROM industry_aggregation
                WHERE industry = '{industry}'
                ORDER BY trade_date DESC
                LIMIT 5
            """))
            agg_rows = result.fetchall()
            if not agg_rows:
                # 尝试模糊匹配
                result = db.execute(text(f"""
                    SELECT industry FROM industry_aggregation
                    WHERE POSITION('{industry}' IN industry) > 0
                    GROUP BY industry
                    LIMIT 5
                """))
                similar = [r[0] for r in result.fetchall()]
                if similar:
                    return f"未找到行业 '{industry}'，可能的匹配: {', '.join(similar)}"
                return f"未找到行业 '{industry}' 的数据"

            latest_agg = agg_rows[0]
            lines = [f"## {industry} 行业归因分析\n"]

            avg_pct = float(latest_agg.avg_pct_chg)
            direction = "上涨" if avg_pct > 0 else "下跌"
            lines.append(f"**最新交易日 {latest_date}**: {direction} {avg_pct:.2f}%")
            lines.append(f"**涨跌比**: {latest_agg.up_count}涨/{latest_agg.down_count}跌/{latest_agg.stock_count}只")

            # 连续趋势
            if len(agg_rows) >= 3:
                recent_pcts = [float(r.avg_pct_chg) for r in agg_rows]
                all_up = all(p > 0 for p in recent_pcts)
                all_down = all(p < 0 for p in recent_pcts)
                if all_up:
                    lines.append("📈 连续上涨，行业趋势向好")
                elif all_down:
                    lines.append("📉 连续下跌，行业趋势偏弱")

            # 2. 成分股明细
            result = db.execute(text(f"""
                SELECT d.ts_code, s.name, d.pct_chg, d.amount, d.vol
                FROM daily_kline d
                JOIN stocks s ON d.ts_code = s.ts_code
                WHERE s.industry = '{industry}'
                  AND d.trade_date = '{latest_date}'
                ORDER BY d.pct_chg DESC
            """))
            constituents = result.fetchall()
            if constituents:
                lines.append(f"\n## 成分股表现（共{len(constituents)}只）")
                top3 = constituents[:3]
                bottom3 = constituents[-3:]
                lines.append("**领涨 TOP3**:")
                for i, c in enumerate(top3, 1):
                    lines.append(f"  {i}. {c.name} ({c.ts_code}): {float(c.pct_chg):.2f}%")
                lines.append("**领跌 BOTTOM3**:")
                for i, c in enumerate(bottom3, 1):
                    lines.append(f"  {len(constituents)-len(bottom3)+i}. {c.name} ({c.ts_code}): {float(c.pct_chg):.2f}%")

                # 权重股影响
                amounts = [float(c.amount) for c in constituents]
                total_amount = sum(amounts)
                if total_amount > 0:
                    top_by_amount = sorted(constituents, key=lambda c: float(c.amount), reverse=True)[:3]
                    lines.append(f"\n**权重股影响**:")
                    for c in top_by_amount:
                        amt_share = float(c.amount) / total_amount * 100
                        lines.append(f"  {c.name}: 成交占比 {amt_share:.1f}%, 涨跌 {float(c.pct_chg):.2f}%")

            # 3. 行业轮动位置
            result = db.execute(text(f"""
                SELECT industry, avg_pct_chg
                FROM industry_aggregation
                WHERE trade_date = '{latest_date}'
                ORDER BY avg_pct_chg DESC
            """))
            all_industries = result.fetchall()
            if all_industries:
                rank = sum(1 for r in all_industries if float(r.avg_pct_chg) > avg_pct) + 1
                total = len(all_industries)
                lines.append(f"\n## 行业轮动位置")
                lines.append(f"**排名**: {rank}/{total}")

                if rank <= total * 0.2:
                    lines.append("🏆 处于领涨梯队，行业景气度高")
                elif rank >= total * 0.8:
                    lines.append("📉 处于领跌梯队，行业承压")
                elif rank <= total * 0.5:
                    lines.append("📊 处于中上游，行业相对稳健")
                else:
                    lines.append("📊 处于中下游，行业相对偏弱")

            # 4. 归因总结
            lines.append(f"\n## 归因总结")
            factors = []

            if avg_pct > 1:
                factors.append(f"{industry}板块整体强势，{avg_pct:.1f}%涨幅")
            elif avg_pct < -1:
                factors.append(f"{industry}板块整体下挫，{abs(avg_pct):.1f}%跌幅")

            if constituents:
                up_count = sum(1 for c in constituents if float(c.pct_chg) > 0)
                up_ratio = up_count / len(constituents)
                if up_ratio > 0.7:
                    factors.append("超7成个股上涨，板块普涨格局")
                elif up_ratio < 0.3:
                    factors.append("不足3成个股上涨，板块普跌格局")

            if len(agg_rows) >= 3:
                if all_up:
                    factors.append("连续多日上涨，趋势确认")
                elif all_down:
                    factors.append("连续多日下跌，趋势恶化")

            for i, f in enumerate(factors, 1):
                lines.append(f"{i}. {f}")

            lines.append(f"\n💡 建议通过 web_search 搜索 **{industry}行业** 最新政策/新闻")

            return "\n".join(lines)

    except Exception as e:
        logger.error(f"[attribution_tools] 行业归因失败: {traceback.format_exc()}")
        return f"归因分析失败: {str(e)}"


@tool
def attribute_market_movement(
    days: int = 1,
) -> str:
    """归因分析：解释今天/近期大盘为什么涨/跌。

    自动分析：
    1. 全市场涨跌分布
    2. 板块贡献（哪些板块拖累/拉动）
    3. 权重股影响
    4. 资金面

    Args:
        days: 回溯天数（默认1天，即今天）
    """
    try:
        with SessionLocal() as db:
            result = db.execute(text("SELECT MAX(trade_date) FROM daily_kline"))
            latest_date = result.fetchone()[0]

            lines = [f"## 全市场归因分析（{latest_date}）\n"]

            # 1. 全市场涨跌统计
            result = db.execute(text(f"""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN pct_chg > 0 THEN 1 ELSE 0 END) as up_count,
                    SUM(CASE WHEN pct_chg < 0 THEN 1 ELSE 0 END) as down_count,
                    SUM(CASE WHEN pct_chg = 0 THEN 1 ELSE 0 END) as flat_count,
                    AVG(CAST(pct_chg AS FLOAT)) as avg_pct,
                    SUM(CAST(amount AS FLOAT)) as total_amount
                FROM daily_kline
                WHERE trade_date = '{latest_date}'
            """))
            market = result.fetchone()
            if market:
                total = market.total
                up = market.up_count
                down = market.down_count
                avg_pct = float(market.avg_pct) if market.avg_pct else 0
                total_amount = float(market.total_amount) if market.total_amount else 0

                direction = "上涨" if avg_pct > 0 else "下跌"
                lines.append(f"**全市场**: {direction} {avg_pct:.2f}%")
                lines.append(f"**涨跌比**: {up}涨/{down}跌/{market.flat_count}平（共{total}只）")
                lines.append(f"**上涨占比**: {up/total*100:.1f}%")
                lines.append(f"**总成交额**: {total_amount/1e8:.0f}亿")
                lines.append("")

            # 2. 板块贡献
            result = db.execute(text(f"""
                SELECT industry, avg_pct_chg, stock_count, up_count, down_count
                FROM industry_aggregation
                WHERE trade_date = '{latest_date}'
                ORDER BY avg_pct_chg DESC
            """))
            industries = result.fetchall()
            if industries:
                lines.append("## 板块贡献分析")
                lines.append("**领涨板块 TOP5**:")
                for i, ind in enumerate(industries[:5], 1):
                    lines.append(f"  {i}. {ind.industry}: {float(ind.avg_pct_chg):.2f}% ({ind.up_count}涨/{ind.down_count}跌)")
                lines.append("**领跌板块 BOTTOM5**:")
                for i, ind in enumerate(industries[-5:], 1):
                    lines.append(f"  {i}. {ind.industry}: {float(ind.avg_pct_chg):.2f}% ({ind.up_count}涨/{ind.down_count}跌)")

                # 极差
                top_avg = float(industries[0].avg_pct_chg)
                bottom_avg = float(industries[-1].avg_pct_chg)
                spread = top_avg - bottom_avg
                if spread > 5:
                    lines.append(f"\n⚠️ 板块分化严重（极差 {spread:.1f}%），市场结构性行情")

            # 3. 权重股影响
            result = db.execute(text(f"""
                SELECT d.ts_code, s.name, d.pct_chg, d.amount
                FROM daily_kline d
                JOIN stocks s ON d.ts_code = s.ts_code
                WHERE d.trade_date = '{latest_date}'
                ORDER BY CAST(d.amount AS FLOAT) DESC
                LIMIT 10
            """))
            heavy = result.fetchall()
            if heavy:
                heavy_pcts = [float(r.pct_chg) for r in heavy]
                heavy_avg = sum(heavy_pcts) / len(heavy_pcts)
                lines.append(f"\n## 权重股（成交额TOP10）")
                lines.append(f"**权重股均值**: {heavy_avg:.2f}%")
                for i, h in enumerate(heavy[:5], 1):
                    lines.append(f"  {i}. {h.name}: {float(h.pct_chg):.2f}% ({float(h.amount)/1e8:.1f}亿)")
                if heavy_avg * avg_pct < 0:
                    lines.append("⚠️ 权重股与全市场方向背离")

            # 4. 归因总结
            lines.append(f"\n## 归因总结")
            factors = []

            if avg_pct > 0.5:
                factors.append("市场整体走强，多方占优")
            elif avg_pct < -0.5:
                factors.append("市场整体走弱，空方占优")
            else:
                factors.append("市场窄幅震荡，多空均衡")

            if up / total > 0.7:
                factors.append("普涨格局，赚钱效应好")
            elif down / total > 0.7:
                factors.append("普跌格局，市场情绪低迷")

            if industries:
                if spread > 5:
                    factors.append("板块分化严重，结构性行情特征明显")

            for i, f in enumerate(factors, 1):
                lines.append(f"{i}. {f}")

            return "\n".join(lines)

    except Exception as e:
        logger.error(f"[attribution_tools] 市场归因失败: {traceback.format_exc()}")
        return f"归因分析失败: {str(e)}"


def get_attribution_tools() -> list:
    return [attribute_stock_movement, attribute_industry_movement, attribute_market_movement]