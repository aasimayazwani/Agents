from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .schemas import (
    StrategyRequest,
    StrategyResponse,
    ChatRequest,
    ChatResponse,
    RiskResponse,
)
from .services import (
    build_strategy,
    get_headline_risks,
    ask_chatbot,
)

app = FastAPI(
    title="Equity Strategy API",
    version="0.1.0",
    description="REST interface for portfolio hedging & quick chat",
)

# Allow local dev UIs (React / Vue / etc.)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=["*"],
    allow_methods=["*"],
)

@app.post("/strategy", response_model=StrategyResponse)
async def generate_strategy(req: StrategyRequest):
    """Return a hedge strategy markdown + sizing table."""
    try:
        return await build_strategy(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat", response_model=ChatResponse)
async def quick_chat(req: ChatRequest):
    """GPT powered quick Q&A about the portfolio."""
    try:
        return await ask_chatbot(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/risk/{ticker}", response_model=RiskResponse)
async def risks(ticker: str):
    """Headline-risk scan for a single ticker."""
    try:
        return await get_headline_risks(ticker.upper())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
