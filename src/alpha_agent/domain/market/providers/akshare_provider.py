import threading
from typing import Optional
import pandas as pd

from alpha_agent.domain.market.providers.base import DataProvider
from alpha_agent.utils.logger import logger


class AkShareProvider(DataProvider):
    name = "akshare"
    _init_lock = threading.Lock()
    _call_lock = threading.Lock()

    def __init__(self):
        self._ak = None

    def _ensure_ak(self):
        if self._ak is None:
            with AkShareProvider._init_lock:
                if self._ak is None:
                    import akshare as ak
                    self._ak = ak
        return self._ak

    def _safe_call(self, func, *args, **kwargs):
        with AkShareProvider._call_lock:
            return func(*args, **kwargs)

    def _ts_code_to_sina_symbol(self, ts_code: str) -> str:
        parts = ts_code.split(".")
        if len(parts) != 2:
            return ts_code
        code, market = parts
        market = market.lower()
        if market == "sz":
            return f"sz{code}"
        elif market == "sh":
            return f"sh{code}"
        return code

    def _ts_code_to_code(self, ts_code: str) -> str:
        return ts_code.split(".")[0]

    def _code_to_ts_code(self, code: str, market: str = "sz") -> str:
        return f"{code}.{market.upper()}"

    def _detect_market(self, code: str) -> str:
        if code.startswith("6"):
            return "SH"
        elif code.startswith("0") or code.startswith("3"):
            return "SZ"
        elif code.startswith("8") or code.startswith("4"):
            return "BJ"
        return "SZ"

    def get_stock_basic(self, ts_code: Optional[str] = None) -> pd.DataFrame:
        ak = self._ensure_ak()
        logger.info("[AkShare] 获取股票列表...")

        df = self._safe_call(ak.stock_info_a_code_name)
        df = df.rename(columns={
            "code": "symbol",
            "name": "name",
        })
        df["market"] = df["symbol"].apply(self._detect_market)
        df["ts_code"] = df.apply(
            lambda r: self._code_to_ts_code(r["symbol"], r["market"].lower()),
            axis=1,
        )
        if ts_code:
            symbol = self._ts_code_to_code(ts_code)
            df = df[df["symbol"] == symbol]
        return df.reset_index(drop=True)

    def get_daily_kline(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: str = "daily",
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        ak = self._ensure_ak()
        symbol = self._ts_code_to_sina_symbol(ts_code)
        logger.info(f"[AkShare] 获取K线: {ts_code} (sina: {symbol}), adjust={adjust}")

        kwargs = {"symbol": symbol, "adjust": adjust}
        if start_date:
            kwargs["start_date"] = start_date
        if end_date:
            kwargs["end_date"] = end_date
        df = self._safe_call(ak.stock_zh_a_daily, **kwargs)

        if df.empty:
            return df

        df = df.rename(columns={
            "date": "trade_date",
            "open": "open",
            "close": "close",
            "high": "high",
            "low": "low",
            "volume": "vol",
            "amount": "amount",
        })
        df["ts_code"] = ts_code
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y%m%d")
        df["pct_chg"] = df["close"].pct_change() * 100
        df["change"] = df["close"].diff()
        df = df.sort_values("trade_date").reset_index(drop=True)
        return df

    def get_financial_report(
        self,
        ts_code: str,
        report_type: str = "income",
        period: Optional[str] = None,
    ) -> pd.DataFrame:
        ak = self._ensure_ak()
        code = self._ts_code_to_code(ts_code)
        logger.info(f"[AkShare] 获取财务报表: {ts_code}, type={report_type}")

        type_map = {
            "income": "利润表",
            "balance": "资产负债表",
            "cashflow": "现金流量表",
        }
        sina_type = type_map.get(report_type, "利润表")

        try:
            df = self._safe_call(ak.stock_financial_report_sina, stock=code, symbol=sina_type)
            if not df.empty:
                df["ts_code"] = ts_code
            return df
        except Exception as e:
            logger.warning(f"[AkShare] 获取财务报表失败: {e}")
            return pd.DataFrame()

    def get_financial_indicator(
        self,
        ts_code: str,
        period: Optional[str] = None,
    ) -> pd.DataFrame:
        ak = self._ensure_ak()
        code = self._ts_code_to_code(ts_code)
        logger.info(f"[AkShare] 获取财务指标: {ts_code}")

        try:
            df = self._safe_call(ak.stock_financial_analysis_indicator, symbol=code)
            if not df.empty:
                df["ts_code"] = ts_code
            return df
        except Exception as e:
            logger.warning(f"[AkShare] 获取财务指标失败: {e}")
            return pd.DataFrame()

    def get_stock_news(self, ts_code: str, limit: int = 20) -> pd.DataFrame:
        ak = self._ensure_ak()
        code = self._ts_code_to_code(ts_code)
        logger.info(f"[AkShare] 获取个股新闻: {ts_code}")

        try:
            df = self._safe_call(ak.stock_news_em, symbol=code)
            if df is None or df.empty:
                return pd.DataFrame()
            df["ts_code"] = ts_code
            if len(df) > limit:
                df = df.head(limit)
            return df
        except Exception as e:
            logger.warning(f"[AkShare] 获取个股新闻失败: {e}")
            return pd.DataFrame()

    def get_stock_announcement(self, ts_code: str, limit: int = 20) -> pd.DataFrame:
        ak = self._ensure_ak()
        code = self._ts_code_to_code(ts_code)
        logger.info(f"[AkShare] 获取个股公告: {ts_code}")

        try:
            df = self._safe_call(ak.stock_notice_report, symbol=code)
            if df is None or df.empty:
                return pd.DataFrame()
            df["ts_code"] = ts_code
            if len(df) > limit:
                df = df.head(limit)
            return df
        except Exception as e:
            logger.warning(f"[AkShare] 获取个股公告失败: {e}")
            return pd.DataFrame()

    def get_realtime_quote(self, ts_code: str) -> pd.DataFrame:
        ak = self._ensure_ak()
        code = self._ts_code_to_code(ts_code)
        logger.info(f"[AkShare] 获取实时行情: {ts_code}")

        try:
            df = self._safe_call(ak.stock_zh_a_spot_em)
            if df is None or df.empty:
                return pd.DataFrame()
            target = df[df["代码"].astype(str) == code]
            if target.empty:
                return pd.DataFrame()
            target = target.copy()
            target["ts_code"] = ts_code
            return target.reset_index(drop=True)
        except Exception as e:
            logger.warning(f"[AkShare] 获取实时行情失败: {e}")
            return pd.DataFrame()

    def get_etf_list(self) -> pd.DataFrame:
        ak = self._ensure_ak()
        logger.info("[AkShare] 获取ETF列表 (新浪)...")

        try:
            df = self._safe_call(ak.fund_etf_category_sina, symbol="ETF基金")
            if df is None or df.empty:
                return pd.DataFrame()

            result = []
            for _, row in df.iterrows():
                code_full = str(row.get("代码", ""))
                name = str(row.get("名称", ""))
                if not code_full or len(code_full) < 3:
                    continue
                market_prefix = code_full[:2].lower()
                code = code_full[2:]
                if market_prefix == "sh":
                    market = "SH"
                elif market_prefix == "sz":
                    market = "SZ"
                else:
                    continue
                ts_code = f"{code}.{market}"
                result.append({
                    "ts_code": ts_code,
                    "symbol": code,
                    "name": name,
                    "market": market,
                })
            result_df = pd.DataFrame(result)
            logger.info(f"[AkShare] 获取ETF列表完成: {len(result_df)} 只")
            return result_df
        except Exception as e:
            logger.warning(f"[AkShare] 获取ETF列表失败: {e}")
            return pd.DataFrame()

    def get_etf_daily_kline(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        ak = self._ensure_ak()
        symbol = self._ts_code_to_sina_symbol(ts_code)
        logger.info(f"[AkShare] 获取ETF K线: {ts_code} (sina: {symbol})")

        try:
            df = self._safe_call(ak.fund_etf_hist_sina, symbol=symbol)
            if df is None or df.empty:
                return pd.DataFrame()

            df = df.rename(columns={
                "date": "trade_date",
                "open": "open",
                "close": "close",
                "high": "high",
                "low": "low",
                "volume": "vol",
                "amount": "amount",
            })
            df["ts_code"] = ts_code
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y%m%d")
            df["pct_chg"] = df["close"].pct_change() * 100
            df["change"] = df["close"].diff()

            if start_date:
                df = df[df["trade_date"] >= start_date]
            if end_date:
                df = df[df["trade_date"] <= end_date]

            df = df.sort_values("trade_date").reset_index(drop=True)
            return df
        except Exception as e:
            logger.warning(f"[AkShare] 获取ETF K线失败: {e}")
            return pd.DataFrame()

    def get_financial_data(self, ts_code: str) -> list:
        ak = self._ensure_ak()
        code = self._ts_code_to_code(ts_code)
        logger.info(f"[AkShare] 获取财务摘要: {ts_code}")

        try:
            df = self._safe_call(ak.stock_financial_abstract, symbol=code)
            if df is None or df.empty:
                return []

            records = []
            for _, row in df.iterrows():
                try:
                    end_date = str(row.get("截止日期", "")).replace("-", "")
                    report_type = str(row.get("报表类型", ""))
                    total_revenue = float(row.get("营业总收入", 0) or 0)
                    net_profit = float(row.get("归母净利润", 0) or 0)
                    eps = float(row.get("基本每股收益", 0) or 0)
                    roe = float(row.get("净资产收益率", 0) or 0)
                    records.append({
                        "end_date": end_date,
                        "report_type": report_type,
                        "total_revenue": round(total_revenue, 2),
                        "net_profit": round(net_profit, 2),
                        "eps": round(eps, 4),
                        "roe": round(roe, 4),
                        "gross_margin": 0,
                        "net_margin": 0,
                    })
                except (ValueError, TypeError):
                    continue
            return records

        except Exception as e:
            logger.warning(f"[AkShare] 获取财务摘要失败 {ts_code}: {e}")
            return []

    def get_money_flow(self, ts_code: str, trade_date: str) -> list:
        ak = self._ensure_ak()
        code = self._ts_code_to_code(ts_code)
        logger.info(f"[AkShare] 获取资金流向: {ts_code}")

        try:
            df = self._safe_call(ak.stock_individual_fund_flow, stock=code, market="sh" if code.startswith("6") else "sz")
            if df is None or df.empty:
                return []

            df = df[df["日期"].astype(str).str.replace("-", "") == trade_date]
            if df.empty:
                return []

            row = df.iloc[0]
            return [{
                "ts_code": ts_code,
                "trade_date": trade_date,
                "flow_type": "stock",
                "main_net_inflow": round(float(row.get("主力净流入", 0) or 0), 2),
                "super_large_net_inflow": round(float(row.get("超大单净流入", 0) or 0), 2),
                "large_net_inflow": round(float(row.get("大单净流入", 0) or 0), 2),
                "medium_net_inflow": round(float(row.get("中单净流入", 0) or 0), 2),
                "small_net_inflow": round(float(row.get("小单净流入", 0) or 0), 2),
                "main_net_inflow_rate": round(float(row.get("主力净流入占比", 0) or 0), 4),
                "super_large_net_inflow_rate": round(float(row.get("超大单净流入占比", 0) or 0), 4),
                "large_net_inflow_rate": round(float(row.get("大单净流入占比", 0) or 0), 4),
                "medium_net_inflow_rate": round(float(row.get("中单净流入占比", 0) or 0), 4),
                "small_net_inflow_rate": round(float(row.get("小单净流入占比", 0) or 0), 4),
            }]

        except Exception as e:
            logger.warning(f"[AkShare] 获取资金流向失败 {ts_code}: {e}")
            return []

    def get_macro_data(self) -> list:
        ak = self._ensure_ak()
        logger.info("[AkShare] 获取宏观经济数据...")

        records = []
        macro_fetchers = [
            ("GDP同比", "macro_china_gdp_yearly", "gdp"),
            ("CPI同比", "macro_china_cpi_monthly", "cpi"),
            ("PMI", "macro_china_pmi", "pmi"),
            ("M2同比", "macro_china_money_supply", "m2"),
            ("社会融资规模", "macro_china_shrzgm", "shrzgm"),
        ]

        for indicator, func_name, source in macro_fetchers:
            try:
                func = getattr(ak, func_name, None)
                if func is None:
                    continue
                df = self._safe_call(func)
                if df is None or df.empty:
                    continue

                date_col = df.columns[0]
                val_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]

                latest = df.iloc[-1]
                period = str(latest[date_col]).replace("-", "")[:6]
                raw_val = latest[val_col]
                if raw_val is None:
                    value = 0
                elif hasattr(raw_val, 'year'):
                    value = 0
                else:
                    try:
                        value = float(raw_val)
                    except (ValueError, TypeError):
                        value = 0

                records.append({
                    "indicator": indicator,
                    "period": period,
                    "value": round(value, 4),
                    "unit": "%",
                    "source": source,
                })
            except Exception as e:
                logger.warning(f"[AkShare] 获取宏观数据失败 {indicator}: {e}")

        logger.info(f"[AkShare] 获取宏观经济数据完成: {len(records)} 条")
        return records

    def get_sentiment_data(self, trade_date: str) -> list:
        ak = self._ensure_ak()
        logger.info(f"[AkShare] 获取市场情绪数据 ({trade_date})...")

        records = []
        try:
            zh_df = self._safe_call(ak.stock_zh_a_spot_em)
            if zh_df is not None and not zh_df.empty:
                up_count = int((zh_df["涨跌幅"].astype(float) > 0).sum())
                down_count = int((zh_df["涨跌幅"].astype(float) < 0).sum())
                neutral_count = int((zh_df["涨跌幅"].astype(float) == 0).sum())
                total = len(zh_df)
                sentiment_score = ((up_count - down_count) / total) * 100 if total > 0 else 0

                records.append({
                    "ts_code": "",
                    "trade_date": trade_date,
                    "sentiment_type": "market",
                    "positive_count": up_count,
                    "negative_count": down_count,
                    "neutral_count": neutral_count,
                    "sentiment_score": round(sentiment_score, 4),
                    "heat_index": round(up_count / total * 100, 4) if total > 0 else 0,
                })

            avg_volume = zh_df["成交量"].astype(float).mean() if zh_df is not None and not zh_df.empty else 0
            avg_turnover = zh_df["换手率"].astype(float).mean() if zh_df is not None and not zh_df.empty else 0
            records.append({
                "ts_code": "",
                "trade_date": trade_date,
                "sentiment_type": "activity",
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "sentiment_score": round(avg_turnover, 4),
                "heat_index": round(avg_volume, 4),
            })

        except Exception as e:
            logger.warning(f"[AkShare] 获取市场情绪失败: {e}")

        logger.info(f"[AkShare] 获取舆情数据完成: {len(records)} 条")
        return records