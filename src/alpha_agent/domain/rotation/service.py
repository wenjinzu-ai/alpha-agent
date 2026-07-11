from typing import List, Dict, Optional
import pandas as pd
import numpy as np
from datetime import datetime

from alpha_agent.domain.market import get_data_service
from alpha_agent.infra.db.warehouse import get_data_warehouse
from alpha_agent.domain.factors.technical import calc_technical_indicators, score_momentum
from alpha_agent.utils.logger import logger


class IndustryRotationService:
    def __init__(self):
        self.ds = get_data_service()
        self.warehouse = get_data_warehouse()

    def get_industry_list(self) -> List[str]:
        if not self.warehouse.enabled:
            return []

        stock_df = self.warehouse.get_stock_list()
        if stock_df.empty:
            return []

        industries = stock_df["industry"].dropna().unique().tolist()
        industries = [i for i in industries if i]
        return sorted(industries)

    def calc_industry_momentum(
        self,
        top_n_stocks: int = 10,
        lookback_days: int = 20,
    ) -> pd.DataFrame:
        if not self.warehouse.enabled:
            return pd.DataFrame()

        stock_df = self.warehouse.get_stock_list()
        if stock_df.empty:
            return pd.DataFrame()

        industries = self.get_industry_list()
        if not industries:
            return pd.DataFrame()

        results = []
        total = len(industries)
        logger.info(f"[rotation] 计算行业动量，共 {total} 个行业")

        for idx, industry in enumerate(industries):
            try:
                ind_stocks = stock_df[stock_df["industry"] == industry]
                if len(ind_stocks) < 3:
                    continue

                changes = []
                mom_scores = []
                sample_stocks = ind_stocks.head(min(top_n_stocks * 2, len(ind_stocks)))

                for _, row in sample_stocks.iterrows():
                    try:
                        df = self.ds.get_daily_kline(ts_code=row["ts_code"], adjust="qfq")
                        if df is not None and not df.empty and len(df) >= lookback_days:
                            closes = df["close"].astype(float)
                            chg = (closes.iloc[-1] / closes.iloc[-lookback_days] - 1) * 100
                            changes.append(chg)

                            ind = calc_technical_indicators(df)
                            score, _ = score_momentum(ind)
                            mom_scores.append(score)
                    except Exception:
                        pass

                if changes:
                    avg_change = np.mean(changes)
                    avg_mom = np.mean(mom_scores) if mom_scores else 50.0

                    results.append({
                        "industry": industry,
                        "stock_count": len(ind_stocks),
                        "sample_count": len(changes),
                        f"avg_return_{lookback_days}d": round(avg_change, 2),
                        "momentum_score": round(avg_mom, 1),
                        "avg_price": 0,
                    })

            except Exception as e:
                logger.debug(f"[rotation] 计算行业动量失败 {industry}: {e}")

            if (idx + 1) % 10 == 0:
                logger.info(f"[rotation] 进度: {idx+1}/{total}")

        if not results:
            return pd.DataFrame()

        result_df = pd.DataFrame(results)
        result_df = result_df.sort_values("momentum_score", ascending=False)
        result_df["rank"] = range(1, len(result_df) + 1)
        return result_df.reset_index(drop=True)

    def get_rotation_signals(
        self,
        top_n: int = 5,
        bottom_n: int = 5,
    ) -> Dict:
        mom_df = self.calc_industry_momentum()
        if mom_df.empty:
            return {}

        top_industries = mom_df.head(top_n).to_dict("records")
        bottom_industries = mom_df.tail(bottom_n).to_dict("records")

        strong = [r["industry"] for r in top_industries]
        weak = [r["industry"] for r in bottom_industries]

        return {
            "strong_industries": strong,
            "weak_industries": weak,
            "top_details": top_industries,
            "bottom_details": bottom_industries,
            "all_industries": mom_df.to_dict("records"),
        }

    def get_report(self, signals: Dict) -> str:
        if not signals:
            return "暂无行业轮动数据"

        lines = [
            "🔄 行业轮动分析",
            "=" * 50,
            f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        if signals.get("top_details"):
            lines.append("📈 强势行业 (建议关注):")
            for i, item in enumerate(signals["top_details"], 1):
                lines.append(
                    f"  {i}. {item['industry']:<10} "
                    f"动量分: {item['momentum_score']:>5.1f} "
                    f"20日涨跌: {item['avg_return_20d']:>+6.1f}% "
                    f"成分股: {item['sample_count']}只"
                )
            lines.append("")

        if signals.get("bottom_details"):
            lines.append("📉 弱势行业 (建议回避):")
            for i, item in enumerate(reversed(signals["bottom_details"]), 1):
                lines.append(
                    f"  {i}. {item['industry']:<10} "
                    f"动量分: {item['momentum_score']:>5.1f} "
                    f"20日涨跌: {item['avg_return_20d']:>+6.1f}% "
                    f"成分股: {item['sample_count']}只"
                )
            lines.append("")

        lines.append("策略建议:")
        lines.append("  - 优先配置强势行业中的龙头股")
        lines.append("  - 回避或减仓弱势行业")
        lines.append("  - 每月初根据动量变化调整行业配置")

        return "\n".join(lines)


_rotation_service: Optional[IndustryRotationService] = None


def get_industry_rotation_service() -> IndustryRotationService:
    global _rotation_service
    if _rotation_service is None:
        _rotation_service = IndustryRotationService()
    return _rotation_service
