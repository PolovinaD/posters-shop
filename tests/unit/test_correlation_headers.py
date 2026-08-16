"""Unit tests for correlation_headers() and shared-logger copy drift."""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SHARED_LOGGER = REPO_ROOT / "services" / "shared" / "logger.py"
SERVICES = [
    "catalog", "infra", "inventory", "logistics", "notifications",
    "orders", "payments", "production", "users",
]


@pytest.fixture
def shared_logger():
    """Load services/shared/logger.py under a unique module name."""
    spec = importlib.util.spec_from_file_location("correlation_shared_logger", SHARED_LOGGER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["correlation_shared_logger"] = module
    spec.loader.exec_module(module)
    token = module.correlation_id_var.set(None)
    yield module
    module.correlation_id_var.reset(token)
    sys.modules.pop("correlation_shared_logger", None)


def test_returns_empty_dict_when_no_correlation_id(shared_logger):
    """Safe to call from background workers and at import time."""
    assert shared_logger.correlation_headers() == {}


def test_returns_header_when_correlation_id_set(shared_logger):
    shared_logger.set_correlation_id("abc-123")
    assert shared_logger.correlation_headers() == {"X-Correlation-ID": "abc-123"}


def test_header_name_is_one_the_middleware_reads_back(shared_logger):
    shared_logger.set_correlation_id("xyz")
    (name,) = shared_logger.correlation_headers().keys()
    assert name in shared_logger.CORRELATION_ID_HEADERS


def test_service_logger_copies_match_shared():
    """All nine per-service copies must stay byte-identical to shared."""
    expected = SHARED_LOGGER.read_bytes()
    for svc in SERVICES:
        copy = REPO_ROOT / "services" / svc / "logger.py"
        assert copy.read_bytes() == expected, f"{svc}/logger.py drifted from shared/logger.py"
