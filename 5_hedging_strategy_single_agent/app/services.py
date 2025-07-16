from __future__ import annotations
import re, textwrap, pandas as pd
from typing import List
from datetime import datetime

from .schemas import (
    StrategyRequest, StrategyResponse,
    HedgeLine, RiskResponse, RiskItem,
    ChatRequest, ChatResponse,
)
from .openai_client import ask_openai
from .stock_utils import get_stock_summary
from .config import DEFAULT_MODEL
import yfinance as yf, os, requests

# ----- small helpers reused from Streamlit version ----- #
def _fetch_prices(tickers: List[str]):
    df = yf.download(tickers, period="2d", progress=False)["Close"]
    return df.iloc[-1], df.iloc[-2]   # last, previous

def _web_risk_scan(ticker: str):
    key = os.getenv("NEWSAPI_KEY")
    if not key:
        return [("No NEWSAPI_KEY set", "#")]
    query = f'"{ticker}" AND (analyst OR downgrade OR risk OR cut)'
    url = "https://newsapi.org/v2/everything"
    params = dict(q=query, language="en", sortBy="publishedAt",
                  pageSize=15, apiKey=key)
    try:
        data = requests.get(url, params=params, timeout=8).json()
        arts = data.get("articles", [])
        out = []
        for a in arts:
            title = a.get("title", "")
            if any(k in title.lower() for k in
                   ["downgrade", "risk", "concern", "slashed"]):
                out.append((title, a.get("url", "#")))
            if len(out) >= 5:
                break
        return out or [("No major risk headlines found.", "#")]
    except Exception as e:
        return [(f"Error: {e}", "#")]

# ---------- core tasks ---------- #
async def build_strategy(req: StrategyRequest) -> StrategyResponse:
    # 1. Basic numbers
    cap = sum(p.amount_usd for p in req.positions)
    tickers = [p.ticker.upper() for p in req.positions]

    # 2. Risk string
    risk_headlines = []
    for t in tickers:
        headlines = _web_risk_scan(t)[:1]    # first headline only
        risk_headlines.extend(h[0] for h in headlines)

    risk_string = ", ".join(risk_headlines) or "None"

    # 3. Build the same big prompt (shortened here!)
    prompt = f"""
Portfolio: {', '.join(tickers)}
Capital: ${cap:,.0f}
Risk notes: {risk_string}
Allowed instruments: {', '.join(req.profile.allowed_instruments)}
Horizon: {req.profile.time_horizon_months} m

Return ONE hedge idea (markdown) ≤ 40 words.
"""

    md = ask_openai(
        model=DEFAULT_MODEL,
        system_prompt="You output concise hedge ideas only.",
        user_prompt=prompt,
    )

    hedge = HedgeLine(
        ticker="N/A",
        rationale=md,
        notional_usd=0,
        pct_capital=0,
        source="N/A",
    )

    return StrategyResponse(markdown=md, hedges=[hedge])


async def ask_chatbot(req: ChatRequest) -> ChatResponse:
    ctx = f"Portfolio tickers: {', '.join(req.positions)}."
    ans = ask_openai(
        DEFAULT_MODEL,
        system_prompt="Helpful market analyst.",
        user_prompt=ctx + "\n\nUser question: " + req.question,
    )
    return ChatResponse(answer=ans)


async def get_headline_risks(ticker: str) -> RiskResponse:
    items = [RiskItem(headline=h, url=u) for h, u in _web_risk_scan(ticker)]
    return RiskResponse(ticker=ticker, risks=items)
