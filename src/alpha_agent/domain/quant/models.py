from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum
from datetime import datetime


class SignalType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class TradeSignal:
    date: str
    ts_code: str
    signal: SignalType
    price: float
    score: float
    reason: str = ""


@dataclass
class Trade:
    open_date: str
    close_date: Optional[str]
    ts_code: str
    direction: str
    open_price: float
    close_price: Optional[float]
    volume: int
    pnl: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class BacktestResult:
    ts_code: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float
    total_return_pct: float
    annual_return_pct: float
    benchmark_return_pct: float = 0.0
    excess_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    win_rate: float = 0.0
    profit_loss_ratio: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[dict] = field(default_factory=list)
    signals: List[TradeSignal] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "ts_code": self.ts_code,
            "period": f"{self.start_date} ~ {self.end_date}",
            "初始资金": f"{self.initial_capital:,.2f}",
            "最终资金": f"{self.final_capital:,.2f}",
            "总收益率": f"{self.total_return_pct:.2f}%",
            "年化收益率": f"{self.annual_return_pct:.2f}%",
            "基准收益率": f"{self.benchmark_return_pct:.2f}%",
            "超额收益率": f"{self.excess_return_pct:.2f}%",
            "最大回撤": f"{self.max_drawdown_pct:.2f}%",
            "夏普比率": f"{self.sharpe_ratio:.2f}",
            "索提诺比率": f"{self.sortino_ratio:.2f}",
            "胜率": f"{self.win_rate:.2f}%",
            "盈亏比": f"{self.profit_loss_ratio:.2f}",
            "总交易次数": self.total_trades,
            "盈利次数": self.winning_trades,
            "亏损次数": self.losing_trades,
            "最大连盈": self.max_consecutive_wins,
            "最大连亏": self.max_consecutive_losses,
        }
