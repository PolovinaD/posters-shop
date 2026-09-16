"""Unit tests for ESC-04: the Ethereum wallet address rule on the users profile.

These tests import the PRODUCTION rule services/users/wallet.py::normalize_wallet.
The rule lives in its own pure module because services/users/schemas.py uses
EmailStr, which needs the email-validator package that is not installed in the
unit-test venv — so the Pydantic WalletIn validator delegates to a function the
tests can reach without importing schemas.py.
"""
import os
import re
import sys

import pytest

_USERS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/users")
)
sys.path.insert(0, _USERS_DIR)
try:
    # Same recipe as test_logistics_worker.py: wallet.py imports only `re`, and
    # "wallet" is a module name no other service uses, so nothing to unwind.
    from wallet import WALLET_RE, normalize_wallet
finally:
    sys.path.remove(_USERS_DIR)
    sys.modules.pop("wallet", None)


LOWER = "0x" + "ab" * 20
UPPER = "0x" + "AB" * 20


def test_normalize_accepts_lowercase_and_checksum_case():
    """ESC-04: a valid address is returned as given — EIP-55 checksums are case-significant."""
    assert normalize_wallet(LOWER) == LOWER
    assert normalize_wallet(UPPER) == UPPER


def test_normalize_strips_whitespace():
    """ESC-04: surrounding whitespace is trimmed before validation."""
    assert normalize_wallet("  " + LOWER + " ") == LOWER


@pytest.mark.parametrize(
    "value",
    [
        "",
        "0x",
        "0x123",
        "0x" + "ab" * 19,   # 38 hex chars
        "0x" + "ab" * 21,   # 42 hex chars
        "0x" + "gg" * 20,   # non-hex
        "ab" * 20,          # no 0x prefix
        None,
        42,
    ],
)
def test_normalize_rejects_bad_values(value):
    """ESC-04: anything that is not 0x + 40 hex characters raises ValueError naming the wallet address."""
    with pytest.raises(ValueError) as exc_info:
        normalize_wallet(value)
    assert "wallet address" in str(exc_info.value)


def test_wallet_regex_constant():
    """ESC-04: the shared regex is the exact 0x + 40 hex rule and matches a real Ganache address."""
    assert WALLET_RE == r"^0x[0-9a-fA-F]{40}$"
    assert re.match(WALLET_RE, "0x22d491bde2303f2f43325b2108d26f1eaba1e32b")
