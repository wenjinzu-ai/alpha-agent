from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import uuid

import numpy as np
import pandas as pd

from alpha_agent.domain.market import get_data_service
from alpha_agent.infra.db.database import SessionLocal, init_db, check_db_connection
from alpha_agent.infra.db.models import Portfolio as PortfolioModel, PortfolioPosition as PositionModel
from alpha_agent.utils.logger import logger


@dataclass
class Position:
    ts_code: str
    stock_name: str = ""
    shares: int = 0
    cost_price: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    weight: float = 0.0
    profit: float = 0.0
    profit_pct: float = 0.0
    industry: str = ""
    score: float = 0.0


@dataclass
class PortfolioSummary:
    portfolio_id: str
    name: str
    total_market_value: float
    total_cost: float
    total_profit: float
    total_profit_pct: float
    initial_capital: float
    position_count: int
    concentration_ratio: float
    industry_count: int


@dataclass
class PortfolioRisk:
    volatility_20d: float = 0.0
    volatility_60d: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    var_95: float = 0.0
    beta: float = 0.0


class PortfolioService:
    def __init__(self):
        self._enabled = False
        self._init_done = False
        self._mem_portfolios: Dict[str, Dict] = {}
        self._mem_positions: Dict[str, List[Position]] = {}
        self._ds = get_data_service()

    def _ensure_init(self):
        if self._init_done:
            return
        self._enabled = check_db_connection()
        if self._enabled:
            try:
                init_db()
            except Exception as e:
                logger.warning(f"[portfolio] 数据库初始化失败，降级为内存模式: {e}")
                self._enabled = False
        self._init_done = True
        if self._enabled:
            logger.info("[portfolio] 数据库模式已启用")
        else:
            logger.info("[portfolio] 内存模式运行")

    def create_portfolio(self, name: str, description: str = "", initial_capital: float = 100000.0) -> str:
        self._ensure_init()
        portfolio_id = f"pf_{uuid.uuid4().hex[:8]}"

        if self._enabled:
            try:
                with SessionLocal() as db:
                    record = PortfolioModel(
                        portfolio_id=portfolio_id,
                        name=name,
                        description=description,
                        initial_capital=float(initial_capital),
                    )
                    db.add(record)
                    db.commit()
                    logger.info(f"[portfolio] 创建组合(DB): {portfolio_id} - {name}")
                    return portfolio_id
            except Exception as e:
                logger.error(f"[portfolio] DB创建组合失败，降级内存: {e}")

        self._mem_portfolios[portfolio_id] = {
            "portfolio_id": portfolio_id,
            "name": name,
            "description": description,
            "initial_capital": initial_capital,
        }
        self._mem_positions[portfolio_id] = []
        logger.info(f"[portfolio] 创建组合(内存): {portfolio_id} - {name}")
        return portfolio_id

    def list_portfolios(self) -> List[dict]:
        self._ensure_init()

        if self._enabled:
            try:
                with SessionLocal() as db:
                    records = db.query(PortfolioModel).filter(
                        PortfolioModel.is_active == True
                    ).order_by(PortfolioModel.created_at.desc()).all()
                    result = []
                    for r in records:
                        pos_count = db.query(PositionModel).filter(
                            PositionModel.portfolio_id == r.portfolio_id,
                            PositionModel.is_active == True,
                        ).count()
                        result.append({
                            "portfolio_id": r.portfolio_id,
                            "name": r.name,
                            "description": r.description,
                            "initial_capital": float(r.initial_capital),
                            "position_count": pos_count,
                        })
                    return result
            except Exception as e:
                logger.error(f"[portfolio] DB查询组合列表失败: {e}")

        return [
            {
                "portfolio_id": p["portfolio_id"],
                "name": p["name"],
                "description": p["description"],
                "initial_capital": p["initial_capital"],
                "position_count": len(self._mem_positions.get(p["portfolio_id"], [])),
            }
            for p in self._mem_portfolios.values()
        ]

    def get_portfolio(self, portfolio_id: str) -> Optional[dict]:
        self._ensure_init()

        if self._enabled:
            try:
                with SessionLocal() as db:
                    r = db.query(PortfolioModel).filter(
                        PortfolioModel.portfolio_id == portfolio_id,
                        PortfolioModel.is_active == True,
                    ).first()
                    if r:
                        return {
                            "portfolio_id": r.portfolio_id,
                            "name": r.name,
                            "description": r.description,
                            "initial_capital": float(r.initial_capital),
                        }
                    return None
            except Exception as e:
                logger.error(f"[portfolio] DB查询组合失败: {e}")

        return self._mem_portfolios.get(portfolio_id)

    def add_position(
        self,
        portfolio_id: str,
        ts_code: str,
        shares: int,
        cost_price: float,
        stock_name: str = "",
    ) -> bool:
        self._ensure_init()

        if not self.get_portfolio(portfolio_id):
            logger.warning(f"[portfolio] 组合不存在: {portfolio_id}")
            return False

        industry = self._get_industry(ts_code)

        if self._enabled:
            try:
                with SessionLocal() as db:
                    existing = db.query(PositionModel).filter(
                        PositionModel.portfolio_id == portfolio_id,
                        PositionModel.ts_code == ts_code,
                        PositionModel.is_active == True,
                    ).first()

                    if existing:
                        old_shares = int(existing.shares)
                        old_cost = float(existing.cost_price)
                        total_cost = old_shares * old_cost + shares * cost_price
                        total_shares = old_shares + shares
                        existing.cost_price = float(total_cost / total_shares) if total_shares > 0 else 0.0
                        existing.shares = total_shares
                        if stock_name and not existing.stock_name:
                            existing.stock_name = stock_name
                        if industry and not existing.industry:
                            existing.industry = industry
                        db.commit()
                        logger.info(f"[portfolio] {portfolio_id} 加仓(DB) {ts_code}: +{shares}股")
                    else:
                        record = PositionModel(
                            portfolio_id=portfolio_id,
                            ts_code=ts_code,
                            stock_name=stock_name,
                            shares=shares,
                            cost_price=float(cost_price),
                            industry=industry,
                        )
                        db.add(record)
                        db.commit()
                        logger.info(f"[portfolio] {portfolio_id} 建仓(DB) {ts_code}: {shares}股")

                    self._refresh_positions_db(db, portfolio_id)
                    return True
            except Exception as e:
                logger.error(f"[portfolio] DB添加持仓失败，降级内存: {e}")

        positions = self._mem_positions.setdefault(portfolio_id, [])
        existing = next((p for p in positions if p.ts_code == ts_code), None)

        if existing:
            total_cost = existing.shares * existing.cost_price + shares * cost_price
            total_shares = existing.shares + shares
            existing.cost_price = total_cost / total_shares if total_shares > 0 else 0
            existing.shares = total_shares
            if industry and not existing.industry:
                existing.industry = industry
            logger.info(f"[portfolio] {portfolio_id} 加仓(内存) {ts_code}: +{shares}股")
        else:
            pos = Position(
                ts_code=ts_code,
                stock_name=stock_name,
                shares=shares,
                cost_price=cost_price,
                industry=industry,
            )
            positions.append(pos)
            logger.info(f"[portfolio] {portfolio_id} 建仓(内存) {ts_code}: {shares}股")

        self._refresh_positions_mem(portfolio_id)
        return True

    def remove_position(self, portfolio_id: str, ts_code: str, shares: Optional[int] = None) -> bool:
        self._ensure_init()

        if not self.get_portfolio(portfolio_id):
            return False

        if self._enabled:
            try:
                with SessionLocal() as db:
                    existing = db.query(PositionModel).filter(
                        PositionModel.portfolio_id == portfolio_id,
                        PositionModel.ts_code == ts_code,
                        PositionModel.is_active == True,
                    ).first()

                    if not existing:
                        logger.warning(f"[portfolio] 持仓不存在: {ts_code}")
                        return False

                    if shares is None or shares >= existing.shares:
                        existing.is_active = False
                        db.commit()
                        logger.info(f"[portfolio] {portfolio_id} 清仓(DB) {ts_code}")
                    else:
                        existing.shares -= shares
                        db.commit()
                        logger.info(f"[portfolio] {portfolio_id} 减仓(DB) {ts_code}: -{shares}股")

                    self._refresh_positions_db(db, portfolio_id)
                    return True
            except Exception as e:
                logger.error(f"[portfolio] DB移除持仓失败: {e}")
                return False

        positions = self._mem_positions.get(portfolio_id, [])
        existing = next((p for p in positions if p.ts_code == ts_code), None)

        if not existing:
            logger.warning(f"[portfolio] 持仓不存在: {ts_code}")
            return False

        if shares is None or shares >= existing.shares:
            positions.remove(existing)
            logger.info(f"[portfolio] {portfolio_id} 清仓(内存) {ts_code}")
        else:
            existing.shares -= shares
            logger.info(f"[portfolio] {portfolio_id} 减仓(内存) {ts_code}: -{shares}股")

        self._refresh_positions_mem(portfolio_id)
        return True

    def get_positions(self, portfolio_id: str) -> List[Position]:
        self._ensure_init()

        if self._enabled:
            try:
                with SessionLocal() as db:
                    self._refresh_positions_db(db, portfolio_id)
                    records = db.query(PositionModel).filter(
                        PositionModel.portfolio_id == portfolio_id,
                        PositionModel.is_active == True,
                    ).all()
                    positions = [
                        Position(
                            ts_code=r.ts_code,
                            stock_name=r.stock_name,
                            shares=r.shares,
                            cost_price=float(r.cost_price),
                            current_price=float(r.current_price),
                            market_value=float(r.market_value),
                            weight=float(r.weight),
                            profit=float(r.profit),
                            profit_pct=float(r.profit_pct),
                            industry=r.industry,
                        )
                        for r in records
                    ]
                    return sorted(positions, key=lambda p: p.market_value, reverse=True)
            except Exception as e:
                logger.error(f"[portfolio] DB查询持仓失败: {e}")

        positions = self._mem_positions.get(portfolio_id, [])
        if positions:
            self._refresh_positions_mem(portfolio_id)
            return sorted(
                self._mem_positions.get(portfolio_id, []),
                key=lambda p: p.market_value,
                reverse=True,
            )
        return []

    def _get_industry(self, ts_code: str) -> str:
        try:
            df = self._ds.get_stock_basic()
            if df is not None and not df.empty and "industry" in df.columns:
                row = df[df["ts_code"] == ts_code]
                if not row.empty:
                    return str(row.iloc[0]["industry"])
        except Exception:
            pass
        return ""

    def _refresh_positions_db(self, db, portfolio_id: str):
        records = db.query(PositionModel).filter(
            PositionModel.portfolio_id == portfolio_id,
            PositionModel.is_active == True,
        ).all()
        if not records:
            return

        total_mv = 0.0
        for pos in records:
            cost_price = float(pos.cost_price)
            shares = int(pos.shares)
            try:
                df = self._ds.get_realtime_quote(pos.ts_code)
                if df is not None and not df.empty:
                    row = df.iloc[0]
                    price = float(row.get("最新价", cost_price))
                    pos.current_price = price
                    if not pos.stock_name:
                        pos.stock_name = str(row.get("名称", pos.ts_code))
            except Exception:
                pass

            current_price = float(pos.current_price)
            if current_price <= 0:
                current_price = cost_price
                pos.current_price = current_price

            market_value = shares * current_price
            profit = market_value - shares * cost_price
            profit_pct = (profit / (shares * cost_price) * 100) if shares > 0 else 0.0

            pos.market_value = market_value
            pos.profit = profit
            pos.profit_pct = profit_pct
            total_mv += market_value

        if total_mv > 0:
            for pos in records:
                pos.weight = float(pos.market_value) / total_mv

        db.commit()

    def _refresh_positions_mem(self, portfolio_id: str):
        positions = self._mem_positions.get(portfolio_id, [])
        if not positions:
            return

        total_mv = 0.0
        for pos in positions:
            try:
                df = self._ds.get_realtime_quote(pos.ts_code)
                if df is not None and not df.empty:
                    row = df.iloc[0]
                    pos.current_price = float(row.get("最新价", pos.cost_price))
                    if not pos.stock_name:
                        pos.stock_name = str(row.get("名称", pos.ts_code))
            except Exception:
                pass

            if pos.current_price <= 0:
                pos.current_price = pos.cost_price

            pos.market_value = pos.shares * pos.current_price
            pos.profit = pos.market_value - pos.shares * pos.cost_price
            pos.profit_pct = (pos.profit / (pos.shares * pos.cost_price) * 100) if pos.shares > 0 else 0
            total_mv += pos.market_value

        if total_mv > 0:
            for pos in positions:
                pos.weight = pos.market_value / total_mv

    def get_summary(self, portfolio_id: str) -> Optional[PortfolioSummary]:
        portfolio = self.get_portfolio(portfolio_id)
        if not portfolio:
            return None

        positions = self.get_positions(portfolio_id)
        if not positions:
            return PortfolioSummary(
                portfolio_id=portfolio_id,
                name=portfolio["name"],
                total_market_value=0,
                total_cost=0,
                total_profit=0,
                total_profit_pct=0,
                initial_capital=portfolio["initial_capital"],
                position_count=0,
                concentration_ratio=0,
                industry_count=0,
            )

        total_mv = sum(p.market_value for p in positions)
        total_cost = sum(p.shares * p.cost_price for p in positions)
        total_profit = total_mv - total_cost
        total_profit_pct = (total_profit / total_cost * 100) if total_cost > 0 else 0

        weights = sorted([p.weight for p in positions], reverse=True)
        top3 = sum(weights[:3]) if len(weights) >= 3 else sum(weights)

        industries = set(p.industry for p in positions if p.industry)

        return PortfolioSummary(
            portfolio_id=portfolio_id,
            name=portfolio["name"],
            total_market_value=round(total_mv, 2),
            total_cost=round(total_cost, 2),
            total_profit=round(total_profit, 2),
            total_profit_pct=round(total_profit_pct, 2),
            initial_capital=portfolio["initial_capital"],
            position_count=len(positions),
            concentration_ratio=round(top3 * 100, 2),
            industry_count=len(industries),
        )

    def analyze_risk(self, portfolio_id: str, days: int = 250) -> PortfolioRisk:
        positions = self.get_positions(portfolio_id)
        if not positions:
            return PortfolioRisk()

        klines = {}
        for pos in positions:
            try:
                df = self._ds.get_daily_kline(pos.ts_code, adjust="qfq")
                if df is not None and len(df) > 30:
                    klines[pos.ts_code] = df.tail(days).reset_index(drop=True)
            except Exception as e:
                logger.warning(f"[portfolio] 获取 {pos.ts_code} K线失败: {e}")

        if not klines:
            return PortfolioRisk()

        returns_dict = {}
        for ts_code, df in klines.items():
            closes = df["close"].astype(float).values
            rets = np.diff(closes) / closes[:-1]
            returns_dict[ts_code] = rets

        min_len = min(len(r) for r in returns_dict.values())
        aligned = {k: v[-min_len:] for k, v in returns_dict.items()}

        total_weight = sum(p.weight for p in positions if p.ts_code in aligned)
        portfolio_returns = np.zeros(min_len)
        for pos in positions:
            if pos.ts_code in aligned and total_weight > 0:
                w = pos.weight / total_weight
                portfolio_returns += aligned[pos.ts_code] * w

        if len(portfolio_returns) < 20:
            return PortfolioRisk()

        vol_20 = float(np.std(portfolio_returns[-20:]) * np.sqrt(252) * 100)
        vol_60 = float(np.std(portfolio_returns[-60:]) * np.sqrt(252) * 100) if len(portfolio_returns) >= 60 else vol_20

        cum = np.cumprod(1 + portfolio_returns)
        peak = np.maximum.accumulate(cum)
        dd = (cum - peak) / peak
        max_dd = float(abs(np.min(dd)) * 100)

        daily_rf = 0.03 / 252
        excess = portfolio_returns - daily_rf
        sharpe = float(np.mean(excess) / np.std(portfolio_returns) * np.sqrt(252)) if np.std(portfolio_returns) > 0 else 0

        var_95 = float(abs(np.percentile(portfolio_returns, 5)) * 100)

        return PortfolioRisk(
            volatility_20d=round(vol_20, 2),
            volatility_60d=round(vol_60, 2),
            max_drawdown=round(max_dd, 2),
            sharpe_ratio=round(sharpe, 2),
            var_95=round(var_95, 2),
        )

    def get_industry_distribution(self, portfolio_id: str) -> Dict[str, float]:
        positions = self.get_positions(portfolio_id)
        industry_mv: Dict[str, float] = {}

        for pos in positions:
            ind = pos.industry or "未知"
            industry_mv[ind] = industry_mv.get(ind, 0) + pos.market_value

        total = sum(industry_mv.values())
        if total > 0:
            return {k: round(v / total * 100, 2) for k, v in sorted(industry_mv.items(), key=lambda x: -x[1])}
        return {}

    def suggest_rebalance(self, portfolio_id: str, target_count: int = 8) -> List[dict]:
        positions = self.get_positions(portfolio_id)
        summary = self.get_summary(portfolio_id)
        if not positions or not summary:
            return []

        suggestions = []
        total_mv = summary.total_market_value

        heavy = [p for p in positions if p.weight > 0.2]
        for p in heavy:
            target_weight = 1.0 / target_count
            target_value = total_mv * target_weight
            reduce_value = p.market_value - target_value
            reduce_shares = int(reduce_value / p.current_price / 100) * 100
            if reduce_shares > 0:
                suggestions.append({
                    "action": "reduce",
                    "ts_code": p.ts_code,
                    "stock_name": p.stock_name,
                    "current_weight": round(p.weight * 100, 2),
                    "target_weight": round(target_weight * 100, 2),
                    "suggested_shares": reduce_shares,
                    "reason": f"仓位过重({p.weight*100:.1f}%)，建议分散",
                })

        if len(positions) < target_count:
            suggestions.append({
                "action": "diversify",
                "ts_code": "",
                "stock_name": "",
                "current_weight": 0,
                "target_weight": round(100.0 / target_count, 2),
                "suggested_shares": 0,
                "reason": f"当前仅{len(positions)}只股票，建议增加到{target_count}只以分散风险",
            })

        lossers = [p for p in positions if p.profit_pct < -15]
        for p in lossers:
            suggestions.append({
                "action": "review",
                "ts_code": p.ts_code,
                "stock_name": p.stock_name,
                "current_weight": round(p.weight * 100, 2),
                "target_weight": 0,
                "suggested_shares": 0,
                "reason": f"深度套牢({p.profit_pct:.1f}%)，建议重新评估基本面",
            })

        return suggestions


_portfolio_service: Optional[PortfolioService] = None


def get_portfolio_service() -> PortfolioService:
    global _portfolio_service
    if _portfolio_service is None:
        _portfolio_service = PortfolioService()
    return _portfolio_service
