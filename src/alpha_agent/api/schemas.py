from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal


class HealthResponse(BaseModel):
    status: str
    version: str
    data_source: str
    llm_available: bool
    redis_enabled: bool
    db_enabled: bool


class ChatRequest(BaseModel):
    thread_id: str = Field("default", description="会话ID，用于保持上下文")
    message: str = Field(..., description="用户消息")


class ChatResponse(BaseModel):
    thread_id: str
    response: str
    tool_calls: List[str] = Field(default_factory=list)


class BacktestRequest(BaseModel):
    ts_code: str
    days: int = 500
    initial_capital: float = 100000.0


class BacktestResponse(BaseModel):
    ts_code: str
    period: str
    total_return_pct: float
    annual_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    profit_loss_ratio: float


class CompareRequest(BaseModel):
    ts_codes: List[str]


class CompareRow(BaseModel):
    rank: int
    ts_code: str
    final_score: float
    final_rating: str
    fundamental_score: float
    technical_score: float
    risk_control_score: float
    position_pct: str


class CompareResponse(BaseModel):
    count: int
    success_count: int
    results: List[CompareRow]


class QuoteResponse(BaseModel):
    ts_code: str
    name: str
    price: float
    change_pct: float
    change: float
    open: float
    high: float
    low: float
    prev_close: float
    volume: str
    amount: str


class NewsItem(BaseModel):
    title: str
    pub_time: str
    source: Optional[str] = None


class NewsResponse(BaseModel):
    ts_code: str
    items: List[NewsItem]


class AlertCreateRequest(BaseModel):
    ts_code: str
    alert_type: Literal["price_above", "price_below", "change_above", "change_below", "volume_above"]
    threshold: float


class AlertItem(BaseModel):
    id: str
    ts_code: str
    alert_type: str
    threshold: float
    triggered: bool
    triggered_price: Optional[float] = None


class AlertsResponse(BaseModel):
    items: List[AlertItem]


class PortfolioCreateRequest(BaseModel):
    name: str = Field(..., description="组合名称")
    description: str = ""
    initial_capital: float = 100000.0


class PortfolioInfo(BaseModel):
    portfolio_id: str
    name: str
    description: str
    initial_capital: float
    position_count: int


class PortfolioListResponse(BaseModel):
    items: List[PortfolioInfo]


class PositionAddRequest(BaseModel):
    ts_code: str
    shares: int
    cost_price: float


class PositionItem(BaseModel):
    ts_code: str
    stock_name: str
    shares: int
    cost_price: float
    current_price: float
    market_value: float
    weight: float
    profit: float
    profit_pct: float
    industry: str = ""


class PortfolioSummaryResponse(BaseModel):
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
    positions: List[PositionItem]


class PortfolioRiskResponse(BaseModel):
    volatility_20d: float
    volatility_60d: float
    max_drawdown: float
    sharpe_ratio: float
    var_95: float


class IndustryDistributionItem(BaseModel):
    industry: str
    pct: float


class IndustryDistributionResponse(BaseModel):
    items: List[IndustryDistributionItem]


class RebalanceSuggestionItem(BaseModel):
    action: str
    ts_code: str
    stock_name: str
    current_weight: float
    target_weight: float
    suggested_shares: int = 0
    reason: str


class RebalanceSuggestionResponse(BaseModel):
    items: List[RebalanceSuggestionItem]


class ConversationItem(BaseModel):
    session_id: str
    user_query: str
    analysis_type: str
    status: str
    created_at: str
    duration_ms: int = 0
    total_steps: int = 0


class ConversationListResponse(BaseModel):
    items: List[ConversationItem]


class ConversationMessage(BaseModel):
    role: str
    content: str


class ConversationDetailResponse(BaseModel):
    session_id: str
    user_query: str
    analysis_type: str
    status: str
    created_at: str
    final_result: str
    duration_ms: int = 0
    total_steps: int = 0
    messages: List[ConversationMessage] = []