from typing import List, Dict, Optional, Callable
import pandas as pd
import numpy as np
from datetime import datetime

from alpha_agent.domain.market import get_data_service
from alpha_agent.infra.db.warehouse import get_data_warehouse
from alpha_agent.domain.factors.technical import calc_technical_indicators
from alpha_agent.utils.logger import logger


class FactorService:
    def __init__(self):
        self.ds = get_data_service()
        self.warehouse = get_data_warehouse()

    def get_factors(
        self,
        ts_code: str,
        factor_names: Optional[List[str]] = None,
    ) -> Dict[str, float]:
        kline_df = self.ds.get_daily_kline(ts_code=ts_code, adjust="qfq")
        if kline_df is None or kline_df.empty:
            return {}

        indicators = calc_technical_indicators(kline_df)

        if factor_names is None:
            return indicators

        result = {}
        for name in factor_names:
            if name in indicators:
                result[name] = indicators[name]
        return result

    def batch_calc_factors(
        self,
        ts_codes: List[str],
        factor_names: Optional[List[str]] = None,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> pd.DataFrame:
        results = []
        total = len(ts_codes)

        for idx, code in enumerate(ts_codes):
            try:
                factors = self.get_factors(code, factor_names)
                if factors:
                    factors["ts_code"] = code
                    results.append(factors)
            except Exception as e:
                logger.debug(f"[factor] 计算因子失败 {code}: {e}")

            if progress_cb:
                progress_cb(idx + 1, total, code)

        return pd.DataFrame(results)

    def rank_by_factor(
        self,
        factor_name: str,
        universe: str = "stock",
        top_n: int = 50,
        ascending: bool = False,
    ) -> pd.DataFrame:
        if not self.warehouse.enabled:
            return pd.DataFrame()

        if universe == "stock":
            stock_df = self.warehouse.get_stock_list()
        elif universe == "etf":
            stock_df = self.warehouse.get_etf_list()
        else:
            return pd.DataFrame()

        if stock_df.empty:
            return pd.DataFrame()

        ts_codes = stock_df["ts_code"].tolist()
        factor_df = self.batch_calc_factors(ts_codes, [factor_name])

        if factor_df.empty:
            return pd.DataFrame()

        factor_df = factor_df.dropna(subset=[factor_name])
        factor_df = factor_df.sort_values(factor_name, ascending=ascending)
        factor_df = factor_df.head(top_n)

        name_map = dict(zip(stock_df["ts_code"], stock_df["name"]))
        factor_df["name"] = factor_df["ts_code"].map(name_map)

        cols = ["ts_code", "name", factor_name]
        factor_df = factor_df[cols]
        return factor_df.reset_index(drop=True)

    def get_available_factors(self) -> Dict[str, str]:
        return {
            "ma5": "5日均线",
            "ma10": "10日均线",
            "ma20": "20日均线",
            "ma60": "60日均线",
            "ma120": "120日均线",
            "ma250": "250日均线",
            "macd_dif": "MACD-DIF",
            "macd_dea": "MACD-DEA",
            "macd_bar": "MACD柱",
            "rsi_6": "RSI(6)",
            "rsi_14": "RSI(14)",
            "rsi_24": "RSI(24)",
            "kdj_k": "KDJ-K",
            "kdj_d": "KDJ-D",
            "kdj_j": "KDJ-J",
            "vol_ratio": "量比",
            "change_pct_1d": "1日涨跌幅",
            "change_pct_5d": "5日涨跌幅",
            "change_pct_20d": "20日涨跌幅",
            "change_pct_60d": "60日涨跌幅",
            "position_20d": "20日位置百分比",
            "volatility_60d": "60日波动率(%)",
            "latest_close": "最新收盘价",
        }


_factor_service: Optional[FactorService] = None


def get_factor_service() -> FactorService:
    global _factor_service
    if _factor_service is None:
        _factor_service = FactorService()
    return _factor_service
