"""Unit tests for ESC-01: the committed OrderEscrow contract artifact.

Pure file/JSON checks -- no web3, no chain, no compiler. The artifact
services/payments/contracts/OrderEscrow.json is COMMITTED (solc runs only via
`make contract-compile`), so these tests guard two things: that the artifact
has the shape escrow.py drives (constructor, functions, events, status tuple)
and that it was produced from the .sol that sits next to it
(source_sha256) -- an edited contract without a recompile fails here.
"""
import hashlib
import json
import pathlib

CONTRACTS_DIR = pathlib.Path(__file__).parents[2] / "services/payments/contracts"
SOL_PATH = CONTRACTS_DIR / "OrderEscrow.sol"
JSON_PATH = CONTRACTS_DIR / "OrderEscrow.json"

# The IEP 2025 „Наплата" wording, locked by 08-CONTEXT.md.
IEP_REQUIRE_STRINGS = [
    "Invalid customer.",
    "Invalid amount.",
    "Transfer already complete.",
    "Transfer not complete.",
    "Invalid address.",
    "Delivery not complete.",
    "Cannot cancel.",
    "Order closed.",
]


def _artifact() -> dict:
    with open(JSON_PATH) as f:
        return json.load(f)


def _abi_entries(kind: str) -> list[dict]:
    return [e for e in _artifact()["abi"] if e.get("type") == kind]


def test_artifact_has_required_keys():
    """ESC-01: the artifact carries exactly abi, bytecode, contract, solc_version, source_sha256."""
    artifact = _artifact()

    assert set(artifact) == {"contract", "abi", "bytecode", "solc_version", "source_sha256"}
    assert artifact["contract"] == "OrderEscrow"
    assert artifact["solc_version"].startswith("0.8.28")
    assert artifact["bytecode"].startswith("0x")
    assert len(artifact["bytecode"]) > 1000


def test_abi_exposes_escrow_functions():
    """ESC-01: every function escrow.py calls exists; pay() is payable; ctor takes (address,uint256,uint256,uint16)."""
    functions = {e["name"]: e for e in _abi_entries("function")}
    expected = {
        "pay", "assignCourier", "confirmDelivery", "cancel", "status",
        "owner", "customer", "courier", "price", "orderId", "courierShareBps", "state",
    }

    assert expected <= set(functions)
    assert functions["pay"]["stateMutability"] == "payable"

    constructors = _abi_entries("constructor")
    assert len(constructors) == 1
    assert [i["type"] for i in constructors[0]["inputs"]] == ["address", "uint256", "uint256", "uint16"]


def test_abi_exposes_events():
    """ESC-01: the four lifecycle events are declared."""
    events = {e["name"] for e in _abi_entries("event")}

    assert {"Funded", "CourierAssigned", "Completed", "Cancelled"} <= events


def test_source_hash_matches_committed_source():
    """ESC-01: the committed artifact was compiled from the committed .sol (catches an edit without recompile)."""
    expected = hashlib.sha256(SOL_PATH.read_bytes()).hexdigest()

    assert _artifact()["source_sha256"] == expected


def test_source_contains_iep_require_strings():
    """ESC-01: the revert reasons mirror the IEP wording so the defence maps 1:1."""
    source = SOL_PATH.read_text()

    missing = [s for s in IEP_REQUIRE_STRINGS if s not in source]
    assert missing == [], f"missing require strings: {missing}"


def test_status_returns_six_values():
    """ESC-01: status() returns (state, owner, customer, courier, price, balance) in one call."""
    status = next(e for e in _abi_entries("function") if e["name"] == "status")

    assert len(status["outputs"]) == 6
    assert [o["type"] for o in status["outputs"]] == [
        "uint8", "address", "address", "address", "uint256", "uint256",
    ]
