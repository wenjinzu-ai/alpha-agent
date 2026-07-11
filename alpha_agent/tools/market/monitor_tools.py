from typing import Optional
from langchain_core.tools import tool

from alpha_agent.domain.market import get_data_service
from alpha_agent.domain.monitor import get_alert_service
from alpha_agent.utils.logger import logger


@tool
def get_realtime_quote(ts_code: str) -> str:
    """获取股票的实时行情数据，包括当前价格、涨跌幅、成交量、成交额等。
    当用户询问当前价格、实时行情、现在多少钱、涨了多少等问题时使用。
    
    Args:
        ts_code: 股票代码，如 000001.SZ
    """
    try:
        ds = get_data_service()
        df = ds.get_realtime_quote(ts_code)
        if df is None or df.empty:
            return f"暂无 {ts_code} 的实时行情数据（可能未开盘或代码错误）"

        row = df.iloc[0]
        name = row.get("名称", row.get("name", ts_code))
        price = row.get("最新价", row.get("price", "-"))
        change_pct = row.get("涨跌幅", row.get("change_pct", "-"))
        change = row.get("涨跌额", row.get("change", "-"))
        volume = row.get("成交量", row.get("volume", "-"))
        amount = row.get("成交额", row.get("amount", "-"))
        high = row.get("最高", row.get("high", "-"))
        low = row.get("最低", row.get("low", "-"))
        open_price = row.get("今开", row.get("open", "-"))
        prev_close = row.get("昨收", row.get("pre_close", "-"))

        try:
            vol_str = f"{float(volume) / 10000:.2f}万手" if volume != "-" else "-"
        except (ValueError, TypeError):
            vol_str = str(volume)

        try:
            amt_val = float(amount)
            if amt_val >= 1e8:
                amt_str = f"{amt_val / 1e8:.2f}亿"
            elif amt_val >= 1e4:
                amt_str = f"{amt_val / 1e4:.2f}万"
            else:
                amt_str = str(amt_val)
        except (ValueError, TypeError):
            amt_str = str(amount)

        lines = [
            f"=== {name} ({ts_code}) 实时行情 ===",
            f"最新价: {price}",
            f"涨跌幅: {change_pct}%",
            f"涨跌额: {change}",
            f"今开: {open_price}",
            f"最高: {high}",
            f"最低: {low}",
            f"昨收: {prev_close}",
            f"成交量: {vol_str}",
            f"成交额: {amt_str}",
        ]

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"获取实时行情失败: {e}")
        return f"获取实时行情失败: {e}"


@tool
def add_price_alert(ts_code: str, alert_type: str, threshold: float) -> str:
    """添加价格监控告警，当价格达到设定条件时触发提醒。
    
    Args:
        ts_code: 股票代码，如 000001.SZ
        alert_type: 告警类型，可选：
            - price_above: 价格上涨到某价位
            - price_below: 价格下跌到某价位
            - change_above: 涨幅超过某个百分比
            - change_below: 跌幅超过某个百分比
            - volume_above: 成交量超过某个数值
        threshold: 阈值，价格或百分比数值
    """
    try:
        svc = get_alert_service()
        alert_id = svc.add_alert(ts_code, alert_type, threshold)

        type_names = {
            "price_above": "价格上涨突破",
            "price_below": "价格下跌跌破",
            "change_above": "涨幅超过",
            "change_below": "跌幅超过",
            "volume_above": "成交量超过",
        }
        type_name = type_names.get(alert_type, alert_type)

        return f"✅ 已添加告警：{ts_code} {type_name} {threshold}\n告警ID: {alert_id}"
    except Exception as e:
        logger.error(f"添加告警失败: {e}")
        return f"添加告警失败: {e}"


@tool
def list_alerts(ts_code: Optional[str] = None) -> str:
    """查看当前已设置的所有告警。
    
    Args:
        ts_code: 可选，只看某只股票的告警
    """
    try:
        svc = get_alert_service()
        alerts = svc.list_alerts(ts_code)
        if not alerts:
            return "暂无设置中的告警"

        lines = [f"=== 当前告警（共{len(alerts)}个）==="]
        type_names = {
            "price_above": "价格上涨突破",
            "price_below": "价格下跌跌破",
            "change_above": "涨幅超过",
            "change_below": "跌幅超过",
            "volume_above": "成交量超过",
        }
        for i, a in enumerate(alerts, 1):
            type_name = type_names.get(a["type"], a["type"])
            status = "✅已触发" if a["triggered"] else "⏳监控中"
            lines.append(
                f"{i}. {a['ts_code']} {type_name} {a['threshold']} "
                f"- {status} (ID: {a['id']})"
            )

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"查询告警失败: {e}")
        return f"查询告警失败: {e}"


@tool
def check_alerts(ts_code: str) -> str:
    """检查某只股票的告警是否触发。
    
    Args:
        ts_code: 股票代码，如 000001.SZ
    """
    try:
        svc = get_alert_service()
        triggered = svc.check_alerts(ts_code)
        if not triggered:
            return f"{ts_code} 暂无告警触发，所有监控正常"

        lines = [f"⚠️ {ts_code} 有 {len(triggered)} 个告警触发："]
        for t in triggered:
            lines.append(f"  • {t['message']}")
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"检查告警失败: {e}")
        return f"检查告警失败: {e}"
