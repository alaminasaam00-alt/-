from fastapi import FastAPI
from datetime import datetime, timezone
import os

app = FastAPI(title="NEXUS AI E-Agent API", version="0.1.0")

@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "nexus-api",
        "trading_mode": os.getenv("TRADING_MODE", "disabled"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/v1/status")
def status():
    return {
        "service": "nexus-api",
        "environment": os.getenv("BINANCE_ENV", "testnet"),
        "trading_mode": os.getenv("TRADING_MODE", "disabled"),
        "live_orders_enabled": False,
        "withdrawals_enabled": False,
    }
