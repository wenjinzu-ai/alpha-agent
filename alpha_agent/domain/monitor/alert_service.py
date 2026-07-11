from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from alpha_agent.domain.market import get_data_service
from alpha_agent.infra.db.warehouse import get_data_warehouse
from alpha_agent.utils.logger import logger


class AlertType(str, Enum):
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    CHANGE_ABOVE = "change_above"
    CHANGE_BELOW = "change_below"
    VOLUME_ABOVE = "volume_above"


@dataclass
class PriceAlert:
    id: str
    ts_code: str
    alert_type: AlertType
    threshold: float
    triggered: bool = False
    triggered_price: Optional[float] = None
    triggered_time: Optional[str] = None
    created_at: str = ""


class AlertService:
    def __init__(self):
        self._alerts: Dict[str, List[PriceAlert]] = {}
        self._ds = None

    def _get_ds(self):
        if self._ds is None:
            self._ds = get_data_service()
        return self._ds

    def add_alert(
        self,
        ts_code: str,
        alert_type: str,
        threshold: float,
    ) -> str:
        import uuid
        alert_id = f"alert_{uuid.uuid4().hex[:8]}"
        alert = PriceAlert(
            id=alert_id,
            ts_code=ts_code,
            alert_type=AlertType(alert_type),
            threshold=threshold,
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        if ts_code not in self._alerts:
            self._alerts[ts_code] = []
        self._alerts[ts_code].append(alert)
        logger.info(f"[alert] 添加告警: {ts_code} {alert_type} {threshold}")
        return alert_id

    def remove_alert(self, alert_id: str) -> bool:
        for ts_code, alerts in self._alerts.items():
            for i, a in enumerate(alerts):
                if a.id == alert_id:
                    alerts.pop(i)
                    logger.info(f"[alert] 移除告警: {alert_id}")
                    return True
        return False

    def list_alerts(self, ts_code: Optional[str] = None) -> List[dict]:
        result = []
        for code, alerts in self._alerts.items():
            if ts_code and code != ts_code:
                continue
            for a in alerts:
                result.append({
                    "id": a.id,
                    "ts_code": a.ts_code,
                    "type": a.alert_type.value,
                    "threshold": a.threshold,
                    "triggered": a.triggered,
                    "triggered_price": a.triggered_price,
                    "triggered_time": a.triggered_time,
                    "created_at": a.created_at,
                })
        return result

    def check_alerts(self, ts_code: str) -> List[dict]:
        alerts = self._alerts.get(ts_code, [])
        if not alerts:
            return []

        try:
            ds = self._get_ds()
            df = ds.get_realtime_quote(ts_code)
            if df is None or df.empty:
                return []

            row = df.iloc[0]
            price = float(row.get("最新价", 0))
            change_pct = float(row.get("涨跌幅", 0))
            volume = float(row.get("成交量", 0))

            return self._check_with_price(alerts, price, change_pct, volume)
        except Exception as e:
            logger.error(f"[alert] 检查告警失败: {e}")
            return []

    def check_all_alerts(
        self,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[dict]:
        all_triggered = []
        all_codes = list(self._alerts.keys())
        total = len(all_codes)

        logger.info(f"[alert] 开始检查全部告警，共 {total} 只标的")

        for idx, code in enumerate(all_codes):
            triggered = self.check_alerts(code)
            all_triggered.extend(triggered)
            if progress_cb:
                progress_cb(idx + 1, total, code)

        logger.info(f"[alert] 告警检查完成，触发 {len(all_triggered)} 条")
        return all_triggered

    def check_alerts_with_kline(self, ts_code: str) -> List[dict]:
        alerts = self._alerts.get(ts_code, [])
        if not alerts:
            return []

        try:
            ds = self._get_ds()
            df = ds.get_daily_kline(ts_code=ts_code, adjust="qfq")
            if df is None or df.empty:
                return []

            row = df.iloc[-1]
            price = float(row.get("close", 0))
            pre_close = float(row.get("pre_close", 0)) if pd_notna(row.get("pre_close")) else price
            change_pct = (price - pre_close) / pre_close * 100 if pre_close > 0 else 0
            volume = float(row.get("vol", 0))

            return self._check_with_price(alerts, price, change_pct, volume)
        except Exception as e:
            logger.error(f"[alert] 用K线检查告警失败: {e}")
            return []

    def _check_with_price(
        self,
        alerts: List[PriceAlert],
        price: float,
        change_pct: float,
        volume: float,
    ) -> List[dict]:
        triggered = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for alert in alerts:
            if alert.triggered:
                continue
            hit = False
            if alert.alert_type == AlertType.PRICE_ABOVE and price >= alert.threshold:
                hit = True
            elif alert.alert_type == AlertType.PRICE_BELOW and price <= alert.threshold:
                hit = True
            elif alert.alert_type == AlertType.CHANGE_ABOVE and change_pct >= alert.threshold:
                hit = True
            elif alert.alert_type == AlertType.CHANGE_BELOW and change_pct <= alert.threshold:
                hit = True
            elif alert.alert_type == AlertType.VOLUME_ABOVE and volume >= alert.threshold:
                hit = True

            if hit:
                alert.triggered = True
                alert.triggered_price = price
                alert.triggered_time = now
                triggered.append({
                    "id": alert.id,
                    "ts_code": alert.ts_code,
                    "type": alert.alert_type.value,
                    "threshold": alert.threshold,
                    "current_price": price,
                    "change_pct": change_pct,
                    "triggered_time": now,
                    "message": self._format_alert_message(alert, price, change_pct),
                })
                logger.info(f"[alert] 告警触发: {alert.ts_code} {alert.alert_type} {alert.threshold}, 当前价={price}")

        return triggered

    def _format_alert_message(self, alert: PriceAlert, price: float, change_pct: float) -> str:
        type_map = {
            AlertType.PRICE_ABOVE: "价格上涨突破",
            AlertType.PRICE_BELOW: "价格下跌跌破",
            AlertType.CHANGE_ABOVE: "涨幅超过",
            AlertType.CHANGE_BELOW: "跌幅超过",
            AlertType.VOLUME_ABOVE: "成交量超过",
        }
        type_name = type_map.get(alert.alert_type, alert.alert_type.value)
        return f"⚠️ {alert.ts_code} 触发告警：{type_name} {alert.threshold}，当前价 {price:.2f}（{change_pct:+.2f}%）"

    def reset_alert(self, alert_id: str) -> bool:
        for ts_code, alerts in self._alerts.items():
            for a in alerts:
                if a.id == alert_id:
                    a.triggered = False
                    a.triggered_price = None
                    a.triggered_time = None
                    logger.info(f"[alert] 重置告警: {alert_id}")
                    return True
        return False

    def clear_triggered(self) -> int:
        count = 0
        for ts_code, alerts in self._alerts.items():
            for a in alerts:
                if a.triggered:
                    a.triggered = False
                    a.triggered_price = None
                    a.triggered_time = None
                    count += 1
        return count


def pd_notna(v) -> bool:
    import pandas as pd
    return pd.notna(v)


_alert_service: Optional[AlertService] = None


def get_alert_service() -> AlertService:
    global _alert_service
    if _alert_service is None:
        _alert_service = AlertService()
    return _alert_service
