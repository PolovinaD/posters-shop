import pytest
import httpx

# Bootstrap owner created by services/users/init_db.py when no owner exists.
# The integration test needs an owner token: /seed on catalog and inventory and
# POST /orders/{id}/pay are all guarded by require_owner, and POST /orders needs
# any authenticated caller.
OWNER_EMAIL = "admin@postershop.com"
OWNER_PASSWORD = "admin1234"


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
def logistics_url():
    return "http://localhost:8005"


@pytest.fixture(scope="session")
def inventory_url():
    return "http://localhost:8006"


@pytest.fixture(scope="session")
def owner_token(users_url):
    """Log in as the bootstrap owner and return an access token.

    Registering instead would not help: POST /register hardcodes role="customer"
    (services/users/main.py:87), and the flow needs owner-only endpoints.
    """
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            f"{users_url}/login",
            json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
        )
        if resp.status_code != 200:
            pytest.fail(
                f"Could not log in as the bootstrap owner {OWNER_EMAIL}: "
                f"{resp.status_code} {resp.text}. The users service creates it on "
                f"startup (services/users/init_db.py); is the stack up?"
            )
        return resp.json()["access_token"]


@pytest.fixture(scope="session")
def http(owner_token):
    """HTTP client carrying the owner bearer token on every request."""
    with httpx.Client(
        timeout=10.0,
        headers={"Authorization": f"Bearer {owner_token}"},
    ) as client:
        yield client


@pytest.fixture(scope="session")
def anon_http():
    """Unauthenticated client, for asserting that guarded endpoints reject."""
    with httpx.Client(timeout=10.0) as client:
        yield client
