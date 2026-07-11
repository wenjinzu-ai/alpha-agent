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
        market = self._detect_market(code)
        market = market.lower()
        if market == "sz":
            return f"sz{code}"
        elif market == "sh":
            return f"sh{code}"
        elif market == "bj":
            return f"bj{code}"
        return code

    def _ts_code_to_code(self, ts_code: str) -> str:
        return ts_code.split(".")[0]

    def _code_to_ts_code(self, code: str, market: str = "sz") -> str:
        return f"{code}.{market.upper()}"

    def _detect_market(self, code: str) -> str:
        if code.startswith("6"):
            return "SH"
        elif code.startswith(("0", "3")):
            return "SZ"
        elif code.startswith(("4", "8", "9")):
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

        if report_type == "income":
            logger.info(f"[AkShare] 获取利润表: {ts_code}")
            df = self._safe_call(ak.stock_profit_sheet_by_yearly, symbol=code)
        elif report_type == "balance":
            logger.info(f"[AkShare] 获取资产负债表: {ts_code}")
            df = self._safe_call(ak.stock_balance_sheet_by_yearly, symbol=code)
        elif report_type == "cashflow":
            logger.info(f"[AkShare] 获取现金流量表: {ts_code}")
            df = self._safe_call(ak.stock_cash_flow_sheet_by_yearly, symbol=code)
        else:
            raise ValueError(f"不支持的报告类型: {report_type}")

        if df.empty:
            return df

        if "date" in df.columns:
            df["ts_code"] = ts_code
            df["report_type"] = report_type
        df = df.reset_index(drop=True)
        return df

    def get_financial_indicator(
        self,
        ts_code: str,
        period: Optional[str] = None,
    ) -> pd.DataFrame:
        return pd.DataFrame()