import pytest
import httpx


@pytest.fixture(scope="session")
def users_url():
    return "http://localhost:8001"


@pytest.fixture(scope="session")
def catalog_url():
    return "http://localhost:8002"


@pytest.fixture(scope="session")
def orders_url():
    return "http://localhost:8003"


@pytest.fixture(scope="session")
def inventory_url():
    return "http://localhost:8006"


@pytest.fixture(scope="session")
def http():
    with httpx.Client(timeout=10.0) as client:
        yield client
