import threading
from typing import Optional
import pandas as pd

from alpha_agent.domain.market.providers.base import DataProvider
from alpha_agent.utils.logger import logger


class BaoStockProvider(DataProvider):
    name = "baostock"
    _init_lock = threading.Lock()
    _call_lock = threading.Lock()
    _logged_in = False

    def __init__(self):
        self._bs = None

    def _ensure_bs(self):
        if self._bs is None:
            with BaoStockProvider._init_lock:
                if self._bs is None:
                    import baostock as bs
                    self._bs = bs
                    if not BaoStockProvider._logged_in:
                        lg = bs.login()
                        if lg.error_code == "0":
                            BaoStockProvider._logged_in = True
                            logger.info("[BaoStock] 登录成功")
                        else:
                            logger.error(f"[BaoStock] 登录失败: {lg.error_msg}")
        return self._bs

    def _safe_query(self, rs) -> pd.DataFrame:
        data_list = []
        while (rs.error_code == "0") and rs.next():
            data_list.append(rs.get_row_data())
        if rs.error_code != "0":
            logger.warning(f"[BaoStock] 查询错误: {rs.error_msg}")
        if not data_list:
            return pd.DataFrame()
        return pd.DataFrame(data_list, columns=rs.fields)

    def _bs_code_to_ts_code(self, bs_code: str) -> str:
        parts = bs_code.split(".")
        if len(parts) != 2:
            return bs_code
        market, code = parts
        return f"{code}.{market.upper()}"

    def _ts_code_to_bs_code(self, ts_code: str) -> str:
        parts = ts_code.split(".")
        if len(parts) != 2:
            return ts_code
        code, market = parts
        return f"{market.lower()}.{code}"

    def get_stock_basic(self, ts_code: Optional[str] = None) -> pd.DataFrame:
        bs = self._ensure_bs()
        logger.info("[BaoStock] 获取股票列表...")

        with BaoStockProvider._call_lock:
            rs = bs.query_stock_basic()
            df = self._safe_query(rs)

        if df.empty:
            return df

        df = df[df["type"] == "1"].copy()
        df["ts_code"] = df["code"].apply(self._bs_code_to_ts_code)
        df["symbol"] = df["ts_code"].apply(lambda x: x.split(".")[0])
        df["name"] = df["code_name"]
        df["market"] = df["ts_code"].apply(lambda x: x.split(".")[1])
        df["list_date"] = df["ipoDate"].str.replace("-", "")
        df["area"] = ""
        df["industry"] = ""
        df["is_active"] = df["status"] == "1"

        try:
            with BaoStockProvider._call_lock:
                rs_ind = bs.query_stock_industry()
                df_ind = self._safe_query(rs_ind)
            if not df_ind.empty:
                df_ind["ts_code"] = df_ind["code"].apply(self._bs_code_to_ts_code)
                industry_map = dict(zip(df_ind["ts_code"], df_ind["industry"]))
                df["industry"] = df["ts_code"].map(industry_map).fillna("")
        except Exception as e:
            logger.warning(f"[BaoStock] 获取行业分类失败: {e}")

        cols = ["ts_code", "symbol", "name", "area", "industry", "market", "list_date", "is_active"]
        df = df[cols]

        if ts_code:
            df = df[df["ts_code"] == ts_code]

        df = df.reset_index(drop=True)
        logger.info(f"[BaoStock] 获取股票列表完成: {len(df)} 只")
        return df

    def get_daily_kline(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: str = "daily",
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        bs = self._ensure_bs()
        code = self._ts_code_to_bs_code(ts_code)
        logger.info(f"[BaoStock] 获取K线: {ts_code} (bs: {code}), adjust={adjust}")

        adjustflag_map = {"none": "3", "qfq": "2", "hfq": "1"}
        adjustflag = adjustflag_map.get(adjust, "2")

        fields = "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg"

        bs_start = start_date[:4] + "-" + start_date[4:6] + "-" + start_date[6:] if start_date else ""
        bs_end = end_date[:4] + "-" + end_date[4:6] + "-" + end_date[6:] if end_date else ""

        with BaoStockProvider._call_lock:
            rs = bs.query_history_k_data_plus(
                code,
                fields,
                start_date=bs_start if bs_start else "1990-01-01",
                end_date=bs_end if bs_end else "2099-12-31",
                frequency="d",
                adjustflag=adjustflag,
            )
            df = self._safe_query(rs)

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
            "pctChg": "pct_chg",
        })

        numeric_cols = ["open", "close", "high", "low", "vol", "amount", "pct_chg"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df["ts_code"] = ts_code
        df["trade_date"] = df["trade_date"].str.replace("-", "")
        df["change"] = df["close"].diff()
        df = df.sort_values("trade_date").reset_index(drop=True)
        return df

    def get_financial_report(
        self,
        ts_code: str,
        report_type: str = "income",
        period: Optional[str] = None,
    ) -> pd.DataFrame:
        bs = self._ensure_bs()
        code = self._ts_code_to_bs_code(ts_code)
        logger.info(f"[BaoStock] 获取财务报表: {ts_code}, type={report_type}")

        try:
            with BaoStockProvider._call_lock:
                if report_type == "income":
                    rs = bs.query_profit_data(code=code, year=2024, quarter=4)
                elif report_type == "balance":
                    rs = bs.query_balance_data(code=code, year=2024, quarter=4)
                elif report_type == "cashflow":
                    rs = bs.query_cash_flow_data(code=code, year=2024, quarter=4)
                else:
                    rs = bs.query_profit_data(code=code, year=2024, quarter=4)

                df = self._safe_query(rs)
                if not df.empty:
                    df["ts_code"] = ts_code
                return df
        except Exception as e:
            logger.warning(f"[BaoStock] 获取财务报表失败: {e}")
            return pd.DataFrame()

    def get_financial_indicator(
        self,
        ts_code: str,
        period: Optional[str] = None,
    ) -> pd.DataFrame:
        bs = self._ensure_bs()
        code = self._ts_code_to_bs_code(ts_code)
        logger.info(f"[BaoStock] 获取财务指标: {ts_code}")

        try:
            with BaoStockProvider._call_lock:
                rs = bs.query_dupont_data(code=code, year=2024, quarter=4)
                df = self._safe_query(rs)
                if not df.empty:
                    df["ts_code"] = ts_code
                return df
        except Exception as e:
            logger.warning(f"[BaoStock] 获取财务指标失败: {e}")
            return pd.DataFrame()

    def get_etf_list(self) -> pd.DataFrame:
        return pd.DataFrame()

    def get_etf_daily_kline(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        return pd.DataFrame()
