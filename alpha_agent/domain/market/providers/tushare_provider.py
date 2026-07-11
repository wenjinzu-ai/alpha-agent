import threading
from typing import Optional
import pandas as pd

from alpha_agent.domain.market.providers.base import DataProvider
from alpha_agent.config import settings
from alpha_agent.utils.logger import logger


class TushareProvider(DataProvider):
    name = "tushare"
    _init_lock = threading.Lock()

    def __init__(self, token: Optional[str] = None):
        self._token = token or settings.tushare_token
        self._pro = None

    def _ensure_pro(self):
        if self._pro is None:
            with TushareProvider._init_lock:
                if self._pro is None:
                    if not self._token:
                        raise ValueError("Tushare token not configured")
                    import tushare as ts
                    ts.set_token(self._token)
                    self._pro = ts.pro_api()
        return self._pro

    def get_stock_basic(self, ts_code: Optional[str] = None) -> pd.DataFrame:
        pro = self._ensure_pro()
        logger.info("[Tushare] 获取股票列表...")

        df = pro.stock_basic(
            ts_code=ts_code or "",
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,list_date",
        )
        return df

    def get_daily_kline(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: str = "daily",
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        pro = self._ensure_pro()
        logger.info(f"[Tushare] 获取K线: {ts_code}, adjust={adjust}")

        if adjust in ("qfq", "hfq"):
            import tushare as ts
            df = ts.pro_bar(
                ts_code=ts_code,
                adj=adjust,
                start_date=start_date or "",
                end_date=end_date or "",
            )
        else:
            df = pro.daily(
                ts_code=ts_code,
                start_date=start_date or "",
                end_date=end_date or "",
            )

        df = df.sort_values("trade_date").reset_index(drop=True)
        return df

    def get_financial_report(
        self,
        ts_code: str,
        report_type: str = "income",
        period: Optional[str] = None,
    ) -> pd.DataFrame:
        pro = self._ensure_pro()
        logger.info(f"[Tushare] 获取财务报表: {ts_code}, type={report_type}")

        api_map = {
            "income": pro.income,
            "balance": pro.balancesheet,
            "cashflow": pro.cashflow,
        }
        api_func = api_map.get(report_type)
        if not api_func:
            return pd.DataFrame()

        df = api_func(ts_code=ts_code, period=period or "")
        return df

    def get_financial_indicator(
        self,
        ts_code: str,
        period: Optional[str] = None,
    ) -> pd.DataFrame:
        pro = self._ensure_pro()
        logger.info(f"[Tushare] 获取财务指标: {ts_code}")

        df = pro.fina_indicator(ts_code=ts_code, period=period or "")
        return df

    def get_stock_news(self, ts_code: str, limit: int = 20) -> pd.DataFrame:
        logger.info(f"[Tushare] 获取新闻: {ts_code}（Tushare 暂无新闻接口，返回空）")
        return pd.DataFrame()

    def get_stock_announcement(self, ts_code: str, limit: int = 20) -> pd.DataFrame:
        pro = self._ensure_pro()
        logger.info(f"[Tushare] 获取公告: {ts_code}")

        try:
            df = pro.anns(
                ts_code=ts_code,
                fields="ts_code,ann_date,title,ann_type",
            )
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.head(limit)
            return df
        except Exception as e:
            logger.warning(f"[Tushare] 获取公告失败: {e}")
            return pd.DataFrame()

    def get_realtime_quote(self, ts_code: str) -> pd.DataFrame:
        logger.info(f"[Tushare] 实时行情: {ts_code}（Tushare 实时行情需另接行情源，返回空）")
        return pd.DataFrame()

