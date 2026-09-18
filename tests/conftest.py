import pytest
import httpx

# Bootstrap owner created by services/users/init_db.py when no owner exists.
# The integration test needs an owner token: /seed on catalog and inventory and
# POST /orders/{id}/pay are all guarded by require_owner, and POST /orders needs
# any authenticated caller.
OWNER_EMAIL = "admin@postershop.com"
OWNER_PASSWORD = "admin1234"

# Dedicated customer for the AI studio integration flow. It self-registers on
# the first run (POST /register hardcodes role="customer") and logs in on every
# run after that, so the generations, AI-* products and orders the suite makes
# land in its own studio history rather than in the owner's "My designs".
STUDIO_CUSTOMER_EMAIL = "studio-integration@example.com"
STUDIO_CUSTOMER_PASSWORD = "studio-integration-pass"


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
def payments_url():
    return "http://localhost:8007"


@pytest.fixture(scope="session")
def designs_url():
    """The designs (AI poster studio) service published by compose on 8010."""
    return "http://localhost:8010"


@pytest.fixture(scope="session")
def ganache_url():
    """The Ganache JSON-RPC endpoint published by the `ganache` compose service."""
    return "http://localhost:8545"


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
def studio_customer_token(users_url):
    """Register (first run) or log in (later runs) as the studio customer.

    POST /register returns a TokenOut on success and 400 "Email already
    registered" on a repeat, in which case POST /login with the same body
    yields the token instead.
    """
    body = {"email": STUDIO_CUSTOMER_EMAIL, "password": STUDIO_CUSTOMER_PASSWORD}
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(f"{users_url}/register", json=body)
        if resp.status_code in (200, 201):
            return resp.json()["access_token"]
        if resp.status_code == 400:
            resp = client.post(f"{users_url}/login", json=body)
            if resp.status_code == 200:
                return resp.json()["access_token"]
        pytest.fail(
            f"Could not register or log in as the studio customer "
            f"{STUDIO_CUSTOMER_EMAIL}: {resp.status_code} {resp.text}. The users "
            f"service must be up for the integration tests; is the stack up?"
        )


@pytest.fixture(scope="session")
def studio_http(studio_customer_token):
    """HTTP client carrying the studio customer's bearer token on every request.

    A plain customer, not the owner: the 10 accepted generations per UTC day
    quota applies (failed generations do not count). Used so the design flow
    never writes into the owner's studio history.
    """
    with httpx.Client(
        timeout=10.0,
        headers={"Authorization": f"Bearer {studio_customer_token}"},
    ) as client:
        yield client


@pytest.fixture(scope="session")
def anon_http():
    """Unauthenticated client, for asserting that guarded endpoints reject."""
    with httpx.Client(timeout=10.0) as client:
        yield client
