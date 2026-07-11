from typing import List
import pandas as pd
import numpy as np

from alpha_agent.domain.quant.models import TradeSignal, SignalType


def generate_signals_from_scores(
    df: pd.DataFrame,
    buy_threshold: float = 65.0,
    sell_threshold: float = 35.0,
    window: int = 20,
) -> List[TradeSignal]:
    """基于滚动评分生成交易信号。

    用简化的技术指标模拟"综合评分"：
    - 均线多头 + RSI 低位 → 买入信号
    - 均线空头 + RSI 高位 → 卖出信号
    """
    signals = []
    closes = df["close"].astype(float).values
    volumes = df["vol"].astype(float).values
    dates = df["trade_date"].astype(str).values
    n = len(df)

    ma5 = pd.Series(closes).rolling(5).mean().values
    ma20 = pd.Series(closes).rolling(20).mean().values
    ma60 = pd.Series(closes).rolling(60).mean().values

    rsi = _calc_rsi(closes, 14)

    for i in range(60, n):
        if np.isnan(ma20[i]) or np.isnan(ma60[i]) or np.isnan(rsi[i]):
            continue

        score = 50.0
        reasons = []

        if ma5[i] > ma20[i] > ma60[i]:
            score += 15
            reasons.append("均线多头")
        elif ma5[i] < ma20[i] < ma60[i]:
            score -= 15
            reasons.append("均线空头")

        if rsi[i] < 30:
            score += 20
            reasons.append("RSI超卖")
        elif rsi[i] < 40:
            score += 10
            reasons.append("RSI偏低")
        elif rsi[i] > 70:
            score -= 20
            reasons.append("RSI超买")
        elif rsi[i] > 60:
            score -= 10
            reasons.append("RSI偏高")

        vol_ma20 = np.mean(volumes[max(0, i - 20):i])
        if volumes[i] > vol_ma20 * 1.5 and closes[i] > closes[i - 1]:
            score += 10
            reasons.append("放量上涨")
        elif volumes[i] > vol_ma20 * 1.5 and closes[i] < closes[i - 1]:
            score -= 10
            reasons.append("放量下跌")

        score = max(0, min(100, score))

        signal_type = SignalType.HOLD
        if score >= buy_threshold:
            signal_type = SignalType.BUY
        elif score <= sell_threshold:
            signal_type = SignalType.SELL

        if signal_type != SignalType.HOLD:
            prev_signal = signals[-1].signal if signals else None
            if signal_type != prev_signal:
                signals.append(TradeSignal(
                    date=str(dates[i]),
                    ts_code=df.get("ts_code", [""])[0] if hasattr(df, 'get') else "",
                    signal=signal_type,
                    price=float(closes[i]),
                    score=round(score, 2),
                    reason="+".join(reasons),
                ))

    return signals


def _calc_rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)

    rsi = np.full(len(prices), np.nan)
    if len(prices) <= period:
        return rsi

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(prices) - 1):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period

        if avg_loss == 0:
            rsi[i + 1] = 100
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100 - (100 / (1 + rs))

    return rsi

