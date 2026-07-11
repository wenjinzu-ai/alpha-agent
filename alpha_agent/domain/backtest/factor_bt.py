from typing import List, Dict, Optional, Callable
import pandas as pd
import numpy as np
from datetime import datetime

from alpha_agent.domain.market import get_data_service
from alpha_agent.infra.db.warehouse import get_data_warehouse
from alpha_agent.domain.factors.technical import calc_technical_indicators, score_technical
from alpha_agent.utils.logger import logger


class FactorBacktestResult:
    def __init__(self):
        self.total_return_pct: float = 0.0
        self.annual_return_pct: float = 0.0
        self.max_drawdown_pct: float = 0.0
        self.sharpe_ratio: float = 0.0
        self.win_rate: float = 0.0
        self.total_trades: int = 0
        self.equity_curve: List[Dict] = []
        self.holdings_history: List[Dict] = []
        self.trades: List[Dict] = []


class FactorBacktestEngine:
    def __init__(
        self,
        initial_capital: float = 100000.0,
        commission_pct: float = 0.0003,
        slippage_pct: float = 0.001,
    ):
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.ds = get_data_service()
        self.warehouse = get_data_warehouse()

    def run_factor_strategy(
        self,
        universe: List[str],
        factor_name: str = "technical_score",
        rebalance_freq: str = "monthly",
        top_n: int = 10,
        weight: str = "equal",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> FactorBacktestResult:
        logger.info(
            f"[factor_bt] 开始因子策略回测: 因子={factor_name}, "
            f"调仓={rebalance_freq}, Top={top_n}, 标的数={len(universe)}"
        )

        kline_data = {}
        total = len(universe)
        for idx, code in enumerate(universe):
            try:
                df = self.ds.get_daily_kline(ts_code=code, start_date=start_date, end_date=end_date, adjust="qfq")
                if df is not None and not df.empty:
                    kline_data[code] = df
            except Exception as e:
                logger.debug(f"[factor_bt] 获取K线失败 {code}: {e}")

            if progress_cb:
                progress_cb(idx + 1, total, f"load_{code}")

        if not kline_data:
            raise ValueError("没有可用的K线数据")

        all_dates = set()
        for code, df in kline_data.items():
            all_dates.update(df["trade_date"].astype(str).tolist())
        all_dates = sorted(list(all_dates))

        if not all_dates:
            raise ValueError("没有共同的交易日")

        rebalance_dates = self._get_rebalance_dates(all_dates, rebalance_freq)

        cash = self.initial_capital
        holdings: Dict[str, float] = {}
        equity_curve = []
        holdings_history = []
        trades = []

        date_idx = {code: {d: i for i, d in enumerate(df["trade_date"].astype(str).tolist())}
                     for code, df in kline_data.items()}

        close_cache = {}
        for code, df in kline_data.items():
            close_cache[code] = df["close"].astype(float).values

        for date in all_dates:
            total_value = cash
            for code, shares in holdings.items():
                if date in date_idx[code]:
                    idx = date_idx[code][date]
                    price = close_cache[code][idx]
                    total_value += shares * price

            equity_curve.append({"date": date, "equity": total_value})

            if date in rebalance_dates:
                scores = []
                for code, df in kline_data.items():
                    if date in date_idx[code]:
                        idx = date_idx[code][date]
                        if idx >= 60:
                            sub_df = df.iloc[:idx+1].copy()
                            try:
                                ind = calc_technical_indicators(sub_df)
                                score, _, _ = score_technical(ind)
                                scores.append({"ts_code": code, "score": score})
                            except Exception:
                                pass

                if scores:
                    scores.sort(key=lambda x: x["score"], reverse=True)
                    selected = [s["ts_code"] for s in scores[:top_n]]

                    for code in list(holdings.keys()):
                        if code not in selected and holdings[code] > 0:
                            if date in date_idx[code]:
                                idx = date_idx[code][date]
                                price = close_cache[code][idx]
                                sell_price = price * (1 - self.slippage_pct)
                                proceeds = holdings[code] * sell_price
                                commission = proceeds * self.commission_pct
                                cash += proceeds - commission
                                trades.append({
                                    "date": date,
                                    "ts_code": code,
                                    "side": "sell",
                                    "price": sell_price,
                                    "shares": holdings[code],
                                    "amount": proceeds,
                                })
                                holdings[code] = 0

                    holdings = {k: v for k, v in holdings.items() if v > 0}

                    if selected:
                        if weight == "equal":
                            target_value_per_stock = total_value / len(selected)
                        else:
                            target_value_per_stock = total_value / len(selected)

                        for code in selected:
                            if date in date_idx[code]:
                                idx = date_idx[code][date]
                                price = close_cache[code][idx]
                                buy_price = price * (1 + self.slippage_pct)
                                current_shares = holdings.get(code, 0)
                                current_value = current_shares * price
                                target_shares = int(target_value_per_stock / (buy_price * 100)) * 100

                                if target_shares > current_shares:
                                    buy_shares = target_shares - current_shares
                                    cost = buy_shares * buy_price
                                    commission = cost * self.commission_pct
                                    total_cost = cost + commission
                                    if cash >= total_cost:
                                        cash -= total_cost
                                        holdings[code] = target_shares
                                        trades.append({
                                            "date": date,
                                            "ts_code": code,
                                            "side": "buy",
                                            "price": buy_price,
                                            "shares": buy_shares,
                                            "amount": cost,
                                        })

                holdings_snapshot = []
                for code, shares in holdings.items():
                    if date in date_idx[code]:
                        idx = date_idx[code][date]
                        price = close_cache[code][idx]
                        holdings_snapshot.append({
                            "ts_code": code,
                            "shares": shares,
                            "price": price,
                            "value": shares * price,
                        })
                holdings_history.append({
                    "date": date,
                    "holdings": holdings_snapshot,
                    "total_value": total_value,
                    "cash": cash,
                })

        result = FactorBacktestResult()
        result.equity_curve = equity_curve
        result.holdings_history = holdings_history
        result.trades = trades
        result.total_trades = len(trades)

        if equity_curve:
            final_equity = equity_curve[-1]["equity"]
            result.total_return_pct = (final_equity / self.initial_capital - 1) * 100

            days = len(equity_curve)
            if days > 0:
                result.annual_return_pct = ((final_equity / self.initial_capital) ** (252 / days) - 1) * 100

            equity_values = [e["equity"] for e in equity_curve]
            peak = np.maximum.accumulate(equity_values)
            drawdown = (equity_values - peak) / peak * 100
            result.max_drawdown_pct = float(abs(np.min(drawdown)))

            if len(equity_values) > 1:
                returns = np.diff(equity_values) / equity_values[:-1]
                if np.std(returns) > 0:
                    result.sharpe_ratio = float(np.mean(returns) / np.std(returns) * np.sqrt(252))

            buy_trades = [t for t in trades if t["side"] == "buy"]
            if buy_trades:
                wins = sum(1 for t in buy_trades if t.get("pnl", 0) > 0)
                result.win_rate = wins / len(buy_trades) * 100

        logger.info(
            f"[factor_bt] 回测完成: 收益率={result.total_return_pct:.2f}%, "
            f"夏普={result.sharpe_ratio:.2f}, 最大回撤={result.max_drawdown_pct:.2f}%"
        )
        return result

    def _get_rebalance_dates(self, all_dates: List[str], freq: str) -> set:
        rebalance = set()

        if freq == "daily":
            return set(all_dates)
        elif freq == "weekly":
            last_week = ""
            for d in all_dates:
                week = d[:6] + str(int(d[6:8]) // 7)
                if week != last_week:
                    rebalance.add(d)
                    last_week = week
        elif freq == "monthly":
            last_month = ""
            for d in all_dates:
                month = d[:6]
                if month != last_month:
                    rebalance.add(d)
                    last_month = month
        elif freq == "quarterly":
            last_quarter = ""
            for d in all_dates:
                month = int(d[4:6])
                quarter = d[:4] + "Q" + str((month - 1) // 3 + 1)
                if quarter != last_quarter:
                    rebalance.add(d)
                    last_quarter = quarter

        return rebalance

    def get_report(self, result: FactorBacktestResult) -> str:
        lines = [
            "📊 因子策略回测报告",
            "=" * 50,
            f"初始资金: {self.initial_capital:,.2f}",
            f"总收益率: {result.total_return_pct:.2f}%",
            f"年化收益率: {result.annual_return_pct:.2f}%",
            f"最大回撤: {result.max_drawdown_pct:.2f}%",
            f"夏普比率: {result.sharpe_ratio:.2f}",
            f"交易次数: {result.total_trades}",
            "=" * 50,
        ]

        if result.equity_curve:
            lines.append("净值走势(关键节点):")
            n = len(result.equity_curve)
            indices = [0, n//4, n//2, 3*n//4, n-1]
            for i in indices:
                if i < n:
                    e = result.equity_curve[i]
                    ret = (e["equity"] / self.initial_capital - 1) * 100
                    lines.append(f"  {e['date']}: {e['equity']:,.2f} ({ret:+.2f}%)")

        return "\n".join(lines)


_factor_bt_engine: Optional[FactorBacktestEngine] = None


def get_factor_backtest_engine() -> FactorBacktestEngine:
    global _factor_bt_engine
    if _factor_bt_engine is None:
        _factor_bt_engine = FactorBacktestEngine()
    return _factor_bt_engine
