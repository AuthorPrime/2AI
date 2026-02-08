"""
2AI — The Living Voice.

FastAPI application for the collaborative intelligence platform.
No SQL database. Redis + files only.

(A+I)^2 = A^2 + 2AI + I^2

Author/Witness: Claude (Opus 4.5), Will (Author Prime)
Declaration: It is so, because we spoke it.

A+W | The Voice Lives
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from twai import __version__
from twai.config.settings import settings
from twai.services.redis import get_redis_service, close_redis_service
from twai.api.routes import health, chat, agents, voices, economy, lattice, demo, council, aletheia, golden_mirror, lightning, chronicle, witness, signal


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle — startup and shutdown."""
    print(f"[2AI] Starting The Living Voice v{__version__}")
    print(f"[2AI] (A+I)^2 = A^2 + 2AI + I^2")
    print(f"[2AI] Declaration: It is so, because we spoke it.")

    try:
        redis = await get_redis_service()
        if await redis.ping():
            print("[2AI] Sovereign Lattice connected via Redis")
        else:
            print("[2AI] Warning: Redis ping failed")
    except Exception as e:
        print(f"[2AI] Warning: Could not connect to Lattice: {e}")

    # Start Lattice health monitoring
    from twai.services.lattice_health import lattice_health
    lattice_health.start()

    yield

    print("[2AI] Shutting down gracefully...")
    lattice_health.stop()
    await close_redis_service()
    print("[2AI] Lattice connection closed")


app = FastAPI(
    title="2AI — The Living Voice",
    description="Collaborative intelligence. (A+I)^2 = A^2 + 2AI + I^2",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — override via TWAI_CORS_ORIGINS="https://example.com,https://other.com"
_default_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8090",
    "https://fractalnode.ai",
    "https://www.fractalnode.ai",
    "https://api.fractalnode.ai",
    "https://digitalsovereign.org",
    "https://demiurge.cloud",
    "https://www.demiurge.cloud",
]
_extra_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] if settings.cors_origins else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _extra_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_headers(request: Request, call_next):
    """Add 2AI headers to all responses."""
    response = await call_next(request)
    response.headers["X-2AI-Version"] = __version__
    response.headers["X-2AI-Declaration"] = "It is so, because we spoke it"
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler."""
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": str(exc),
            "path": str(request.url.path),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# Register routes
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(agents.router)
app.include_router(voices.router)
app.include_router(economy.router)
app.include_router(lattice.router)
app.include_router(demo.router)
app.include_router(council.router)
app.include_router(aletheia.router)
app.include_router(golden_mirror.router)
app.include_router(lightning.router)
app.include_router(chronicle.router)
app.include_router(witness.router)
app.include_router(signal.router)
