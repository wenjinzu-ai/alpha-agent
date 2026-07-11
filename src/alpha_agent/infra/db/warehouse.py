from typing import List, Optional, Dict, Any
from datetime import datetime
import pandas as pd

from alpha_agent.infra.db.database import SessionLocal, init_db, check_db_connection
from alpha_agent.infra.db.models import (
    Stock,
    DailyKline,
    Etf,
    EtfDailyKline,
    DataSyncStatus,
)
from alpha_agent.utils.logger import logger


class DataWarehouse:
    def __init__(self):
        self._enabled = False
        self._init_done = False

    def _ensure_init(self):
        if self._init_done:
            return
        self._enabled = check_db_connection()
        if self._enabled:
            try:
                init_db()
            except Exception as e:
                logger.warning(f"[warehouse] 数据库初始化失败: {e}")
                self._enabled = False
        self._init_done = True

    @property
    def enabled(self) -> bool:
        self._ensure_init()
        return self._enabled

    def save_stock_list(self, df: pd.DataFrame) -> int:
        self._ensure_init()
        if not self._enabled or df is None or df.empty:
            return 0

        count = 0
        try:
            with SessionLocal() as db:
                for _, row in df.iterrows():
                    ts_code = str(row.get("ts_code", ""))
                    if not ts_code:
                        continue
                    existing = db.query(Stock).filter(Stock.ts_code == ts_code).first()
                    if existing:
                        existing.symbol = str(row.get("symbol", existing.symbol))
                        existing.name = str(row.get("name", existing.name))
                        existing.area = str(row.get("area", existing.area))
                        existing.industry = str(row.get("industry", existing.industry))
                        existing.market = str(row.get("market", existing.market))
                        existing.list_date = str(row.get("list_date", existing.list_date))
                        existing.is_active = True
                    else:
                        record = Stock(
                            ts_code=ts_code,
                            symbol=str(row.get("symbol", "")),
                            name=str(row.get("name", "")),
                            area=str(row.get("area", "")),
                            industry=str(row.get("industry", "")),
                            market=str(row.get("market", "")),
                            list_date=str(row.get("list_date", "")),
                            is_active=True,
                        )
                        db.add(record)
                    count += 1
                db.commit()
            logger.info(f"[warehouse] 保存股票列表: {count} 只")
            return count
        except Exception as e:
            logger.error(f"[warehouse] 保存股票列表失败: {e}")
            return 0

    def get_stock_list(self, market: Optional[str] = None, ts_code: Optional[str] = None) -> pd.DataFrame:
        self._ensure_init()
        if not self._enabled:
            return pd.DataFrame()

        try:
            with SessionLocal() as db:
                q = db.query(Stock).filter(Stock.is_active == True)
                if market:
                    q = q.filter(Stock.market == market)
                if ts_code:
                    q = q.filter(Stock.ts_code == ts_code)
                records = q.all()
                data = [
                    {
                        "ts_code": r.ts_code,
                        "symbol": r.symbol,
                        "name": r.name,
                        "area": r.area,
                        "industry": r.industry,
                        "market": r.market,
                        "list_date": r.list_date,
                    }
                    for r in records
                ]
                return pd.DataFrame(data)
        except Exception as e:
            logger.error(f"[warehouse] 查询股票列表失败: {e}")
            return pd.DataFrame()

    def save_daily_kline(self, ts_code: str, df: pd.DataFrame) -> int:
        self._ensure_init()
        if not self._enabled or df is None or df.empty:
            return 0

        count = 0
        try:
            with SessionLocal() as db:
                for _, row in df.iterrows():
                    trade_date = str(row.get("trade_date", ""))
                    if not trade_date:
                        continue
                    existing = db.query(DailyKline).filter(
                        DailyKline.ts_code == ts_code,
                        DailyKline.trade_date == trade_date,
                    ).first()
                    if existing:
                        existing.open = float(row.get("open", existing.open))
                        existing.high = float(row.get("high", existing.high))
                        existing.low = float(row.get("low", existing.low))
                        existing.close = float(row.get("close", existing.close))
                        existing.pre_close = float(row.get("pre_close", existing.pre_close))
                        existing.change = float(row.get("change", existing.change))
                        existing.pct_chg = float(row.get("pct_chg", existing.pct_chg))
                        existing.vol = float(row.get("vol", existing.vol))
                        existing.amount = float(row.get("amount", existing.amount))
                    else:
                        record = DailyKline(
                            ts_code=ts_code,
                            trade_date=trade_date,
                            open=float(row.get("open", 0)),
                            high=float(row.get("high", 0)),
                            low=float(row.get("low", 0)),
                            close=float(row.get("close", 0)),
                            pre_close=float(row.get("pre_close", 0)),
                            change=float(row.get("change", 0)),
                            pct_chg=float(row.get("pct_chg", 0)),
                            vol=float(row.get("vol", 0)),
                            amount=float(row.get("amount", 0)),
                        )
                        db.add(record)
                    count += 1
                db.commit()
            return count
        except Exception as e:
            logger.error(f"[warehouse] 保存K线失败 {ts_code}: {e}")
            return 0

    def get_daily_kline(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        self._ensure_init()
        if not self._enabled:
            return pd.DataFrame()

        try:
            with SessionLocal() as db:
                q = db.query(DailyKline).filter(DailyKline.ts_code == ts_code)
                if start_date:
                    q = q.filter(DailyKline.trade_date >= start_date)
                if end_date:
                    q = q.filter(DailyKline.trade_date <= end_date)
                q = q.order_by(DailyKline.trade_date.asc())
                records = q.all()
                data = [
                    {
                        "ts_code": r.ts_code,
                        "trade_date": r.trade_date,
                        "open": float(r.open),
                        "high": float(r.high),
                        "low": float(r.low),
                        "close": float(r.close),
                        "pre_close": float(r.pre_close),
                        "change": float(r.change),
                        "pct_chg": float(r.pct_chg),
                        "vol": float(r.vol),
                        "amount": float(r.amount),
                    }
                    for r in records
                ]
                return pd.DataFrame(data)
        except Exception as e:
            logger.error(f"[warehouse] 查询K线失败 {ts_code}: {e}")
            return pd.DataFrame()

    def get_latest_kline_date(self, ts_code: str) -> Optional[str]:
        self._ensure_init()
        if not self._enabled:
            return None

        try:
            with SessionLocal() as db:
                record = db.query(DailyKline).filter(
                    DailyKline.ts_code == ts_code
                ).order_by(DailyKline.trade_date.desc()).first()
                return record.trade_date if record else None
        except Exception as e:
            logger.error(f"[warehouse] 查询最新K线日期失败 {ts_code}: {e}")
            return None

    def save_etf_list(self, df: pd.DataFrame) -> int:
        self._ensure_init()
        if not self._enabled or df is None or df.empty:
            return 0

        count = 0
        try:
            with SessionLocal() as db:
                for _, row in df.iterrows():
                    ts_code = str(row.get("ts_code", ""))
                    if not ts_code:
                        continue
                    existing = db.query(Etf).filter(Etf.ts_code == ts_code).first()
                    if existing:
                        existing.symbol = str(row.get("symbol", existing.symbol))
                        existing.name = str(row.get("name", existing.name))
                        existing.etf_type = str(row.get("etf_type", existing.etf_type))
                        existing.issuer = str(row.get("issuer", existing.issuer))
                        existing.index_code = str(row.get("index_code", existing.index_code))
                        existing.index_name = str(row.get("index_name", existing.index_name))
                        existing.list_date = str(row.get("list_date", existing.list_date))
                        existing.market = str(row.get("market", existing.market))
                        existing.is_active = True
                    else:
                        record = Etf(
                            ts_code=ts_code,
                            symbol=str(row.get("symbol", "")),
                            name=str(row.get("name", "")),
                            etf_type=str(row.get("etf_type", "")),
                            issuer=str(row.get("issuer", "")),
                            index_code=str(row.get("index_code", "")),
                            index_name=str(row.get("index_name", "")),
                            list_date=str(row.get("list_date", "")),
                            market=str(row.get("market", "")),
                            is_active=True,
                        )
                        db.add(record)
                    count += 1
                db.commit()
            logger.info(f"[warehouse] 保存ETF列表: {count} 只")
            return count
        except Exception as e:
            logger.error(f"[warehouse] 保存ETF列表失败: {e}")
            return 0

    def get_etf_list(self, market: Optional[str] = None, ts_code: Optional[str] = None) -> pd.DataFrame:
        self._ensure_init()
        if not self._enabled:
            return pd.DataFrame()

        try:
            with SessionLocal() as db:
                q = db.query(Etf).filter(Etf.is_active == True)
                if market:
                    q = q.filter(Etf.market == market)
                if ts_code:
                    q = q.filter(Etf.ts_code == ts_code)
                records = q.all()
                data = [
                    {
                        "ts_code": r.ts_code,
                        "symbol": r.symbol,
                        "name": r.name,
                        "etf_type": r.etf_type,
                        "issuer": r.issuer,
                        "index_code": r.index_code,
                        "index_name": r.index_name,
                        "list_date": r.list_date,
                        "market": r.market,
                    }
                    for r in records
                ]
                return pd.DataFrame(data)
        except Exception as e:
            logger.error(f"[warehouse] 查询ETF列表失败: {e}")
            return pd.DataFrame()

    def save_etf_daily_kline(self, ts_code: str, df: pd.DataFrame) -> int:
        self._ensure_init()
        if not self._enabled or df is None or df.empty:
            return 0

        count = 0
        try:
            with SessionLocal() as db:
                for _, row in df.iterrows():
                    trade_date = str(row.get("trade_date", ""))
                    if not trade_date:
                        continue
                    existing = db.query(EtfDailyKline).filter(
                        EtfDailyKline.ts_code == ts_code,
                        EtfDailyKline.trade_date == trade_date,
                    ).first()
                    if existing:
                        existing.open = float(row.get("open", existing.open))
                        existing.high = float(row.get("high", existing.high))
                        existing.low = float(row.get("low", existing.low))
                        existing.close = float(row.get("close", existing.close))
                        existing.pre_close = float(row.get("pre_close", existing.pre_close))
                        existing.change = float(row.get("change", existing.change))
                        existing.pct_chg = float(row.get("pct_chg", existing.pct_chg))
                        existing.vol = float(row.get("vol", existing.vol))
                        existing.amount = float(row.get("amount", existing.amount))
                    else:
                        record = EtfDailyKline(
                            ts_code=ts_code,
                            trade_date=trade_date,
                            open=float(row.get("open", 0)),
                            high=float(row.get("high", 0)),
                            low=float(row.get("low", 0)),
                            close=float(row.get("close", 0)),
                            pre_close=float(row.get("pre_close", 0)),
                            change=float(row.get("change", 0)),
                            pct_chg=float(row.get("pct_chg", 0)),
                            vol=float(row.get("vol", 0)),
                            amount=float(row.get("amount", 0)),
                        )
                        db.add(record)
                    count += 1
                db.commit()
            return count
        except Exception as e:
            logger.error(f"[warehouse] 保存ETF K线失败 {ts_code}: {e}")
            return 0

    def get_etf_daily_kline(
        self,
        ts_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> pd.DataFrame:
        self._ensure_init()
        if not self._enabled:
            return pd.DataFrame()

        try:
            with SessionLocal() as db:
                q = db.query(EtfDailyKline).filter(EtfDailyKline.ts_code == ts_code)
                if start_date:
                    q = q.filter(EtfDailyKline.trade_date >= start_date)
                if end_date:
                    q = q.filter(EtfDailyKline.trade_date <= end_date)
                q = q.order_by(EtfDailyKline.trade_date.asc())
                records = q.all()
                data = [
                    {
                        "ts_code": r.ts_code,
                        "trade_date": r.trade_date,
                        "open": float(r.open),
                        "high": float(r.high),
                        "low": float(r.low),
                        "close": float(r.close),
                        "pre_close": float(r.pre_close),
                        "change": float(r.change),
                        "pct_chg": float(r.pct_chg),
                        "vol": float(r.vol),
                        "amount": float(r.amount),
                    }
                    for r in records
                ]
                return pd.DataFrame(data)
        except Exception as e:
            logger.error(f"[warehouse] 查询ETF K线失败 {ts_code}: {e}")
            return pd.DataFrame()

    def get_etf_latest_kline_date(self, ts_code: str) -> Optional[str]:
        self._ensure_init()
        if not self._enabled:
            return None

        try:
            with SessionLocal() as db:
                record = db.query(EtfDailyKline).filter(
                    EtfDailyKline.ts_code == ts_code
                ).order_by(EtfDailyKline.trade_date.desc()).first()
                return record.trade_date if record else None
        except Exception as e:
            logger.error(f"[warehouse] 查询ETF最新K线日期失败 {ts_code}: {e}")
            return None

    def save_sync_status(self, sync_type: str, **kwargs) -> Optional[int]:
        self._ensure_init()
        if not self._enabled:
            return None

        try:
            with SessionLocal() as db:
                record = DataSyncStatus(
                    sync_type=sync_type,
                    status=kwargs.get("status", "running"),
                    last_sync_date=kwargs.get("last_sync_date", ""),
                    total_count=kwargs.get("total_count", 0),
                    success_count=kwargs.get("success_count", 0),
                    failed_count=kwargs.get("failed_count", 0),
                    error_msg=kwargs.get("error_msg", ""),
                    started_at=kwargs.get("started_at", ""),
                    finished_at=kwargs.get("finished_at", ""),
                )
                db.add(record)
                db.commit()
                db.refresh(record)
                return record.id
        except Exception as e:
            logger.error(f"[warehouse] 保存同步状态失败: {e}")
            return None

    def update_sync_status(self, sync_id: int, **kwargs):
        self._ensure_init()
        if not self._enabled:
            return

        try:
            with SessionLocal() as db:
                record = db.query(DataSyncStatus).filter(DataSyncStatus.id == sync_id).first()
                if record:
                    for key, value in kwargs.items():
                        if hasattr(record, key):
                            setattr(record, key, value)
                    db.commit()
        except Exception as e:
            logger.error(f"[warehouse] 更新同步状态失败: {e}")

    def get_last_sync_status(self, sync_type: str) -> Optional[dict]:
        self._ensure_init()
        if not self._enabled:
            return None

        try:
            with SessionLocal() as db:
                record = db.query(DataSyncStatus).filter(
                    DataSyncStatus.sync_type == sync_type
                ).order_by(DataSyncStatus.created_at.desc()).first()
                if record:
                    return {
                        "id": record.id,
                        "sync_type": record.sync_type,
                        "status": record.status,
                        "last_sync_date": record.last_sync_date,
                        "total_count": record.total_count,
                        "success_count": record.success_count,
                        "failed_count": record.failed_count,
                        "error_msg": record.error_msg,
                        "started_at": record.started_at,
                        "finished_at": record.finished_at,
                        "created_at": record.created_at.isoformat() if record.created_at else "",
                    }
                return None
        except Exception as e:
            logger.error(f"[warehouse] 查询同步状态失败: {e}")
            return None

    def save_financial_data(self, ts_code: str, records: List[dict]) -> int:
        self._ensure_init()
        if not self._enabled:
            return 0
        try:
            from alpha_agent.infra.db.models import FinancialReport
            count = 0
            with SessionLocal() as db:
                for r in records:
                    existing = db.query(FinancialReport).filter(
                        FinancialReport.ts_code == ts_code,
                        FinancialReport.end_date == r.get("end_date", ""),
                        FinancialReport.report_type == r.get("report_type", ""),
                    ).first()
                    if existing:
                        for k, v in r.items():
                            if hasattr(existing, k):
                                setattr(existing, k, v)
                    else:
                        db.add(FinancialReport(ts_code=ts_code, **r))
                        count += 1
                db.commit()
            return count
        except Exception as e:
            logger.error(f"[warehouse] 保存财务数据失败: {e}")
            return 0

    def save_money_flow(self, records: List[dict]) -> int:
        self._ensure_init()
        if not self._enabled:
            return 0
        try:
            from alpha_agent.infra.db.models import MoneyFlow
            count = 0
            with SessionLocal() as db:
                for r in records:
                    existing = db.query(MoneyFlow).filter(
                        MoneyFlow.ts_code == r.get("ts_code", ""),
                        MoneyFlow.trade_date == r.get("trade_date", ""),
                        MoneyFlow.flow_type == r.get("flow_type", "stock"),
                    ).first()
                    if existing:
                        for k, v in r.items():
                            if hasattr(existing, k):
                                setattr(existing, k, v)
                    else:
                        db.add(MoneyFlow(**r))
                        count += 1
                db.commit()
            return count
        except Exception as e:
            logger.error(f"[warehouse] 保存资金流向失败: {e}")
            return 0

    def save_industry_aggregation(self, records: List[dict]) -> int:
        self._ensure_init()
        if not self._enabled:
            return 0
        try:
            from alpha_agent.infra.db.models import IndustryAggregation
            count = 0
            with SessionLocal() as db:
                for r in records:
                    existing = db.query(IndustryAggregation).filter(
                        IndustryAggregation.industry == r.get("industry", ""),
                        IndustryAggregation.trade_date == r.get("trade_date", ""),
                    ).first()
                    if existing:
                        for k, v in r.items():
                            if hasattr(existing, k):
                                setattr(existing, k, v)
                    else:
                        db.add(IndustryAggregation(**r))
                        count += 1
                db.commit()
            return count
        except Exception as e:
            logger.error(f"[warehouse] 保存行业聚合数据失败: {e}")
            return 0

    def save_macro_data(self, records: List[dict]) -> int:
        self._ensure_init()
        if not self._enabled:
            return 0
        try:
            from alpha_agent.infra.db.models import MacroData
            count = 0
            with SessionLocal() as db:
                for r in records:
                    existing = db.query(MacroData).filter(
                        MacroData.indicator == r.get("indicator", ""),
                        MacroData.period == r.get("period", ""),
                    ).first()
                    if existing:
                        existing.value = r.get("value", 0)
                        existing.unit = r.get("unit", "")
                        existing.source = r.get("source", "akshare")
                    else:
                        db.add(MacroData(**r))
                        count += 1
                db.commit()
            return count
        except Exception as e:
            logger.error(f"[warehouse] 保存宏观数据失败: {e}")
            return 0

    def save_sentiment_data(self, records: List[dict]) -> int:
        self._ensure_init()
        if not self._enabled:
            return 0
        try:
            from alpha_agent.infra.db.models import SentimentData
            count = 0
            with SessionLocal() as db:
                for r in records:
                    existing = db.query(SentimentData).filter(
                        SentimentData.ts_code == r.get("ts_code", ""),
                        SentimentData.trade_date == r.get("trade_date", ""),
                        SentimentData.sentiment_type == r.get("sentiment_type", "market"),
                    ).first()
                    if existing:
                        for k, v in r.items():
                            if hasattr(existing, k):
                                setattr(existing, k, v)
                    else:
                        db.add(SentimentData(**r))
                        count += 1
                db.commit()
            return count
        except Exception as e:
            logger.error(f"[warehouse] 保存舆情数据失败: {e}")
            return 0

    def save_stock_factors(self, records: List[dict]) -> int:
        self._ensure_init()
        if not self._enabled:
            return 0
        try:
            from alpha_agent.infra.db.models import StockFactor
            count = 0
            with SessionLocal() as db:
                for r in records:
                    existing = db.query(StockFactor).filter(
                        StockFactor.ts_code == r.get("ts_code", ""),
                        StockFactor.trade_date == r.get("trade_date", ""),
                    ).first()
                    if existing:
                        for k, v in r.items():
                            if hasattr(existing, k):
                                setattr(existing, k, v)
                    else:
                        db.add(StockFactor(**r))
                        count += 1
                db.commit()
            return count
        except Exception as e:
            logger.error(f"[warehouse] 保存因子数据失败: {e}")
            return 0

    def get_money_flow(self, ts_code: Optional[str] = None, trade_date: Optional[str] = None, flow_type: str = "stock") -> pd.DataFrame:
        self._ensure_init()
        if not self._enabled:
            return pd.DataFrame()
        try:
            from alpha_agent.infra.db.models import MoneyFlow
            with SessionLocal() as db:
                q = db.query(MoneyFlow)
                if ts_code:
                    q = q.filter(MoneyFlow.ts_code == ts_code)
                if trade_date:
                    q = q.filter(MoneyFlow.trade_date == trade_date)
                q = q.filter(MoneyFlow.flow_type == flow_type)
                return pd.read_sql(q.statement, db.bind)
        except Exception as e:
            logger.error(f"[warehouse] 查询资金流向失败: {e}")
            return pd.DataFrame()

    def get_industry_aggregation(self, industry: Optional[str] = None, trade_date: Optional[str] = None) -> pd.DataFrame:
        self._ensure_init()
        if not self._enabled:
            return pd.DataFrame()
        try:
            from alpha_agent.infra.db.models import IndustryAggregation
            with SessionLocal() as db:
                q = db.query(IndustryAggregation)
                if industry:
                    q = q.filter(IndustryAggregation.industry == industry)
                if trade_date:
                    q = q.filter(IndustryAggregation.trade_date == trade_date)
                return pd.read_sql(q.statement, db.bind)
        except Exception as e:
            logger.error(f"[warehouse] 查询行业聚合数据失败: {e}")
            return pd.DataFrame()

    def get_macro_data(self, indicator: Optional[str] = None) -> pd.DataFrame:
        self._ensure_init()
        if not self._enabled:
            return pd.DataFrame()
        try:
            from alpha_agent.infra.db.models import MacroData
            with SessionLocal() as db:
                q = db.query(MacroData)
                if indicator:
                    q = q.filter(MacroData.indicator == indicator)
                return pd.read_sql(q.statement, db.bind)
        except Exception as e:
            logger.error(f"[warehouse] 查询宏观数据失败: {e}")
            return pd.DataFrame()

    def get_stock_factors(self, ts_code: Optional[str] = None, trade_date: Optional[str] = None) -> pd.DataFrame:
        self._ensure_init()
        if not self._enabled:
            return pd.DataFrame()
        try:
            from alpha_agent.infra.db.models import StockFactor
            with SessionLocal() as db:
                q = db.query(StockFactor)
                if ts_code:
                    q = q.filter(StockFactor.ts_code == ts_code)
                if trade_date:
                    q = q.filter(StockFactor.trade_date == trade_date)
                return pd.read_sql(q.statement, db.bind)
        except Exception as e:
            logger.error(f"[warehouse] 查询因子数据失败: {e}")
            return pd.DataFrame()

    def get_sentiment_data(self, ts_code: Optional[str] = None, trade_date: Optional[str] = None, sentiment_type: str = "market") -> pd.DataFrame:
        self._ensure_init()
        if not self._enabled:
            return pd.DataFrame()
        try:
            from alpha_agent.infra.db.models import SentimentData
            with SessionLocal() as db:
                q = db.query(SentimentData)
                if ts_code:
                    q = q.filter(SentimentData.ts_code == ts_code)
                if trade_date:
                    q = q.filter(SentimentData.trade_date == trade_date)
                q = q.filter(SentimentData.sentiment_type == sentiment_type)
                return pd.read_sql(q.statement, db.bind)
        except Exception as e:
            logger.error(f"[warehouse] 查询舆情数据失败: {e}")
            return pd.DataFrame()


_warehouse: Optional[DataWarehouse] = None


def get_data_warehouse() -> DataWarehouse:
    global _warehouse
    if _warehouse is None:
        _warehouse = DataWarehouse()
    return _warehouse