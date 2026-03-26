"""
Structured JSON Logging Module for PosterShop Services

Features:
- JSON-formatted log output (for Loki/Fluent Bit ingestion)
- Correlation ID propagation across requests
- Request context middleware for FastAPI
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL

Usage:
    from logger import get_logger, LoggingMiddleware, get_correlation_id

    # In FastAPI app setup
    app.add_middleware(LoggingMiddleware)

    # Get a logger
    logger = get_logger(__name__)
    logger.info("Order created", order_id=123, customer="test@example.com")
"""

import json
import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Context variable for correlation ID (propagates across async calls)
correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
request_path_var: ContextVar[Optional[str]] = ContextVar("request_path", default=None)

# Standard correlation ID headers
CORRELATION_ID_HEADERS = ["X-Correlation-ID", "X-Request-ID", "X-Trace-ID"]


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID from context."""
    return correlation_id_var.get()


def set_correlation_id(cid: str) -> None:
    """Set the correlation ID in context."""
    correlation_id_var.set(cid)


class JSONFormatter(logging.Formatter):
    """
    Formats log records as JSON for structured logging.
    Compatible with Loki, Fluent Bit, CloudWatch Logs Insights.
    """

    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add correlation ID if present
        cid = correlation_id_var.get()
        if cid:
            log_entry["correlation_id"] = cid

        # Add request path if present
        path = request_path_var.get()
        if path:
            log_entry["path"] = path

        # Add extra fields passed via logger.info("msg", extra={...})
        # or via our custom StructuredLogger
        if hasattr(record, "structured_data"):
            log_entry.update(record.structured_data)

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add source location for errors
        if record.levelno >= logging.ERROR:
            log_entry["location"] = {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            }

        return json.dumps(log_entry, default=str)


class StructuredLogger(logging.LoggerAdapter):
    """
    Logger adapter that supports structured key-value logging.
    
    Usage:
        logger.info("User logged in", user_id=123, ip="1.2.3.4")
    """

    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:
        # Extract structured data from kwargs
        structured_data = {}
        extra = kwargs.get("extra", {})
        
        # Move non-standard kwargs to structured_data
        standard_keys = {"exc_info", "stack_info", "stacklevel", "extra"}
        for key in list(kwargs.keys()):
            if key not in standard_keys:
                structured_data[key] = kwargs.pop(key)
        
        # Merge with any existing extra
        if structured_data:
            extra["structured_data"] = {**extra.get("structured_data", {}), **structured_data}
            kwargs["extra"] = extra
        
        return msg, kwargs


def get_logger(name: str, service_name: Optional[str] = None) -> StructuredLogger:
    """
    Get a structured logger for a module.
    
    Args:
        name: Logger name (typically __name__)
        service_name: Service name for log entries (auto-detected from SERVICE_NAME env var)
    
    Returns:
        StructuredLogger instance
    """
    service = service_name or os.getenv("SERVICE_NAME", "unknown")
    
    logger = logging.getLogger(name)
    
    # Only configure if not already configured
    if not logger.handlers:
        logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
        
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter(service))
        logger.addHandler(handler)
        
        # Prevent propagation to root logger (avoid duplicate logs)
        logger.propagate = False
    
    return StructuredLogger(logger, {})


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    FastAPI middleware for request logging and correlation ID propagation.
    
    - Extracts or generates correlation ID
    - Logs request start/end with timing
    - Adds correlation ID to response headers
    """

    async def dispatch(self, request: Request, call_next):
        # Extract correlation ID from headers or generate new one
        correlation_id = None
        for header in CORRELATION_ID_HEADERS:
            correlation_id = request.headers.get(header)
            if correlation_id:
                break
        
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
        
        # Set context variables
        correlation_id_var.set(correlation_id)
        request_path_var.set(request.url.path)
        
        # Store in request state for access in route handlers
        request.state.correlation_id = correlation_id
        
        logger = get_logger("http")
        
        start_time = time.perf_counter()
        
        # Log request start (DEBUG level to reduce noise)
        logger.debug(
            "Request started",
            method=request.method,
            path=request.url.path,
            client_ip=request.client.host if request.client else None,
        )
        
        try:
            response = await call_next(request)
            
            duration_ms = (time.perf_counter() - start_time) * 1000
            
            # Log request completion
            log_method = logger.warning if response.status_code >= 400 else logger.info
            log_method(
                "Request completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
            )
            
            # Add correlation ID to response headers
            response.headers["X-Correlation-ID"] = correlation_id
            
            return response
            
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "Request failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 2),
                error=str(e),
                exc_info=True,
            )
            raise
        finally:
            # Clear context
            correlation_id_var.set(None)
            request_path_var.set(None)


def configure_uvicorn_logging(service_name: str) -> dict:
    """
    Returns uvicorn logging config for JSON output.
    
    Usage in main.py:
        import uvicorn
        from logger import configure_uvicorn_logging
        
        if __name__ == "__main__":
            uvicorn.run(
                "main:app",
                log_config=configure_uvicorn_logging("orders"),
            )
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": JSONFormatter,
                "service_name": service_name,
            },
        },
        "handlers": {
            "default": {
                "formatter": "json",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
        },
    }
