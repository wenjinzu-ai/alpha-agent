from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np


def calc_technical_indicators(df: pd.DataFrame) -> Dict[str, float]:
    if df is None or df.empty or len(df) < 5:
        return {}

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    vol = df["vol"].astype(float)

    result = {}
    n = len(close)

    ma5 = close.rolling(5).mean().iloc[-1]
    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1] if n >= 60 else None
    ma120 = close.rolling(120).mean().iloc[-1] if n >= 120 else None
    ma250 = close.rolling(250).mean().iloc[-1] if n >= 250 else None

    result["ma5"] = round(float(ma5), 3) if pd.notna(ma5) else None
    result["ma10"] = round(float(ma10), 3) if pd.notna(ma10) else None
    result["ma20"] = round(float(ma20), 3) if pd.notna(ma20) else None
    result["ma60"] = round(float(ma60), 3) if pd.notna(ma60) and ma60 is not None else None
    result["ma120"] = round(float(ma120), 3) if pd.notna(ma120) and ma120 is not None else None
    result["ma250"] = round(float(ma250), 3) if pd.notna(ma250) and ma250 is not None else None
    result["latest_close"] = round(float(close.iloc[-1]), 3)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd = (dif - dea) * 2

    result["macd_dif"] = round(float(dif.iloc[-1]), 4) if pd.notna(dif.iloc[-1]) else None
    result["macd_dea"] = round(float(dea.iloc[-1]), 4) if pd.notna(dea.iloc[-1]) else None
    result["macd_bar"] = round(float(macd.iloc[-1]), 4) if pd.notna(macd.iloc[-1]) else None

    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    result["rsi_6"] = None
    result["rsi_14"] = None
    result["rsi_24"] = None
    if n >= 6:
        delta6 = close.diff()
        gain6 = delta6.where(delta6 > 0, 0)
        loss6 = (-delta6).where(delta6 < 0, 0)
        avg_gain6 = gain6.rolling(6).mean()
        avg_loss6 = loss6.rolling(6).mean()
        rs6 = avg_gain6 / avg_loss6
        rsi6 = 100 - (100 / (1 + rs6))
        result["rsi_6"] = round(float(rsi6.iloc[-1]), 2) if pd.notna(rsi6.iloc[-1]) else None
    if n >= 14:
        result["rsi_14"] = round(float(rsi.iloc[-1]), 2) if pd.notna(rsi.iloc[-1]) else None
    if n >= 24:
        delta24 = close.diff()
        gain24 = delta24.where(delta24 > 0, 0)
        loss24 = (-delta24).where(delta24 < 0, 0)
        avg_gain24 = gain24.rolling(24).mean()
        avg_loss24 = loss24.rolling(24).mean()
        rs24 = avg_gain24 / avg_loss24
        rsi24 = 100 - (100 / (1 + rs24))
        result["rsi_24"] = round(float(rsi24.iloc[-1]), 2) if pd.notna(rsi24.iloc[-1]) else None

    low_9 = low.rolling(9).min()
    high_9 = high.rolling(9).max()
    rsv = (close - low_9) / (high_9 - low_9) * 100
    k = rsv.rolling(3).mean()
    d = k.rolling(3).mean()
    j = 3 * k - 2 * d

    result["kdj_k"] = round(float(k.iloc[-1]), 2) if pd.notna(k.iloc[-1]) else None
    result["kdj_d"] = round(float(d.iloc[-1]), 2) if pd.notna(d.iloc[-1]) else None
    result["kdj_j"] = round(float(j.iloc[-1]), 2) if pd.notna(j.iloc[-1]) else None

    vol_ma5 = vol.rolling(5).mean().iloc[-1]
    vol_ma10 = vol.rolling(10).mean().iloc[-1]
    vol_ratio = vol.iloc[-1] / vol_ma5 if vol_ma5 and vol_ma5 > 0 else 1.0

    result["vol_ratio"] = round(float(vol_ratio), 2)
    result["vol_ma5"] = round(float(vol_ma5), 0) if pd.notna(vol_ma5) else None
    result["vol_ma10"] = round(float(vol_ma10), 0) if pd.notna(vol_ma10) else None
    result["latest_vol"] = round(float(vol.iloc[-1]), 0)

    result["change_pct_1d"] = round(float(close.pct_change().iloc[-1] * 100), 2) if n >= 2 else None
    result["change_pct_5d"] = round(float((close.iloc[-1] / close.iloc[-5] - 1) * 100), 2) if n >= 5 else None
    result["change_pct_20d"] = round(float((close.iloc[-1] / close.iloc[-20] - 1) * 100), 2) if n >= 20 else None
    result["change_pct_60d"] = round(float((close.iloc[-1] / close.iloc[-60] - 1) * 100), 2) if n >= 60 else None

    if n >= 20:
        rolling_max = close.rolling(20).max().iloc[-1]
        rolling_min = close.rolling(20).min().iloc[-1]
        if rolling_max > rolling_min:
            result["position_20d"] = round(float((close.iloc[-1] - rolling_min) / (rolling_max - rolling_min) * 100), 1)
        else:
            result["position_20d"] = 50.0
    else:
        result["position_20d"] = None

    if n >= 60:
        high_60 = high.rolling(60).max().iloc[-1]
        low_60 = low.rolling(60).min().iloc[-1]
        atr = (high_60 - low_60) / close.iloc[-1] * 100
        result["volatility_60d"] = round(float(atr), 2)
    else:
        result["volatility_60d"] = None

    return result


def score_technical(indicators: Dict[str, float]) -> Tuple[float, str, List[str]]:
    if not indicators:
        return 0.0, "数据不足", []

    score = 50.0
    signals = []

    if indicators.get("ma5") and indicators.get("ma20"):
        if indicators["ma5"] > indicators["ma20"]:
            score += 8
            signals.append("MA5 > MA20，短期趋势偏多")
        else:
            score -= 8
            signals.append("MA5 < MA20，短期趋势偏空")

    if indicators.get("ma20") and indicators.get("ma60"):
        if indicators["ma20"] > indicators["ma60"]:
            score += 7
            signals.append("MA20 > MA60，中期趋势偏多")
        else:
            score -= 7
            signals.append("MA20 < MA60，中期趋势偏空")

    if indicators.get("ma60") and indicators.get("ma120"):
        if indicators["ma60"] > indicators["ma120"]:
            score += 5
            signals.append("MA60 > MA120，长期趋势偏多")
        else:
            score -= 5
            signals.append("MA60 < MA120，长期趋势偏空")

    if indicators.get("macd_dif") and indicators.get("macd_dea"):
        if indicators["macd_dif"] > indicators["macd_dea"]:
            score += 6
            signals.append("MACD 金叉区间")
        else:
            score -= 6
            signals.append("MACD 死叉区间")

        if indicators.get("macd_bar", 0) > 0:
            score += 3
            signals.append("MACD 红柱，动能偏多")
        else:
            score -= 3
            signals.append("MACD 绿柱，动能偏空")

    if indicators.get("rsi_14") is not None:
        rsi = indicators["rsi_14"]
        if rsi > 70:
            score -= 5
            signals.append(f"RSI={rsi:.1f}，超买区域")
        elif rsi < 30:
            score += 5
            signals.append(f"RSI={rsi:.1f}，超卖区域")
        elif rsi > 50:
            score += 2
            signals.append(f"RSI={rsi:.1f}，偏强")
        else:
            score -= 2
            signals.append(f"RSI={rsi:.1f}，偏弱")

    if indicators.get("kdj_k") and indicators.get("kdj_d"):
        if indicators["kdj_k"] > indicators["kdj_d"]:
            score += 4
            signals.append("KDJ 金叉")
        else:
            score -= 4
            signals.append("KDJ 死叉")

    if indicators.get("vol_ratio", 1.0) > 1.5:
        score += 3
        signals.append(f"放量 (量比 {indicators['vol_ratio']})")
    elif indicators.get("vol_ratio", 1.0) < 0.7:
        score -= 2
        signals.append(f"缩量 (量比 {indicators['vol_ratio']})")

    if indicators.get("change_pct_20d") is not None:
        chg = indicators["change_pct_20d"]
        if chg > 15:
            score -= 3
            signals.append(f"20日涨幅 {chg:.1f}%，短期超买")
        elif chg < -15:
            score += 3
            signals.append(f"20日跌幅 {abs(chg):.1f}%，短期超卖")

    score = max(0, min(100, score))

    if score >= 75:
        rating = "推荐"
    elif score >= 55:
        rating = "中性偏多"
    elif score >= 45:
        rating = "中性"
    elif score >= 25:
        rating = "中性偏空"
    else:
        rating = "谨慎"

    return round(score, 1), rating, signals


def score_momentum(indicators: Dict[str, float]) -> Tuple[float, str]:
    if not indicators:
        return 0.0, "数据不足"

    score = 50.0

    chg_5 = indicators.get("change_pct_5d")
    chg_20 = indicators.get("change_pct_20d")
    chg_60 = indicators.get("change_pct_60d")

    if chg_5 is not None:
        if chg_5 > 10:
            score += 10
        elif chg_5 > 5:
            score += 5
        elif chg_5 > 0:
            score += 2
        elif chg_5 > -5:
            score -= 2
        elif chg_5 > -10:
            score -= 5
        else:
            score -= 10

    if chg_20 is not None:
        if chg_20 > 20:
            score += 12
        elif chg_20 > 10:
            score += 7
        elif chg_20 > 0:
            score += 3
        elif chg_20 > -10:
            score -= 3
        elif chg_20 > -20:
            score -= 7
        else:
            score -= 12

    if chg_60 is not None:
        if chg_60 > 30:
            score += 8
        elif chg_60 > 15:
            score += 5
        elif chg_60 > 0:
            score += 2
        elif chg_60 > -15:
            score -= 2
        elif chg_60 > -30:
            score -= 5
        else:
            score -= 8

    score = max(0, min(100, score))

    if score >= 70:
        rating = "强势"
    elif score >= 55:
        return score, "偏强"
    elif score >= 45:
        rating = "中性"
    elif score >= 30:
        rating = "偏弱"
    else:
        rating = "弱势"

    return round(score, 1), rating


def score_value(indicators: Dict[str, float]) -> Tuple[float, str]:
    if not indicators:
        return 0.0, "数据不足"

    score = 50.0

    pos = indicators.get("position_20d")
    if pos is not None:
        if pos < 20:
            score += 15
        elif pos < 30:
            score += 10
        elif pos < 40:
            score += 5
        elif pos > 80:
            score -= 15
        elif pos > 70:
            score -= 10
        elif pos > 60:
            score -= 5

    rsi = indicators.get("rsi_14")
    if rsi is not None:
        if rsi < 30:
            score += 10
        elif rsi < 40:
            score += 5
        elif rsi > 70:
            score -= 10
        elif rsi > 60:
            score -= 5

    vol = indicators.get("volatility_60d")
    if vol is not None:
        if vol < 15:
            score += 5
        elif vol > 40:
            score -= 5

    score = max(0, min(100, score))

    if score >= 70:
        rating = "低估"
    elif score >= 55:
        rating = "偏低"
    elif score >= 45:
        rating = "合理"
    elif score >= 30:
        rating = "偏高"
    else:
        rating = "高估"

    return round(score, 1), rating


def calc_composite_score(
    technical_score: float,
    momentum_score: float,
    value_score: float,
    tech_weight: float = 0.4,
    mom_weight: float = 0.35,
    val_weight: float = 0.25,
) -> Tuple[float, str]:
    if technical_score <= 0 and momentum_score <= 0 and value_score <= 0:
        return 0.0, "数据不足"

    total = tech_weight + mom_weight + val_weight
    score = (technical_score * tech_weight + momentum_score * mom_weight + value_score * val_weight) / total
    score = round(score, 1)

    if score >= 70:
        rating = "强烈推荐"
    elif score >= 60:
        rating = "推荐"
    elif score >= 50:
        rating = "中性偏多"
    elif score >= 40:
        rating = "中性偏空"
    elif score >= 30:
        rating = "谨慎"
    else:
        rating = "回避"

    return score, rating
