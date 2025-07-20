
from fastapi import FastAPI
from routers import strategy

app = FastAPI()
app.include_router(strategy.router)
