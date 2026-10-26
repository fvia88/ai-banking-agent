# backend/app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contracts.models import ErrorResponse
from app.config import settings
from app.api import health, accounts, transactions, chat, approvals, audit, subscriptions, demo_inbox, continuation

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS setup for future frontend milestone
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Standardized Error Handling
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            code="INTERNAL_SERVER_ERROR",
            message=str(exc),
            request_id=request.headers.get("x-request-id", "req_unknown")
        ).model_dump()
    )

# Include routers under /api/v1
app.include_router(health.router, prefix=settings.API_V1_PREFIX, tags=["Health"])
app.include_router(accounts.router, prefix=settings.API_V1_PREFIX, tags=["Accounts"])
app.include_router(transactions.router, prefix=settings.API_V1_PREFIX, tags=["Transactions"])
app.include_router(chat.router, prefix=settings.API_V1_PREFIX, tags=["Chat"])
app.include_router(approvals.router, prefix=settings.API_V1_PREFIX, tags=["Approvals"])
app.include_router(audit.router, prefix=settings.API_V1_PREFIX, tags=["Audit"])
app.include_router(subscriptions.router, prefix=settings.API_V1_PREFIX, tags=["Subscriptions"])
app.include_router(demo_inbox.router, prefix=settings.API_V1_PREFIX, tags=["Demo Inbox"])
app.include_router(continuation.router, prefix=settings.API_V1_PREFIX, tags=["Chat"])
