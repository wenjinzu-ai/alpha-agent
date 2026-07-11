from abc import ABC, abstractmethod
from typing import Optional
import pandas as pd


class DataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_stock_basic(self, ts_code: Optional[str] = None) -> pd.DataFrame:
        pass

    @abstractmethod
    def get_daily_kline(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: str = "daily",
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        pass

    @abstractmethod
    def get_financial_report(
        self,
        ts_code: str,
        report_type: str = "income",
        period: Optional[str] = None,
    ) -> pd.DataFrame:
        pass

    @abstractmethod
    def get_financial_indicator(
        self,
        ts_code: str,
        period: Optional[str] = None,
    ) -> pd.DataFrame:
        pass

    def get_stock_news(self, ts_code: str, limit: int = 20) -> pd.DataFrame:
        return pd.DataFrame()

    def get_stock_announcement(self, ts_code: str, limit: int = 20) -> pd.DataFrame:
        return pd.DataFrame()

    def get_realtime_quote(self, ts_code: str) -> pd.DataFrame:
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
