import asyncio
import threading
from datetime import timedelta
from typing import Optional
import pandas as pd

from alpha_agent.domain.market.providers.base import DataProvider
from alpha_agent.domain.market.providers.akshare_provider import AkShareProvider
from alpha_agent.domain.market.providers.tushare_provider import TushareProvider
from alpha_agent.domain.market.providers.baostock_provider import BaoStockProvider
from alpha_agent.config import settings
from alpha_agent.utils.logger import logger

try:
    from alpha_agent.infra.cache import get_cache
except ImportError:
    get_cache = None

try:
    from alpha_agent.infra.db.warehouse import get_data_warehouse
except ImportError:
    get_data_warehouse = None


_CACHE_TTL = {
    "stock_basic": timedelta(hours=24),
    "kline_daily_qfq": timedelta(hours=12),
    "kline_daily_hfq": timedelta(hours=12),
    "kline_daily_none": timedelta(hours=12),
    "financial_income": timedelta(hours=168),
    "financial_balance": timedelta(hours=168),
    "financial_cashflow": timedelta(hours=168),
    "financial_indicator": timedelta(hours=168),
    "news": timedelta(hours=2),
    "announcement": timedelta(hours=6),
}


class DataService:
    _instance: Optional["DataService"] = None
    _lock = threading.Lock()

    def __init__(self, primary: str = "akshare"):
        self._providers: dict[str, DataProvider] = {}
        self._primary = primary
        self._cache = None
        self._warehouse = None
        self._init_providers()
        self._init_cache()
        self._init_warehouse()

    @classmethod
    def get_instance(cls) -> "DataService":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _init_providers(self):
        self._providers["akshare"] = AkShareProvider()

        if settings.tushare_token:
            try:
                self._providers["tushare"] = TushareProvider()
                logger.info("Tushare provider 已初始化")
            except Exception as e:
                logger.warning(f"Tushare provider 初始化失败: {e}")

        try:
            self._providers["baostock"] = BaoStockProvider()
            logger.info("BaoStock provider 已初始化")
        except Exception as e:
            logger.warning(f"BaoStock provider 初始化失败: {e}")

        logger.info(
            f"DataService 初始化完成，可用数据源: {list(self._providers.keys())}, "
            f"主数据源: {self._primary}"
        )

    def _init_cache(self):
        if get_cache is None:
            return
        try:
            self._cache = get_cache()
            if self._cache.enabled:
                logger.info("DataService: Redis 缓存已启用")
            else:
                logger.info("DataService: Redis 缓存未启用")
        except Exception as e:
            logger.warning(f"DataService: 缓存初始化失败: {e}")
            self._cache = None

    def _init_warehouse(self):
        if get_data_warehouse is None:
            return
        try:
            self._warehouse = get_data_warehouse()
            if self._warehouse.enabled:
                logger.info("DataService: 本地数据仓库已启用")
            else:
                logger.info("DataService: 本地数据仓库未启用")
        except Exception as e:
            logger.warning(f"DataService: 数据仓库初始化失败: {e}")
            self._warehouse = None

    def get_provider(self, name: Optional[str] = None) -> DataProvider:
        name = name or self._primary
        if name not in self._providers:
            raise ValueError(f"Provider not found: {name}. Available: {list(self._providers.keys())}")
        return self._providers[name]

    def _cache_get_df(self, key: str) -> Optional[pd.DataFrame]:
        if not self._cache or not self._cache.enabled:
            return None
        return self._cache.get_df(key)

    def _cache_set_df(self, key: str, df: pd.DataFrame, ttl_key: str):
        if not self._cache or not self._cache.enabled or df is None or df.empty:
            return
        ttl = _CACHE_TTL.get(ttl_key, timedelta(hours=12))
        self._cache.set_df(key, df, ex=ttl)

    def _cache_key(self, prefix: str, *parts) -> str:
        key_parts = [prefix] + [str(p) for p in parts if p is not None]
        return "ia:" + ":".join(key_parts)

    def get_stock_basic(
        self,
        ts_code: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> pd.DataFrame:
        prov_name = provider or self._primary
        cache_key = self._cache_key("stock_basic", prov_name, ts_code or "all")

        cached = self._cache_get_df(cache_key)
        if cached is not None:
            logger.debug(f"[Cache hit] stock_basic {ts_code}")
            return cached

        if self._warehouse and self._warehouse.enabled:
            wh_df = self._warehouse.get_stock_list(ts_code=ts_code)
            if not wh_df.empty:
                logger.debug(f"[Warehouse hit] stock_basic {ts_code}")
                self._cache_set_df(cache_key, wh_df, "stock_basic")
                return wh_df

        p = self.get_provider(provider)
        df = p.get_stock_basic(ts_code)

        if self._warehouse and self._warehouse.enabled and not ts_code:
            self._warehouse.save_stock_list(df)

        self._cache_set_df(cache_key, df, "stock_basic")
        return df

    def get_daily_kline(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: str = "daily",
        adjust: str = "qfq",
        provider: Optional[str] = None,
    ) -> pd.DataFrame:
        prov_name = provider or self._primary
        cache_key = self._cache_key("kline", prov_name, ts_code, period, adjust)

        cached = self._cache_get_df(cache_key)
        if cached is not None:
            if start_date:
                cached = cached[cached["trade_date"] >= start_date]
            if end_date:
                cached = cached[cached["trade_date"] <= end_date]
            logger.debug(f"[Cache hit] kline {ts_code} {adjust}")
            return cached.reset_index(drop=True)

        if self._warehouse and self._warehouse.enabled and adjust == "qfq":
            wh_df = self._warehouse.get_daily_kline(ts_code, start_date, end_date)
            if not wh_df.empty:
                logger.debug(f"[Warehouse hit] kline {ts_code}")
                if not start_date and not end_date:
                    self._cache_set_df(cache_key, wh_df, f"kline_{period}_{adjust}")
                return wh_df

        p = self.get_provider(provider)
        df = p.get_daily_kline(ts_code, start_date, end_date, period, adjust)

        if self._warehouse and self._warehouse.enabled and adjust == "qfq":
            self._warehouse.save_daily_kline(ts_code, df)

        if not start_date and not end_date:
            ttl_key = f"kline_{period}_{adjust}"
            self._cache_set_df(cache_key, df, ttl_key)
        return df

    def get_financial_report(
        self,
        ts_code: str,
        report_type: str = "income",
        period: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> pd.DataFrame:
        prov_name = provider or self._primary
        cache_key = self._cache_key("financial", prov_name, ts_code, report_type, period or "all")

        cached = self._cache_get_df(cache_key)
        if cached is not None:
            logger.debug(f"[Cache hit] financial {ts_code} {report_type}")
            return cached

        p = self.get_provider(provider)
        df = p.get_financial_report(ts_code, report_type, period)
        ttl_key = f"financial_{report_type}"
        self._cache_set_df(cache_key, df, ttl_key)
        return df

    def get_financial_indicator(
        self,
        ts_code: str,
        period: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> pd.DataFrame:
        prov_name = provider or self._primary
        cache_key = self._cache_key("findicator", prov_name, ts_code, period or "all")

        cached = self._cache_get_df(cache_key)
        if cached is not None:
            logger.debug(f"[Cache hit] findicator {ts_code}")
            return cached

        p = self.get_provider(provider)
        df = p.get_financial_indicator(ts_code, period)
        self._cache_set_df(cache_key, df, "financial_indicator")
        return df

    async def get_stock_basic_async(
        self,
        ts_code: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> pd.DataFrame:
        return await asyncio.to_thread(self.get_stock_basic, ts_code, provider)

    async def get_daily_kline_async(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        period: str = "daily",
        adjust: str = "qfq",
        provider: Optional[str] = None,
    ) -> pd.DataFrame:
        return await asyncio.to_thread(
            self.get_daily_kline, ts_code, start_date, end_date, period, adjust, provider
        )

    async def get_financial_report_async(
        self,
        ts_code: str,
        report_type: str = "income",
        period: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> pd.DataFrame:
        return await asyncio.to_thread(
            self.get_financial_report, ts_code, report_type, period, provider
        )

    async def get_financial_indicator_async(
        self,
        ts_code: str,
        period: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> pd.DataFrame:
        return await asyncio.to_thread(self.get_financial_indicator, ts_code, period, provider)

    @property
    def available_providers(self) -> list[str]:
        return list(self._providers.keys())

    @property
    def primary_provider(self) -> str:
        return self._primary

    @property
    def cache_enabled(self) -> bool:
        return self._cache is not None and self._cache.enabled

    def get_stock_news(
        self,
        ts_code: str,
        limit: int = 20,
        provider: Optional[str] = None,
    ) -> pd.DataFrame:
        prov_name = provider or self._primary
        p = self.get_provider(prov_name)
        cache_key = self._cache_key("news", prov_name, ts_code, str(limit))
        cached = self._cache_get_df(cache_key)
        if cached is not None:
            return cached
        df = p.get_stock_news(ts_code, limit)
        if df is not None and not df.empty:
            self._cache_set_df(cache_key, df, "news")
        return df

    def get_stock_announcement(
        self,
        ts_code: str,
        limit: int = 20,
        provider: Optional[str] = None,
    ) -> pd.DataFrame:
        prov_name = provider or self._primary
        p = self.get_provider(prov_name)
        cache_key = self._cache_key("announcement", prov_name, ts_code, str(limit))
        cached = self._cache_get_df(cache_key)
        if cached is not None:
            return cached
        df = p.get_stock_announcement(ts_code, limit)
        if df is not None and not df.empty:
            self._cache_set_df(cache_key, df, "announcement")
        return df

    def get_realtime_quote(
        self,
        ts_code: str,
        provider: Optional[str] = None,
    ) -> pd.DataFrame:
        prov_name = provider or self._primary
        p = self.get_provider(prov_name)
        return p.get_realtime_quote(ts_code)


def get_data_service() -> DataService:
    return DataService.get_instance()