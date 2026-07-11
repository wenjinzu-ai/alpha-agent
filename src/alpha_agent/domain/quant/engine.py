from typing import List, Optional
import pandas as pd
import numpy as np

from alpha_agent.domain.quant.models import (
    BacktestResult,
    Trade,
    TradeSignal,
    SignalType,
)
from alpha_agent.domain.quant.strategies import generate_signals_from_scores
from alpha_agent.utils.logger import logger


class BacktestEngine:
    def __init__(
        self,
        initial_capital: float = 100000.0,
        commission_pct: float = 0.0003,
        slippage_pct: float = 0.001,
        position_pct: float = 0.95,
    ):
        self.initial_capital = initial_capital
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.position_pct = position_pct

    def run(
        self,
        ts_code: str,
        kline_df: pd.DataFrame,
        strategy: str = "score_based",
        benchmark_df: Optional[pd.DataFrame] = None,
        **kwargs,
    ) -> BacktestResult:
        logger.info(f"[backtest] 开始回测: {ts_code}, {len(kline_df)} 条K线")

        if kline_df is None or len(kline_df) < 60:
            raise ValueError("K线数据不足，至少需要60条")

        df = kline_df.copy().reset_index(drop=True)
        dates = df["trade_date"].astype(str).values
        closes = df["close"].astype(float).values

        signals = generate_signals_from_scores(df)

        trades, equity_curve = self._simulate_trading(dates, closes, signals)

        result = self._calc_metrics(
            ts_code=ts_code,
            dates=dates,
            closes=closes,
            trades=trades,
            equity_curve=equity_curve,
            signals=signals,
            benchmark_df=benchmark_df,
        )

        logger.info(
            f"[backtest] 回测完成: 收益率={result.total_return_pct:.2f}%, "
            f"夏普={result.sharpe_ratio:.2f}, 交易次数={result.total_trades}"
        )
        return result

    def _simulate_trading(
        self,
        dates: np.ndarray,
        closes: np.ndarray,
        signals: List[TradeSignal],
    ) -> tuple:
        cash = self.initial_capital
        position = 0
        avg_cost = 0.0
        trades: List[Trade] = []
        equity_curve = []

        signal_map = {s.date: s for s in signals}
        open_trade: Optional[Trade] = None

        for i in range(len(dates)):
            date = str(dates[i])
            price = float(closes[i])

            if date in signal_map:
                sig = signal_map[date]

                if sig.signal == SignalType.BUY and position == 0:
                    buy_price = price * (1 + self.slippage_pct)
                    available_cash = cash * self.position_pct
                    volume = int(available_cash / (buy_price * 100)) * 100
                    if volume > 0:
                        cost = volume * buy_price
                        commission = cost * self.commission_pct
                        total_cost = cost + commission
                        cash -= total_cost
                        position = volume
                        avg_cost = buy_price
                        open_trade = Trade(
                            open_date=date,
                            close_date=None,
                            ts_code="",
                            direction="long",
                            open_price=buy_price,
                            close_price=None,
                            volume=volume,
                        )

                elif sig.signal == SignalType.SELL and position > 0:
                    sell_price = price * (1 - self.slippage_pct)
                    revenue = position * sell_price
                    commission = revenue * self.commission_pct
                    net_revenue = revenue - commission
                    cash += net_revenue

                    pnl = net_revenue - position * avg_cost
                    pnl_pct = (pnl / (position * avg_cost)) * 100

                    if open_trade:
                        open_trade.close_date = date
                        open_trade.close_price = sell_price
                        open_trade.pnl = pnl
                        open_trade.pnl_pct = pnl_pct
                        trades.append(open_trade)
                        open_trade = None

                    position = 0
                    avg_cost = 0.0

            equity = cash + position * price
            equity_curve.append({
                "date": date,
                "equity": round(equity, 2),
                "cash": round(cash, 2),
                "position": position,
                "price": price,
            })

        if position > 0 and open_trade:
            last_price = float(closes[-1])
            sell_price = last_price * (1 - self.slippage_pct)
            revenue = position * sell_price
            commission = revenue * self.commission_pct
            net_revenue = revenue - commission
            cash += net_revenue

            pnl = net_revenue - position * avg_cost
            pnl_pct = (pnl / (position * avg_cost)) * 100

            open_trade.close_date = str(dates[-1])
            open_trade.close_price = sell_price
            open_trade.pnl = pnl
            open_trade.pnl_pct = pnl_pct
            trades.append(open_trade)

            equity_curve[-1]["equity"] = round(cash, 2)
            equity_curve[-1]["cash"] = round(cash, 2)
            equity_curve[-1]["position"] = 0

        return trades, equity_curve

    def _calc_metrics(
        self,
        ts_code: str,
        dates: np.ndarray,
        closes: np.ndarray,
        trades: List[Trade],
        equity_curve: List[dict],
        signals: List[TradeSignal],
        benchmark_df: Optional[pd.DataFrame],
    ) -> BacktestResult:
        equities = np.array([e["equity"] for e in equity_curve])

        return_metrics = self._calc_return_metrics(equities)
        risk_metrics = self._calc_risk_metrics(equities)
        trade_metrics = self._calc_trade_metrics(trades)
        benchmark_return = self._calc_benchmark_return(benchmark_df)

        return BacktestResult(
            ts_code=ts_code,
            start_date=str(dates[0]),
            end_date=str(dates[-1]),
            initial_capital=self.initial_capital,
            final_capital=round(return_metrics["final_capital"], 2),
            total_return_pct=round(return_metrics["total_return"], 2),
            annual_return_pct=round(return_metrics["annual_return"], 2),
            benchmark_return_pct=round(benchmark_return, 2),
            excess_return_pct=round(return_metrics["total_return"] - benchmark_return, 2),
            max_drawdown_pct=round(risk_metrics["max_drawdown"], 2),
            sharpe_ratio=round(risk_metrics["sharpe"], 2),
            sortino_ratio=round(risk_metrics["sortino"], 2),
            win_rate=round(trade_metrics["win_rate"], 2),
            profit_loss_ratio=round(trade_metrics["profit_loss_ratio"], 2),
            total_trades=trade_metrics["total_trades"],
            winning_trades=trade_metrics["winning_trades"],
            losing_trades=trade_metrics["losing_trades"],
            max_consecutive_wins=trade_metrics["max_consec_wins"],
            max_consecutive_losses=trade_metrics["max_consec_losses"],
            trades=trades,
            equity_curve=equity_curve,
            signals=signals,
        )

    def _calc_return_metrics(self, equities: np.ndarray) -> dict:
        final_capital = float(equities[-1])
        total_return = (final_capital / self.initial_capital - 1) * 100

        n_days = len(equities)
        annual_return = (
            ((final_capital / self.initial_capital) ** (252 / n_days) - 1) * 100
            if n_days > 0
            else 0
        )

        return {
            "final_capital": final_capital,
            "total_return": total_return,
            "annual_return": annual_return,
        }

    def _calc_risk_metrics(self, equities: np.ndarray) -> dict:
        daily_returns = np.diff(equities) / equities[:-1]

        if len(daily_returns) > 1 and np.std(daily_returns) > 0:
            sharpe = (np.mean(daily_returns) / np.std(daily_returns)) * np.sqrt(252)
        else:
            sharpe = 0

        downside_returns = daily_returns[daily_returns < 0]
        if len(downside_returns) > 1 and np.std(downside_returns) > 0:
            sortino = (np.mean(daily_returns) / np.std(downside_returns)) * np.sqrt(252)
        else:
            sortino = 0

        peak = np.maximum.accumulate(equities)
        drawdown = (equities - peak) / peak * 100
        max_drawdown = float(abs(np.min(drawdown)))

        return {
            "sharpe": sharpe,
            "sortino": sortino,
            "max_drawdown": max_drawdown,
        }

    def _calc_trade_metrics(self, trades: List[Trade]) -> dict:
        winning = [t for t in trades if t.pnl > 0]
        losing = [t for t in trades if t.pnl <= 0]
        total_trades = len(trades)

        win_rate = (len(winning) / total_trades * 100) if total_trades > 0 else 0

        avg_win = np.mean([t.pnl_pct for t in winning]) if winning else 0
        avg_loss = abs(np.mean([t.pnl_pct for t in losing])) if losing else 0
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

        max_consec_wins = 0
        max_consec_losses = 0
        cur_wins = 0
        cur_losses = 0
        for t in trades:
            if t.pnl > 0:
                cur_wins += 1
                cur_losses = 0
                max_consec_wins = max(max_consec_wins, cur_wins)
            else:
                cur_losses += 1
                cur_wins = 0
                max_consec_losses = max(max_consec_losses, cur_losses)

        return {
            "total_trades": total_trades,
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": win_rate,
            "profit_loss_ratio": profit_loss_ratio,
            "max_consec_wins": max_consec_wins,
            "max_consec_losses": max_consec_losses,
        }

    def _calc_benchmark_return(self, benchmark_df: Optional[pd.DataFrame]) -> float:
        if benchmark_df is None or len(benchmark_df) <= 1:
            return 0.0
        bench_closes = benchmark_df["close"].astype(float).values
        return (bench_closes[-1] / bench_closes[0] - 1) * 100

