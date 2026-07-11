from typing import List, Dict, Optional, Callable
import pandas as pd
from datetime import datetime

from alpha_agent.domain.market import get_data_service
from alpha_agent.infra.db.warehouse import get_data_warehouse
from alpha_agent.domain.factors.technical import (
    calc_technical_indicators,
    score_technical,
    score_momentum,
    score_value,
    calc_composite_score,
)
from alpha_agent.utils.logger import logger


class StockScreener:
    def __init__(self):
        self.ds = get_data_service()
        self.warehouse = get_data_warehouse()

    def scan(
        self,
        universe: str = "stock",
        top_n: int = 50,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        min_vol: Optional[float] = None,
        industries: Optional[List[str]] = None,
        market: Optional[str] = None,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[Dict]:
        if not self.warehouse.enabled:
            logger.warning("[screener] 本地数据仓库未启用，无法全市场扫描")
            return []

        if universe == "stock":
            stock_df = self.warehouse.get_stock_list(market=market)
        elif universe == "etf":
            stock_df = self.warehouse.get_etf_list(market=market)
        else:
            stock_df = pd.DataFrame()

        if stock_df.empty:
            logger.warning(f"[screener] 股票/ETF列表为空，请先同步数据")
            return []

        if industries and universe == "stock":
            stock_df = stock_df[stock_df["industry"].isin(industries)]

        total = len(stock_df)
        logger.info(f"[screener] 开始扫描，共 {total} 只标的")

        results = []
        success = 0
        failed = 0

        for idx, row in stock_df.iterrows():
            ts_code = row["ts_code"]
            name = row["name"]

            try:
                kline_df = self.ds.get_daily_kline(
                    ts_code=ts_code,
                    period="daily",
                    adjust="qfq",
                )

                if kline_df is None or kline_df.empty or len(kline_df) < 20:
                    failed += 1
                    if progress_cb:
                        progress_cb(idx + 1, total, ts_code)
                    continue

                latest_close = float(kline_df["close"].iloc[-1])
                latest_vol = float(kline_df["vol"].iloc[-1])

                if min_price and latest_close < min_price:
                    if progress_cb:
                        progress_cb(idx + 1, total, ts_code)
                    continue
                if max_price and latest_close > max_price:
                    if progress_cb:
                        progress_cb(idx + 1, total, ts_code)
                    continue
                if min_vol and latest_vol < min_vol:
                    if progress_cb:
                        progress_cb(idx + 1, total, ts_code)
                    continue

                indicators = calc_technical_indicators(kline_df)
                tech_score, tech_rating, _ = score_technical(indicators)
                mom_score, mom_rating = score_momentum(indicators)
                val_score, val_rating = score_value(indicators)
                comp_score, comp_rating = calc_composite_score(tech_score, mom_score, val_score)

                result = {
                    "ts_code": ts_code,
                    "name": name,
                    "latest_price": latest_close,
                    "latest_vol": latest_vol,
                    "industry": row.get("industry", "") if universe == "stock" else "",
                    "technical_score": tech_score,
                    "technical_rating": tech_rating,
                    "momentum_score": mom_score,
                    "momentum_rating": mom_rating,
                    "value_score": val_score,
                    "value_rating": val_rating,
                    "composite_score": comp_score,
                    "composite_rating": comp_rating,
                    "change_pct_1d": indicators.get("change_pct_1d"),
                    "change_pct_5d": indicators.get("change_pct_5d"),
                    "change_pct_20d": indicators.get("change_pct_20d"),
                    "change_pct_60d": indicators.get("change_pct_60d"),
                    "rsi_14": indicators.get("rsi_14"),
                    "vol_ratio": indicators.get("vol_ratio"),
                    "ma5": indicators.get("ma5"),
                    "ma20": indicators.get("ma20"),
                    "ma60": indicators.get("ma60"),
                    "data_count": len(kline_df),
                }
                results.append(result)
                success += 1

            except Exception as e:
                failed += 1
                logger.debug(f"[screener] 扫描失败 {ts_code}: {e}")

            if progress_cb:
                progress_cb(idx + 1, total, ts_code)

            if (idx + 1) % 100 == 0:
                logger.info(f"[screener] 进度: {idx+1}/{total}, 成功: {success}, 失败: {failed}")

        results.sort(key=lambda x: x["composite_score"], reverse=True)

        logger.info(f"[screener] 扫描完成: 总数{total}, 成功{success}, 失败{failed}")
        return results[:top_n]

    def get_scan_report(self, results: List[Dict], top_n: int = 20) -> str:
        if not results:
            return "暂无符合条件的标的"

        lines = [
            f"📊 全市场选股扫描结果",
            f"扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"共扫描 {len(results)} 只，展示前 {min(top_n, len(results))} 名",
            "",
            f"{'排名':<4}{'代码':<12}{'名称':<10}{'综合分':<8}{'评级':<10}{'技术':<6}{'动量':<6}{'价值':<6}{'20日涨跌':<10}",
            "-" * 80,
        ]

        for i, r in enumerate(results[:top_n], 1):
            lines.append(
                f"{i:<4}"
                f"{r['ts_code']:<12}"
                f"{r['name']:<10}"
                f"{r['composite_score']:<8.1f}"
                f"{r['composite_rating']:<10}"
                f"{r['technical_score']:<6.1f}"
                f"{r['momentum_score']:<6.1f}"
                f"{r['value_score']:<6.1f}"
                f"{r['change_pct_20d']:>8.1f}%" if r['change_pct_20d'] is not None else "    N/A"
            )

        lines.append("")
        lines.append("说明:")
        lines.append("  综合分 = 技术面40% + 动量35% + 价值25%")
        lines.append("  分数越高越看好，建议关注综合分>60的标的")

        return "\n".join(lines)


_screener: Optional[StockScreener] = None


def get_stock_screener() -> StockScreener:
    global _screener
    if _screener is None:
        _screener = StockScreener()
    return _screener
