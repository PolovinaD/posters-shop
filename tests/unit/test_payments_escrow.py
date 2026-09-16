"""Unit tests for ESC-02 / ESC-07: the payments escrow provider and its endpoints.

No chain is needed. The provider half drives services/payments/escrow.py with a
MagicMock standing in for web3's ``Web3`` object; the endpoint half loads
payments/main.py the way test_stripe_payments.py does and swaps the provider
for an in-memory fake that walks the same state machine as OrderEscrow.sol.
"""
import importlib.util
import json
import os
import pathlib
import sys
import types
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from eth_account import Account
from web3 import Web3
from web3.exceptions import ContractLogicError

REPO = pathlib.Path(__file__).parents[2]
PAYMENTS_DIR = REPO / "services/payments"
ARTIFACT_PATH = PAYMENTS_DIR / "contracts/OrderEscrow.json"

# A fixed dev key that is NOT a Ganache account (so startup funding is exercised).
OWNER_KEY = "0x4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318"
OWNER = "0x2c7536E3605D9C16a7a3D7b1898e529396a65c23"
CUST = Web3.to_checksum_address("0x" + "11" * 20)
COURIER = "0x" + "22" * 20
ADDR = "0x" + "ab" * 20
GANACHE_0 = "0x90f8bf6a479f320ead074411a4b0e7944ea8c9c1"

# escrow.py reads the owner key at import time; set it before the module loads.
os.environ["ESCROW_OWNER_PRIVATE_KEY"] = OWNER_KEY

# --- Stub logger so escrow.py / main.py import without the service dir on the path ---
from starlette.middleware.base import BaseHTTPMiddleware  # noqa: E402


class _NoopLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        return await call_next(request)


_logger_stub = types.ModuleType("logger")
_logger_stub.get_logger = MagicMock(return_value=MagicMock())
_logger_stub.LoggingMiddleware = _NoopLoggingMiddleware
sys.modules.setdefault("logger", _logger_stub)


def _load_escrow():
    """Load services/payments/escrow.py under a unique module name."""
    sys.path.insert(0, str(PAYMENTS_DIR))
    try:
        spec = importlib.util.spec_from_file_location("payments_escrow", PAYMENTS_DIR / "escrow.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(PAYMENTS_DIR))
    return mod


esc = _load_escrow()


@pytest.fixture
def artifact():
    with open(ARTIFACT_PATH) as f:
        return json.load(f)


def _fake_w3(chain_id: int = 1337) -> MagicMock:
    w3 = MagicMock()
    w3.eth.chain_id = chain_id
    w3.is_connected.return_value = True
    w3.client_version = "Ganache/v7.9.2/EthereumJS TestRPC/v0.0.0/ethereum-js"
    return w3


def _provider(w3, artifact):
    return esc.EscrowProvider(w3, OWNER_KEY, artifact)


# ============== pure helpers ==============

def test_usd_to_wei_uses_fixed_rate():
    """ESC-02: amount_wei = Decimal(usd) * WEI_PER_USD, exact even for floats."""
    assert esc.usd_to_wei(Decimal("12.50"), wei_per_usd=10**15) == 12_500_000_000_000_000
    assert esc.usd_to_wei("0.01", wei_per_usd=10**15) == 10_000_000_000_000
    assert esc.usd_to_wei(19.99, wei_per_usd=10**15) == 19_990_000_000_000_000


def test_state_name_mapping():
    """ESC-02: index == Solidity enum value."""
    assert esc.STATE_NAMES == ["awaiting_payment", "funded", "in_delivery", "released", "cancelled"]


def test_demo_accounts_are_derived_from_mnemonic():
    """ESC-02: Ganache's deterministic keys are derived at runtime, never hardcoded."""
    accs = esc.demo_accounts()

    assert len(accs) == 10
    assert accs[0]["index"] == 0
    assert accs[0]["address"].lower() == GANACHE_0
    assert accs[1]["address"].lower() == "0xffcf8fdee72ac11b5c542428b35eef5769c409f0"
    assert accs[2]["address"].lower() == "0x22d491bde2303f2f43325b2108d26f1eaba1e32b"
    for a in accs:
        assert a["private_key"].startswith("0x") and len(a["private_key"]) == 66
    assert Account.from_key(accs[1]["private_key"]).address.lower() == accs[1]["address"].lower()


def test_revert_reason_strips_prefix():
    """ESC-02: the bare require() string is what reaches the HTTP 409."""
    assert esc.revert_reason(ContractLogicError("execution reverted: Transfer not complete.")) == "Transfer not complete."
    assert esc.revert_reason(ContractLogicError("Something else")) == "Something else"


# ============== EscrowProvider against a fake Web3 ==============

def test_ensure_owner_funded_tops_up_from_account0(artifact):
    """ESC-02: an owner below the threshold is funded from Ganache's first unlocked account."""
    w3 = _fake_w3()
    w3.eth.accounts = [GANACHE_0]
    w3.eth.get_balance.return_value = 0
    p = _provider(w3, artifact)

    assert p.ensure_owner_funded(min_eth=Decimal("10"), topup_eth=Decimal("100")) is True

    w3.eth.send_transaction.assert_called_once()
    tx = w3.eth.send_transaction.call_args[0][0]
    assert tx["from"] == GANACHE_0
    assert tx["to"] == p.owner_address
    assert tx["value"] == 100 * 10**18


def test_ensure_owner_funded_skips_when_rich_or_no_unlocked_accounts(artifact):
    """ESC-02: no top-up when the owner is rich, and never on a node without unlocked accounts."""
    w3 = _fake_w3()
    w3.eth.accounts = [GANACHE_0]
    w3.eth.get_balance.return_value = 50 * 10**18
    assert _provider(w3, artifact).ensure_owner_funded(min_eth=Decimal("10"), topup_eth=Decimal("100")) is False
    w3.eth.send_transaction.assert_not_called()

    w3 = _fake_w3()
    w3.eth.accounts = []  # public network: nothing unlocked
    w3.eth.get_balance.return_value = 0
    assert _provider(w3, artifact).ensure_owner_funded(min_eth=Decimal("10"), topup_eth=Decimal("100")) is False
    w3.eth.send_transaction.assert_not_called()


def test_deploy_returns_address_and_amount(artifact):
    """ESC-02: deploy signs with the owner key and returns address, tx hash and the exact wei amount."""
    w3 = _fake_w3()
    ctor = w3.eth.contract.return_value.constructor
    ctor.return_value.build_transaction.return_value = {"from": OWNER, "nonce": 0}
    w3.eth.account.sign_transaction.return_value.raw_transaction = b"\x01"
    w3.eth.send_raw_transaction.return_value = b"\xaa" * 32
    w3.eth.wait_for_transaction_receipt.return_value = {"status": 1, "contractAddress": ADDR}
    p = _provider(w3, artifact)

    result = p.deploy(order_id=7, customer_address="0x" + "11" * 20, amount_usd="12.50")

    assert result["contract_address"].lower() == ADDR
    assert result["deploy_tx_hash"] == "0x" + "aa" * 32
    assert result["amount_wei"] == "12500000000000000"
    ctor.assert_called_once_with(CUST, 12_500_000_000_000_000, 7, 2000)
    assert ctor.call_args[0][3] == p.courier_share_bps
    w3.eth.send_raw_transaction.assert_called_once_with(b"\x01")


def test_revert_maps_to_escrow_revert(artifact):
    """ESC-02: a contract require() failure surfaces as EscrowRevert with the bare reason."""
    w3 = _fake_w3()
    w3.eth.get_code.return_value = b"\x60\x80"
    fn = w3.eth.contract.return_value.functions.assignCourier
    fn.return_value.build_transaction.side_effect = ContractLogicError("execution reverted: Transfer not complete.")
    p = _provider(w3, artifact)

    with pytest.raises(esc.EscrowRevert) as excinfo:
        p.assign_courier(ADDR, COURIER)

    assert excinfo.value.reason == "Transfer not complete."


def test_state_reads_status_tuple(artifact):
    """ESC-02: state() maps the status() tuple; zero courier -> None; ints -> decimal strings."""
    w3 = _fake_w3()
    w3.eth.get_code.return_value = b"\x60\x80"
    w3.eth.contract.return_value.functions.status.return_value.call.return_value = (
        1, OWNER, CUST, "0x" + "00" * 20, 5_000, 5_000,
    )
    p = _provider(w3, artifact)

    assert p.state(ADDR) == {
        "state": "funded",
        "owner": OWNER,
        "customer": CUST,
        "courier": None,
        "price_wei": "5000",
        "balance_wei": "5000",
    }


def test_state_raises_not_found_without_code(artifact):
    """ESC-02: an address with no code is EscrowNotFound (a wiped Ganache volume, a typo)."""
    w3 = _fake_w3()
    w3.eth.get_code.return_value = b""
    p = _provider(w3, artifact)

    with pytest.raises(esc.EscrowNotFound):
        p.state(ADDR)


def test_invoice_shape(artifact):
    """ESC-02: the unsigned pay() tx for ethers: to, value (string), data (selector), chain_id."""
    w3 = _fake_w3(chain_id=1337)
    w3.eth.get_code.return_value = b"\x60\x80"
    w3.eth.contract.return_value.functions.status.return_value.call.return_value = (
        0, OWNER, CUST, "0x" + "00" * 20, 5_000, 0,
    )
    p = _provider(w3, artifact)

    assert p.invoice(ADDR) == {
        "to": Web3.to_checksum_address(ADDR),
        "value": "5000",
        "data": esc.PAY_SELECTOR,
        "chain_id": 1337,
    }
    assert esc.PAY_SELECTOR == "0x" + bytes(Web3.keccak(text="pay()"))[:4].hex()


# ============== module-level factory ==============

class FakeW3:
    def __init__(self, connected: bool):
        self._connected = connected

    def is_connected(self) -> bool:
        return self._connected


def test_init_provider_returns_none_when_unreachable():
    """ESC-02: an unreachable chain disables escrow without raising; get_provider then says so."""
    assert esc.init_provider(w3_factory=lambda url: FakeW3(connected=False)) is None

    with pytest.raises(esc.EscrowUnavailable):
        esc.get_provider()


def test_init_provider_returns_none_without_owner_key(monkeypatch):
    """ESC-02: no owner key -> escrow disabled, the chain is not even contacted."""
    monkeypatch.delenv("ESCROW_OWNER_PRIVATE_KEY", raising=False)
    monkeypatch.setattr(esc, "ESCROW_OWNER_PRIVATE_KEY", None)
    factory = MagicMock()

    assert esc.init_provider(w3_factory=factory) is None
    factory.assert_not_called()
