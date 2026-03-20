"""Marketplace Service main application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import Base, engine
from . import models  # Ensure models are registered
from .routers import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield
    
    # Shutdown
    await engine.dispose()


app = FastAPI(
    title="Marketplace Service",
    description="Agent marketplace for listing, purchasing, and reviewing AI agents",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
async def root_health():
    """Root health check."""
    return {"service": "marketplace", "status": "ok"}
