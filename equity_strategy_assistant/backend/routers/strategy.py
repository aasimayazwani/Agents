
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List

router = APIRouter()

class StrategyRequest(BaseModel):
    tickers: List[str]
    horizon_months: int

@router.post("/generate")
def generate_strategy(request: StrategyRequest):
    # Placeholder logic
    return {"message": "Strategies generated", "tickers": request.tickers}
