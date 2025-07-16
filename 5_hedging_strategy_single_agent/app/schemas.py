from __future__ import annotations
from typing import List, Dict, Optional
from pydantic import BaseModel, Field, confloat

# ---------- Investor / portfolio input ---------- #
class Position(BaseModel):
    ticker: str
    instrument_type: str = "stock"      # stock, etf, option, etc.
    amount_usd: float
    stop_loss: Optional[float] = None

class InvestorProfile(BaseModel):
    experience_level: str = Field(..., regex="^(Beginner|Intermediate|Expert)$")
    explanation_pref: str = Field(..., regex="^(Just the strategy|Explain the reasoning|Both)$")
    time_horizon_months: int = Field(..., ge=1, le=24)
    allowed_instruments: List[str]

class StrategyRequest(BaseModel):
    profile: InvestorProfile
    positions: List[Position]
    avoid_overlap: bool = True          # same meaning as before

# ---------- Strategy output ---------- #
class HedgeLine(BaseModel):
    ticker: str
    rationale: str
    notional_usd: float
    pct_capital: confloat(ge=0, le=100)
    source: str

class StrategyResponse(BaseModel):
    markdown: str               # the full markdown generated
    hedges: List[HedgeLine]

# ---------- Quick-chat ---------- #
class ChatRequest(BaseModel):
    question: str
    positions: List[str]

class ChatResponse(BaseModel):
    answer: str

# ---------- Risk headlines ---------- #
class RiskItem(BaseModel):
    headline: str
    url: str

class RiskResponse(BaseModel):
    ticker: str
    risks: List[RiskItem]
