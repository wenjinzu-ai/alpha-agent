from typing import Optional, Callable
from datetime import datetime
import time
import pandas as pd

from alpha_agent.domain.market.providers.akshare_provider import AkShareProvider
from alpha_agent.infra.db.warehouse import get_data_warehouse
from alpha_agent.utils.logger import logger


class DataSyncService:
    def __init__(self):
        self.provider = AkShareProvider()
        self.warehouse = get_data_warehouse()

    def sync_stock_list(self) -> dict:
        sync_id = None
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            if not self.warehouse.enabled:
                logger.warning("[sync] 数据仓库未启用，跳过股票列表同步")
                return {"status": "skipped", "reason": "warehouse_disabled"}

            sync_id = self.warehouse.save_sync_status(
                sync_type="stock_list",
                status="running",
                started_at=started,
            )

            logger.info("[sync] 开始同步股票列表...")
            df = self.provider.get_stock_basic()
            if df.empty:
                self.warehouse.update_sync_status(
                    sync_id,
                    status="failed",
                    error_msg="获取股票列表为空",
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
                return {"status": "failed", "error": "empty_data"}

            count = self.warehouse.save_stock_list(df)
            self.warehouse.update_sync_status(
                sync_id,
                status="success",
                total_count=count,
                success_count=count,
                last_sync_date=datetime.now().strftime("%Y%m%d"),
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            logger.info(f"[sync] 股票列表同步完成: {count} 只")
            return {"status": "success", "count": count}

        except Exception as e:
            logger.error(f"[sync] 股票列表同步失败: {e}")
            if sync_id:
                self.warehouse.update_sync_status(
                    sync_id,
                    status="failed",
                    error_msg=str(e),
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            return {"status": "failed", "error": str(e)}

    def sync_stock_kline(
        self,
        ts_code: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        sync_id = None
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            if not self.warehouse.enabled:
                return {"status": "skipped", "reason": "warehouse_disabled"}

            sync_id = self.warehouse.save_sync_status(
                sync_type="stock_kline",
                status="running",
                started_at=started,
            )

            stock_df = self.warehouse.get_stock_list()
            if ts_code:
                stock_df = stock_df[stock_df["ts_code"] == ts_code]
            if stock_df.empty:
                self.warehouse.update_sync_status(
                    sync_id,
                    status="failed",
                    error_msg="股票列表为空，请先同步股票列表",
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
                return {"status": "failed", "error": "no_stocks"}

            total = len(stock_df)
            success = 0
            failed = 0
            logger.info(f"[sync] 开始同步 {total} 只股票K线数据...")

            for idx, row in stock_df.iterrows():
                code = row["ts_code"]
                name = row["name"]
                try:
                    latest = self.warehouse.get_latest_kline_date(code)
                    actual_start = start_date
                    if latest and not start_date:
                        actual_start = latest

                    df = self.provider.get_daily_kline(
                        ts_code=code,
                        start_date=actual_start,
                        end_date=end_date,
                        adjust="qfq",
                    )
                    if not df.empty:
                        self.warehouse.save_daily_kline(code, df)
                    success += 1

                    if progress_cb:
                        progress_cb(idx + 1, total, code)

                    if (idx + 1) % 50 == 0:
                        logger.info(f"[sync] K线进度: {idx+1}/{total}, 成功: {success}, 失败: {failed}")

                    time.sleep(0.3)

                except Exception as e:
                    failed += 1
                    logger.warning(f"[sync] 同步K线失败 {code}({name}): {e}")

            self.warehouse.update_sync_status(
                sync_id,
                status="success",
                total_count=total,
                success_count=success,
                failed_count=failed,
                last_sync_date=datetime.now().strftime("%Y%m%d"),
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            logger.info(f"[sync] 股票K线同步完成: 总数{total}, 成功{success}, 失败{failed}")
            return {
                "status": "success",
                "total": total,
                "success": success,
                "failed": failed,
            }

        except Exception as e:
            logger.error(f"[sync] 股票K线同步失败: {e}")
            if sync_id:
                self.warehouse.update_sync_status(
                    sync_id,
                    status="failed",
                    error_msg=str(e),
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            return {"status": "failed", "error": str(e)}

    def sync_etf_list(self) -> dict:
        sync_id = None
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            if not self.warehouse.enabled:
                return {"status": "skipped", "reason": "warehouse_disabled"}

            sync_id = self.warehouse.save_sync_status(
                sync_type="etf_list",
                status="running",
                started_at=started,
            )

            logger.info("[sync] 开始同步ETF列表...")
            df = self._get_etf_list_from_provider()
            if df.empty:
                self.warehouse.update_sync_status(
                    sync_id,
                    status="failed",
                    error_msg="获取ETF列表为空",
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
                return {"status": "failed", "error": "empty_data"}

            count = self.warehouse.save_etf_list(df)
            self.warehouse.update_sync_status(
                sync_id,
                status="success",
                total_count=count,
                success_count=count,
                last_sync_date=datetime.now().strftime("%Y%m%d"),
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            logger.info(f"[sync] ETF列表同步完成: {count} 只")
            return {"status": "success", "count": count}

        except Exception as e:
            logger.error(f"[sync] ETF列表同步失败: {e}")
            if sync_id:
                self.warehouse.update_sync_status(
                    sync_id,
                    status="failed",
                    error_msg=str(e),
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            return {"status": "failed", "error": str(e)}

    def _get_etf_list_from_provider(self):
        try:
            df = self.provider.get_etf_list()
            if df is None or df.empty:
                return pd.DataFrame()
            if "etf_type" not in df.columns:
                df["etf_type"] = ""
            if "issuer" not in df.columns:
                df["issuer"] = ""
            if "index_code" not in df.columns:
                df["index_code"] = ""
            if "index_name" not in df.columns:
                df["index_name"] = ""
            if "list_date" not in df.columns:
                df["list_date"] = ""
            return df
        except Exception as e:
            logger.warning(f"[sync] 获取ETF列表失败: {e}")
            return pd.DataFrame()

    def sync_etf_kline(
        self,
        ts_code: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        sync_id = None
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            if not self.warehouse.enabled:
                return {"status": "skipped", "reason": "warehouse_disabled"}

            sync_id = self.warehouse.save_sync_status(
                sync_type="etf_kline",
                status="running",
                started_at=started,
            )

            etf_df = self.warehouse.get_etf_list()
            if ts_code:
                etf_df = etf_df[etf_df["ts_code"] == ts_code]
            if etf_df.empty:
                self.warehouse.update_sync_status(
                    sync_id,
                    status="failed",
                    error_msg="ETF列表为空，请先同步ETF列表",
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
                return {"status": "failed", "error": "no_etfs"}

            total = len(etf_df)
            success = 0
            failed = 0
            logger.info(f"[sync] 开始同步 {total} 只ETF K线数据...")

            for idx, row in etf_df.iterrows():
                code = row["ts_code"]
                name = row["name"]
                try:
                    latest = self.warehouse.get_etf_latest_kline_date(code)
                    actual_start = start_date
                    if latest and not start_date:
                        actual_start = latest

                    df = self._get_etf_kline_from_provider(
                        ts_code=code,
                        start_date=actual_start,
                        end_date=end_date,
                    )
                    if not df.empty:
                        self.warehouse.save_etf_daily_kline(code, df)
                    success += 1

                    if progress_cb:
                        progress_cb(idx + 1, total, code)

                    if (idx + 1) % 50 == 0:
                        logger.info(f"[sync] ETF K线进度: {idx+1}/{total}, 成功: {success}, 失败: {failed}")

                    time.sleep(0.3)

                except Exception as e:
                    failed += 1
                    logger.warning(f"[sync] 同步ETF K线失败 {code}({name}): {e}")

            self.warehouse.update_sync_status(
                sync_id,
                status="success",
                total_count=total,
                success_count=success,
                failed_count=failed,
                last_sync_date=datetime.now().strftime("%Y%m%d"),
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            logger.info(f"[sync] ETF K线同步完成: 总数{total}, 成功{success}, 失败{failed}")
            return {
                "status": "success",
                "total": total,
                "success": success,
                "failed": failed,
            }

        except Exception as e:
            logger.error(f"[sync] ETF K线同步失败: {e}")
            if sync_id:
                self.warehouse.update_sync_status(
                    sync_id,
                    status="failed",
                    error_msg=str(e),
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            return {"status": "failed", "error": str(e)}

    def _get_etf_kline_from_provider(self, ts_code: str, start_date: Optional[str] = None, end_date: Optional[str] = None):
        try:
            df = self.provider.get_etf_daily_kline(ts_code, start_date=start_date, end_date=end_date, adjust="qfq")
            if df is None or df.empty:
                return pd.DataFrame()
            return df
        except Exception as e:
            logger.warning(f"[sync] 获取ETF K线失败 {ts_code}: {e}")
            return pd.DataFrame()

    def sync_financial_data(
        self,
        ts_code: Optional[str] = None,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        sync_id = None
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            if not self.warehouse.enabled:
                return {"status": "skipped", "reason": "warehouse_disabled"}

            sync_id = self.warehouse.save_sync_status(
                sync_type="financial_data",
                status="running",
                started_at=started,
            )

            stock_df = self.warehouse.get_stock_list()
            if ts_code:
                stock_df = stock_df[stock_df["ts_code"] == ts_code]
            if stock_df.empty:
                self.warehouse.update_sync_status(sync_id, status="failed", error_msg="股票列表为空",
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                return {"status": "failed", "error": "no_stocks"}

            total = len(stock_df)
            success = 0
            failed = 0
            logger.info(f"[sync] 开始同步 {total} 只股票财务数据...")

            for idx, row in stock_df.iterrows():
                code = row["ts_code"]
                try:
                    reports = self.provider.get_financial_data(code)
                    if reports:
                        count = self.warehouse.save_financial_data(code, reports)
                        if count > 0:
                            success += 1
                        else:
                            failed += 1
                    else:
                        failed += 1

                    if progress_cb:
                        progress_cb(idx + 1, total, code)
                    if (idx + 1) % 100 == 0:
                        logger.info(f"[sync] 财务进度: {idx+1}/{total}, 成功: {success}")
                    time.sleep(0.3)

                except Exception as e:
                    failed += 1
                    logger.warning(f"[sync] 同步财务数据失败 {code}: {e}")

            self.warehouse.update_sync_status(sync_id, status="success",
                total_count=total, success_count=success, failed_count=failed,
                last_sync_date=datetime.now().strftime("%Y%m%d"),
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            logger.info(f"[sync] 财务数据同步完成: 成功{success}, 失败{failed}")
            return {"status": "success", "total": total, "success": success, "failed": failed}

        except Exception as e:
            logger.error(f"[sync] 财务数据同步失败: {e}")
            if sync_id:
                self.warehouse.update_sync_status(sync_id, status="failed",
                    error_msg=str(e), finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            return {"status": "failed", "error": str(e)}

    def sync_money_flow(
        self,
        trade_date: Optional[str] = None,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> dict:
        sync_id = None
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            if not self.warehouse.enabled:
                return {"status": "skipped", "reason": "warehouse_disabled"}

            sync_id = self.warehouse.save_sync_status(
                sync_type="money_flow", status="running", started_at=started)

            if not trade_date:
                trade_date = datetime.now().strftime("%Y%m%d")

            stock_df = self.warehouse.get_stock_list()
            if stock_df.empty:
                self.warehouse.update_sync_status(sync_id, status="failed", error_msg="股票列表为空",
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                return {"status": "failed", "error": "no_stocks"}

            total = len(stock_df)
            success = 0
            failed = 0
            logger.info(f"[sync] 开始同步资金流向({trade_date})...")

            for idx, row in stock_df.iterrows():
                code = row["ts_code"]
                try:
                    flows = self.provider.get_money_flow(code, trade_date)
                    if flows:
                        count = self.warehouse.save_money_flow(flows)
                        if count > 0:
                            success += 1
                        else:
                            failed += 1
                    else:
                        failed += 1

                    if progress_cb:
                        progress_cb(idx + 1, total, code)
                    if (idx + 1) % 100 == 0:
                        logger.info(f"[sync] 资金流向进度: {idx+1}/{total}, 成功: {success}")
                    time.sleep(0.3)

                except Exception as e:
                    failed += 1

            self.warehouse.update_sync_status(sync_id, status="success",
                total_count=total, success_count=success, failed_count=failed,
                last_sync_date=trade_date,
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            logger.info(f"[sync] 资金流向同步完成: 成功{success}, 失败{failed}")
            return {"status": "success", "total": total, "success": success, "failed": failed}

        except Exception as e:
            logger.error(f"[sync] 资金流向同步失败: {e}")
            if sync_id:
                self.warehouse.update_sync_status(sync_id, status="failed",
                    error_msg=str(e), finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            return {"status": "failed", "error": str(e)}

    def sync_industry_aggregation(self, trade_date: Optional[str] = None) -> dict:
        sync_id = None
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            if not self.warehouse.enabled:
                return {"status": "skipped", "reason": "warehouse_disabled"}

            sync_id = self.warehouse.save_sync_status(
                sync_type="industry_aggregation", status="running", started_at=started)

            if not trade_date:
                trade_date = datetime.now().strftime("%Y%m%d")

            stock_df = self.warehouse.get_stock_list()
            if stock_df.empty:
                self.warehouse.update_sync_status(sync_id, status="failed", error_msg="股票列表为空",
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                return {"status": "failed", "error": "no_stocks"}

            from alpha_agent.infra.db.database import SessionLocal
            from alpha_agent.infra.db.models import DailyKline as KlineModel
            from sqlalchemy import text as sa_text

            with SessionLocal() as db:
                kline_rows = db.query(KlineModel).filter(
                    KlineModel.trade_date == trade_date
                ).all()
                kline_data = [
                    {
                        "ts_code": r.ts_code,
                        "trade_date": r.trade_date,
                        "pct_chg": float(r.pct_chg),
                        "vol": float(r.vol),
                        "amount": float(r.amount),
                    }
                    for r in kline_rows
                ]
            kline_df = pd.DataFrame(kline_data)
            if kline_df.empty:
                self.warehouse.update_sync_status(sync_id, status="failed", error_msg=f"无{trade_date}的K线数据",
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                return {"status": "failed", "error": "no_kline"}

            merged = kline_df.merge(stock_df[["ts_code", "industry"]], on="ts_code", how="left")
            merged = merged[merged["industry"].notna() & (merged["industry"] != "")]

            records = []
            for industry, group in merged.groupby("industry"):
                pct_chg = group["pct_chg"].astype(float)
                records.append({
                    "industry": industry,
                    "trade_date": trade_date,
                    "stock_count": int(len(group)),
                    "avg_pct_chg": float(round(pct_chg.mean(), 4)),
                    "median_pct_chg": float(round(pct_chg.median(), 4)),
                    "up_count": int((pct_chg > 0).sum()),
                    "down_count": int((pct_chg < 0).sum()),
                    "total_volume": float(round(group["vol"].astype(float).sum(), 2)),
                    "total_amount": float(round(group["amount"].astype(float).sum(), 2)),
                    "avg_turnover_rate": float(round(
                        (group["amount"].astype(float) / group["vol"].astype(float).replace(0, 1)).mean(), 4
                    )),
                })

            count = self.warehouse.save_industry_aggregation(records)
            self.warehouse.update_sync_status(sync_id, status="success",
                total_count=len(records), success_count=count,
                last_sync_date=trade_date,
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            logger.info(f"[sync] 行业聚合同步完成: {count} 个行业")
            return {"status": "success", "industry_count": len(records), "saved": count}

        except Exception as e:
            logger.error(f"[sync] 行业聚合同步失败: {e}")
            if sync_id:
                self.warehouse.update_sync_status(sync_id, status="failed",
                    error_msg=str(e), finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            return {"status": "failed", "error": str(e)}

    def sync_macro_data(self) -> dict:
        sync_id = None
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            if not self.warehouse.enabled:
                return {"status": "skipped", "reason": "warehouse_disabled"}

            sync_id = self.warehouse.save_sync_status(
                sync_type="macro_data", status="running", started_at=started)

            logger.info("[sync] 开始同步宏观经济数据...")
            records = self.provider.get_macro_data()
            if not records:
                self.warehouse.update_sync_status(sync_id, status="failed", error_msg="获取宏观数据为空",
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                return {"status": "failed", "error": "empty_data"}

            count = self.warehouse.save_macro_data(records)
            self.warehouse.update_sync_status(sync_id, status="success",
                total_count=len(records), success_count=count,
                last_sync_date=datetime.now().strftime("%Y%m%d"),
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            logger.info(f"[sync] 宏观数据同步完成: {count} 条")
            return {"status": "success", "count": count}

        except Exception as e:
            logger.error(f"[sync] 宏观数据同步失败: {e}")
            if sync_id:
                self.warehouse.update_sync_status(sync_id, status="failed",
                    error_msg=str(e), finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            return {"status": "failed", "error": str(e)}

    def sync_sentiment_data(self, trade_date: Optional[str] = None) -> dict:
        sync_id = None
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            if not self.warehouse.enabled:
                return {"status": "skipped", "reason": "warehouse_disabled"}

            sync_id = self.warehouse.save_sync_status(
                sync_type="sentiment_data", status="running", started_at=started)

            if not trade_date:
                trade_date = datetime.now().strftime("%Y%m%d")

            logger.info(f"[sync] 开始同步舆情数据({trade_date})...")
            records = self.provider.get_sentiment_data(trade_date)
            if not records:
                self.warehouse.update_sync_status(sync_id, status="failed", error_msg="获取舆情数据为空",
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                return {"status": "failed", "error": "empty_data"}

            count = self.warehouse.save_sentiment_data(records)
            self.warehouse.update_sync_status(sync_id, status="success",
                total_count=len(records), success_count=count,
                last_sync_date=trade_date,
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            logger.info(f"[sync] 舆情数据同步完成: {count} 条")
            return {"status": "success", "count": count}

        except Exception as e:
            logger.error(f"[sync] 舆情数据同步失败: {e}")
            if sync_id:
                self.warehouse.update_sync_status(sync_id, status="failed",
                    error_msg=str(e), finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            return {"status": "failed", "error": str(e)}

    def sync_stock_factors(self, trade_date: Optional[str] = None, ts_code: Optional[str] = None) -> dict:
        sync_id = None
        started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            if not self.warehouse.enabled:
                return {"status": "skipped", "reason": "warehouse_disabled"}

            sync_id = self.warehouse.save_sync_status(
                sync_type="stock_factors", status="running", started_at=started)

            if not trade_date:
                trade_date = datetime.now().strftime("%Y%m%d")

            from datetime import timedelta
            start_dt = datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=180)
            start_dt_str = start_dt.strftime("%Y%m%d")

            stock_df = self.warehouse.get_stock_list()
            if ts_code:
                stock_df = stock_df[stock_df["ts_code"] == ts_code]
            if stock_df.empty:
                self.warehouse.update_sync_status(sync_id, status="failed", error_msg="股票列表为空",
                    finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                return {"status": "failed", "error": "no_stocks"}

            total = len(stock_df)
            success = 0
            failed = 0
            logger.info(f"[sync] 开始计算 {total} 只股票因子...")

            for idx, row in stock_df.iterrows():
                code = row["ts_code"]
                try:
                    kline = self.warehouse.get_daily_kline(ts_code=code, start_date=start_dt_str, end_date=trade_date)
                    if kline is not None and not kline.empty and len(kline) > 120:
                        kline = kline.tail(120)
                    if kline is None or kline.empty or len(kline) < 20:
                        failed += 1
                        continue

                    factors = self._compute_factors(code, trade_date, kline)
                    if factors:
                        self.warehouse.save_stock_factors([factors])
                        success += 1
                    else:
                        failed += 1

                    if (idx + 1) % 200 == 0:
                        logger.info(f"[sync] 因子进度: {idx+1}/{total}, 成功: {success}")

                except Exception as e:
                    failed += 1

            self.warehouse.update_sync_status(sync_id, status="success",
                total_count=total, success_count=success, failed_count=failed,
                last_sync_date=trade_date,
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            logger.info(f"[sync] 因子计算完成: 成功{success}, 失败{failed}")
            return {"status": "success", "total": total, "success": success, "failed": failed}

        except Exception as e:
            logger.error(f"[sync] 因子计算失败: {e}")
            if sync_id:
                self.warehouse.update_sync_status(sync_id, status="failed",
                    error_msg=str(e), finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            return {"status": "failed", "error": str(e)}

    @staticmethod
    def _compute_factors(ts_code: str, trade_date: str, df: pd.DataFrame) -> Optional[dict]:
        try:
            df = df.sort_values("trade_date").reset_index(drop=True)
            closes = df["close"].astype(float).values
            volumes = df["vol"].astype(float).values
            highs = df["high"].astype(float).values
            lows = df["low"].astype(float).values
            n = len(closes)

            if n < 61:
                return None

            momentum_5d = (closes[-1] / closes[-6] - 1) * 100 if n >= 6 else 0
            momentum_20d = (closes[-1] / closes[-21] - 1) * 100 if n >= 21 else 0
            momentum_60d = (closes[-1] / closes[-61] - 1) * 100 if n >= 61 else 0

            reversal_5d = -((closes[-1] / closes[-2] - 1) * 100) if n >= 2 else 0

            ret_20 = pd.Series(closes).pct_change().tail(20)
            volatility_20d = ret_20.std() * (252 ** 0.5) * 100 if len(ret_20) >= 2 else 0

            vol_5 = volumes[-5:].mean() if n >= 5 else 0
            vol_20 = volumes[-20:-1].mean() if n >= 21 else 1
            volume_ratio_5d = vol_5 / vol_20 if vol_20 > 0 else 1

            amounts = df["amount"].astype(float).tail(20).values
            turnover_avg_20d = amounts.mean() if len(amounts) > 0 else 0

            amplitudes = ((highs[-20:] - lows[-20:]) / closes[-20:]) * 100
            amplitude_avg_20d = amplitudes.mean() if len(amplitudes) > 0 else 0

            delta = pd.Series(closes).diff()
            gain = delta.clip(lower=0).tail(15).mean()
            loss = -delta.clip(upper=0).tail(15).mean()
            rsi_14 = 100 - (100 / (1 + gain / loss)) if loss > 0 else 100

            composite = (
                momentum_20d * 0.25 + momentum_60d * 0.15 + reversal_5d * 0.1
                + (100 - volatility_20d) * 0.15 + volume_ratio_5d * 0.1
                + rsi_14 * 0.15 - amplitude_avg_20d * 0.1
            )

            return {
                "ts_code": ts_code,
                "trade_date": trade_date,
                "momentum_5d": float(round(momentum_5d, 4)),
                "momentum_20d": float(round(momentum_20d, 4)),
                "momentum_60d": float(round(momentum_60d, 4)),
                "reversal_5d": float(round(reversal_5d, 4)),
                "volatility_20d": float(round(volatility_20d, 4)),
                "volume_ratio_5d": float(round(volume_ratio_5d, 4)),
                "turnover_avg_20d": float(round(turnover_avg_20d, 2)),
                "amplitude_avg_20d": float(round(amplitude_avg_20d, 4)),
                "rsi_14": float(round(rsi_14, 4)),
                "composite_score": float(round(composite, 4)),
            }
        except Exception as e:
            logger.warning(f"[factor] 计算因子失败 {ts_code}: {e}")
            return None

    def sync_all(self, full: bool = False) -> dict:
        results = {}

        logger.info("=" * 50)
        logger.info("[sync] 开始全量数据同步")
        logger.info("=" * 50)

        logger.info("[sync] 第1步: 同步股票列表")
        results["stock_list"] = self.sync_stock_list()

        logger.info("[sync] 第2步: 同步ETF列表")
        results["etf_list"] = self.sync_etf_list()

        logger.info("[sync] 第3步: 同步股票K线")
        results["stock_kline"] = self.sync_stock_kline()

        logger.info("[sync] 第4步: 同步ETF K线")
        results["etf_kline"] = self.sync_etf_kline()

        logger.info("[sync] 第5步: 同步财务数据")
        results["financial_data"] = self.sync_financial_data()

        logger.info("[sync] 第6步: 同步资金流向")
        results["money_flow"] = self.sync_money_flow()

        logger.info("[sync] 第7步: 行业聚合")
        results["industry_aggregation"] = self.sync_industry_aggregation()

        logger.info("[sync] 第8步: 同步宏观数据")
        results["macro_data"] = self.sync_macro_data()

        logger.info("[sync] 第9步: 同步舆情数据")
        results["sentiment_data"] = self.sync_sentiment_data()

        logger.info("[sync] 第10步: 计算因子")
        results["stock_factors"] = self.sync_stock_factors()

        logger.info("=" * 50)
        logger.info("[sync] 全量数据同步完成")
        logger.info("=" * 50)

        return results


_sync_service: Optional[DataSyncService] = None


def get_data_sync_service() -> DataSyncService:
    global _sync_service
    if _sync_service is None:
        _sync_service = DataSyncService()
    return _sync_service