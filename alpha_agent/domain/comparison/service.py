from typing import List, Dict, Any, Optional
import pandas as pd

from alpha_agent.domain.market import get_data_service
from alpha_agent.utils.logger import logger


class StockComparison:
    def __init__(self):
        self.ds = get_data_service()

    def compare(self, ts_codes: List[str]) -> Dict[str, Any]:
        logger.info(f"[comparison] 开始对比 {len(ts_codes)} 只股票: {ts_codes}")

        results = []
        for ts_code in ts_codes:
            try:
                result = self._analyze_one(ts_code)
                if result:
                    results.append(result)
            except Exception as e:
                logger.error(f"[comparison] 分析 {ts_code} 失败: {e}")
                results.append({"ts_code": ts_code, "error": str(e)})

        ranked = sorted(
            [r for r in results if "error" not in r],
            key=lambda x: x.get("final_score", 0) or 0,
            reverse=True,
        )

        comparison = self._build_comparison_table(ranked)

        return {
            "count": len(ts_codes),
            "success_count": len(ranked),
            "ranked": ranked,
            "comparison_table": comparison,
            "all_results": results,
        }

    def _analyze_one(self, ts_code: str) -> Optional[Dict[str, Any]]:
        basic_df = self.ds.get_stock_basic(ts_code)
        if basic_df is None or basic_df.empty:
            return None

        info = basic_df.iloc[0].to_dict()

        from datetime import datetime, timedelta
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=180)).strftime("%Y%m%d")
        klines = self.ds.get_daily_kline(ts_code, start_date=start_date, end_date=end_date)
        if klines is None or klines.empty:
            return None

        fundamental = self._calc_fundamental(info, klines)
        technical = self._calc_technical(klines)
        risk = self._calc_risk(klines, info)

        final_score = (
            fundamental.get("score", 50) * 0.35
            + technical.get("score", 50) * 0.35
            + risk.get("score", 50) * 0.30
        )

        final_score = round(max(0, min(100, final_score)), 1)
        final_rating = self._score_to_rating(final_score)

        return {
            "ts_code": ts_code,
            "name": info.get("name", "") or info.get("ts_name", "") or "",
            "final_score": final_score,
            "final_rating": final_rating,
            "fundamental": fundamental,
            "technical": technical,
            "risk_control": risk,
        }

    def _calc_fundamental(self, info: dict, klines: pd.DataFrame) -> Dict[str, Any]:
        score = 50.0
        details = {}

        industry = info.get("industry", "")
        if industry:
            details["industry"] = industry
            hot_industries = ["半导体", "人工智能", "新能源", "医药", "白酒", "银行", "保险"]
            if any(h in industry for h in hot_industries):
                score += 5
                details["industry_tier"] = "热门"
            else:
                details["industry_tier"] = "普通"

        list_date = info.get("list_date", "")
        if list_date and len(str(list_date)) >= 8:
            from datetime import datetime
            try:
                list_dt = datetime.strptime(str(list_date), "%Y%m%d")
                years = (datetime.now() - list_dt).days / 365
                details["list_years"] = round(years, 1)
                if years > 10:
                    score += 5
                    details["maturity"] = "成熟"
                elif years < 2:
                    score -= 5
                    details["maturity"] = "次新"
            except:
                pass

        market = info.get("market", "")
        if market in ["SH", "SZ"]:
            score += 3
            details["market"] = market

        if len(klines) >= 60:
            close = klines["close"].astype(float)
            avg_vol = klines["vol"].astype(float).tail(20).mean()
            current_price = close.iloc[-1]
            if avg_vol > 0 and current_price > 0:
                amount_yi = avg_vol * current_price / 100000000
                details["avg_amount_yi"] = round(amount_yi, 2)
                if amount_yi > 10:
                    score += 8
                    details["liquidity"] = "极好"
                elif amount_yi > 3:
                    score += 5
                    details["liquidity"] = "好"
                elif amount_yi > 0.5:
                    score += 2
                    details["liquidity"] = "一般"
                else:
                    score -= 5
                    details["liquidity"] = "差"

        score = max(0, min(100, score))
        return {
            "score": round(score, 1),
            "rating": self._score_to_rating(score),
            "detail": details,
        }

    def _calc_technical(self, klines: pd.DataFrame) -> Dict[str, Any]:
        score = 50.0
        details = {}

        if len(klines) < 20:
            return {"score": 50, "rating": "中性", "detail": {"note": "数据不足"}}

        close = klines["close"].astype(float)
        volume = klines["vol"].astype(float)

        ma5 = close.rolling(5).mean().iloc[-1]
        ma10 = close.rolling(10).mean().iloc[-1]
        ma20 = close.rolling(20).mean().iloc[-1]
        ma60 = close.rolling(60).mean().iloc[-1] if len(close) >= 60 else None
        current = close.iloc[-1]

        details["current_price"] = float(current)
        details["ma5"] = round(float(ma5), 2)
        details["ma10"] = round(float(ma10), 2)
        details["ma20"] = round(float(ma20), 2)

        if current > ma5 > ma10 > ma20:
            score += 20
            details["trend"] = "多头排列"
        elif current < ma5 < ma10 < ma20:
            score -= 20
            details["trend"] = "空头排列"
        elif current > ma20:
            score += 8
            details["trend"] = "偏强"
        else:
            score -= 8
            details["trend"] = "偏弱"

        if ma60 and current > ma60:
            score += 5
            details["ma60"] = round(float(ma60), 2)
        elif ma60:
            score -= 5
            details["ma60"] = round(float(ma60), 2)

        returns = close.pct_change().dropna()
        if len(returns) >= 20:
            momentum_10d = (current / close.iloc[-11] - 1) * 100 if len(close) >= 11 else 0
            if momentum_10d > 5:
                score += 8
            elif momentum_10d < -5:
                score -= 8
            details["momentum_10d"] = round(momentum_10d, 2)

        if len(returns) >= 20:
            vol_20d = returns.tail(20).std() * (252 ** 0.5) * 100
            details["volatility_20d"] = round(vol_20d, 2)
            if vol_20d < 25:
                score += 3
            elif vol_20d > 45:
                score -= 5

        score = max(0, min(100, score))
        return {
            "score": round(score, 1),
            "rating": self._score_to_rating(score),
            "detail": details,
        }

    def _calc_risk(self, klines: pd.DataFrame, info: dict) -> Dict[str, Any]:
        score = 50.0
        details = {}

        if len(klines) < 20:
            return {"score": 50, "rating": "中等", "detail": {"note": "数据不足"}, "position_pct": "不建议"}

        close = klines["close"].astype(float)
        high = klines["high"].astype(float)
        low = klines["low"].astype(float)
        volume = klines["vol"].astype(float)

        returns = close.pct_change().dropna()

        if len(returns) >= 20:
            vol_20d = returns.tail(20).std() * (252 ** 0.5) * 100
            details["volatility_20d_pct"] = round(vol_20d, 2)
            if vol_20d < 20:
                score += 15
            elif vol_20d < 30:
                score += 8
            elif vol_20d < 40:
                score -= 5
            else:
                score -= 15

        if len(close) >= 60:
            max_60 = high.tail(60).max()
            current = close.iloc[-1]
            drawdown = (max_60 - current) / max_60 * 100
            details["max_drawdown_60d_pct"] = round(drawdown, 2)
            if drawdown < 10:
                score += 10
            elif drawdown < 20:
                score += 3
            elif drawdown < 35:
                score -= 5
            else:
                score -= 12

        avg_vol = volume.tail(20).mean()
        if avg_vol > 0:
            details["avg_volume"] = float(avg_vol)
            if avg_vol > 1000000:
                score += 3
                details["liquidity"] = "好"
            elif avg_vol < 100000:
                score -= 5
                details["liquidity"] = "差"

        score = max(0, min(100, score))

        if score >= 75:
            position_pct = "20-30%"
        elif score >= 60:
            position_pct = "10-20%"
        elif score >= 45:
            position_pct = "5-10%"
        else:
            position_pct = "不建议"

        return {
            "score": round(score, 1),
            "rating": self._risk_score_to_rating(score),
            "detail": {**details, "position_pct": position_pct},
            "position_pct": position_pct,
        }

    def _score_to_rating(self, score: float) -> str:
        if score >= 80:
            return "强烈推荐"
        elif score >= 65:
            return "推荐"
        elif score >= 50:
            return "中性"
        elif score >= 35:
            return "谨慎"
        else:
            return "回避"

    def _risk_score_to_rating(self, score: float) -> str:
        if score >= 75:
            return "低风险"
        elif score >= 55:
            return "中低风险"
        elif score >= 40:
            return "中风险"
        elif score >= 25:
            return "中高风险"
        else:
            return "高风险"

    def _build_comparison_table(self, ranked: List[dict]) -> List[dict]:
        table = []
        for i, r in enumerate(ranked, 1):
            fund = r.get("fundamental", {})
            tech = r.get("technical", {})
            risk = r.get("risk_control", {})

            row = {
                "排名": i,
                "代码": r.get("ts_code", ""),
                "名称": r.get("name", ""),
                "综合评分": r.get("final_score", "-"),
                "综合评级": r.get("final_rating", "-"),
                "基本面评分": fund.get("score", "-"),
                "基本面评级": fund.get("rating", "-"),
                "技术面评分": tech.get("score", "-"),
                "技术面评级": tech.get("rating", "-"),
                "风控评分": risk.get("score", "-"),
                "风控评级": risk.get("rating", "-"),
                "建议仓位": risk.get("position_pct", "-"),
            }
            table.append(row)
        return table

    def format_comparison_text(self, comparison: Dict[str, Any]) -> str:
        table = comparison.get("comparison_table", [])
        if not table:
            return "没有可对比的股票数据"

        lines = [
            f"=== 股票对比报告（{comparison['success_count']}/{comparison['count']}只）===",
            "",
            "排名  代码        名称    综合分  评级    基本面  技术面  风控   建议仓位",
            "-" * 80,
        ]

        for row in table:
            lines.append(
                f"  {row['排名']}  {row['代码']:<10}  {row['名称']:<6}  "
                f"{str(row['综合评分']):>5}  {row['综合评级']:<4}  "
                f"{str(row['基本面评分']):>5}  "
                f"{str(row['技术面评分']):>5}  "
                f"{str(row['风控评分']):>5}  "
                f"{row['建议仓位']}"
            )

        lines.append("")
        lines.append("说明：评分越高越好，满分为100")
        lines.append("建议仓位由风控模型给出，仅供参考")

        return "\n".join(lines)


_comparison = None


def get_stock_comparison() -> StockComparison:
    global _comparison
    if _comparison is None:
        _comparison = StockComparison()
    return _comparison
