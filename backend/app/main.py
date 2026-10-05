"""
3D Reel Studio — FastAPI Main Application Entrypoint
Phase 2: FastAPI Backend Foundation
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.logging import logger
from app.db.session import init_db, SessionLocal
from app.schemas.response import APIErrorDetail, APIErrorResponse, RootResponse
from app.services.maintenance import reconcile_stale_jobs_on_startup


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifecycle manager for startup and shutdown event hooks.
    """
    logger.info("==================================================")
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Environment: {settings.ENVIRONMENT} | Debug: {settings.DEBUG}")
    logger.info(f"CORS Origins: {settings.CORS_ORIGINS}")
    logger.info(f"Docs available at: http://{settings.HOST}:{settings.PORT}/docs")
    logger.info("==================================================")
    
    # Initialize SQLite database and tables
    init_db()

    # Reconcile any background jobs interrupted by prior shutdown
    db = SessionLocal()
    try:
        reconcile_stale_jobs_on_startup(db)
    finally:
        db.close()
    
    yield

    from app.services.worker import worker_manager
    worker_manager.shutdown()
    logger.info(f"Shutting down {settings.APP_NAME}... Clean lifecycle complete.")


docs_url = "/docs" if settings.DOCS_ENABLED else None
redoc_url = "/redoc" if settings.DOCS_ENABLED else None
openapi_url = "/openapi.json" if settings.DOCS_ENABLED else None

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=settings.APP_DESCRIPTION,
    lifespan=lifespan,
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
)

# -------------------------------------------------------------------
# SECURITY HEADERS & CORS MIDDLEWARE CONFIGURATION
# -------------------------------------------------------------------
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Adds standard production security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


cors_origins = settings.CORS_ORIGINS
allow_creds = True
if settings.ENVIRONMENT == "production" and ("*" in cors_origins or cors_origins == ["*"]):
    logger.warning("CORS wildcard origin in production mode: restricting wildcard credentials.")
    allow_creds = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=allow_creds,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------------
# GLOBAL EXCEPTION HANDLERS
# -------------------------------------------------------------------
@app.exception_handler(StarletteHTTPException)
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException | StarletteHTTPException) -> JSONResponse:
    """
    Handles standard HTTP exceptions with structured JSON error payloads.
    """
    logger.warning(f"HTTP {exc.status_code} on {request.method} {request.url.path}: {exc.detail}")
    
    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        429: "TOO_MANY_REQUESTS",
        500: "INTERNAL_SERVER_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }
    error_code = code_map.get(exc.status_code, "HTTP_ERROR")
    error_msg = "An HTTP error occurred."
    details = None

    if isinstance(exc.detail, dict):
        error_code = exc.detail.get("code", error_code)
        error_msg = exc.detail.get("message", str(exc.detail))
        details = exc.detail.get("details", None)
    elif exc.detail:
        error_msg = str(exc.detail)

    error_payload = APIErrorResponse(
        success=False,
        error=APIErrorDetail(
            code=error_code,
            message=error_msg,
            details=details,
        ),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload.model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Handles request body and query parameter validation errors.
    """
    logger.warning(f"Validation error on {request.method} {request.url.path}: {exc.errors()}")
    
    formatted_errors = []
    sanitized_details = []
    for err in exc.errors():
        loc = " -> ".join([str(p) for p in err.get("loc", [])])
        msg = err.get("msg", "Invalid value")
        formatted_errors.append(f"{loc}: {msg}")
        sanitized_details.append({
            "loc": [str(p) for p in err.get("loc", [])],
            "msg": msg,
            "type": err.get("type", "value_error"),
        })
    
    summary = "; ".join(formatted_errors) if formatted_errors else "Invalid request payload parameters."

    error_payload = APIErrorResponse(
        success=False,
        error=APIErrorDetail(
            code="VALIDATION_ERROR",
            message=summary,
            details=sanitized_details,
        ),
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_payload.model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all exception handler to ensure raw tracebacks are never exposed to clients.
    """
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {str(exc)}", exc_info=True)
    
    error_payload = APIErrorResponse(
        success=False,
        error=APIErrorDetail(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected error occurred. Please check server logs.",
        ),
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_payload.model_dump(),
    )


# -------------------------------------------------------------------
# ROOT ENDPOINT
# -------------------------------------------------------------------
@app.get(
    "/",
    response_model=RootResponse,
    status_code=status.HTTP_200_OK,
    summary="Root API Endpoint",
    description="Returns basic application status and documentation URL.",
)
async def root() -> RootResponse:
    """
    Root status endpoint confirming API is running.
    """
    return RootResponse(
        success=True,
        message="3D Reel Studio API is running",
        docs="/docs",
    )


# -------------------------------------------------------------------
# ROUTER MOUNTING
# -------------------------------------------------------------------
from app.api.v1.health import router as health_router

app.include_router(health_router, tags=["Health & Readiness"])
app.include_router(api_v1_router, prefix=settings.API_PREFIX)
