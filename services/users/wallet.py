"""Ethereum wallet address rule for the users profile (phase 8, ESC-04).

Pure on purpose: schemas.py cannot be imported in unit tests (EmailStr needs
email-validator), so the rule lives where the test can reach it.
"""
import re

WALLET_RE = r"^0x[0-9a-fA-F]{40}$"

_WALLET = re.compile(WALLET_RE)


def normalize_wallet(value) -> str:
    """Return the trimmed address, case preserved.

    Raises ValueError for anything that is not 0x + 40 hex chars. The case is
    kept as given because EIP-55 checksum addresses are case-significant.
    """
    if not isinstance(value, str):
        raise ValueError("wallet address must be a string of the form 0x + 40 hex characters")
    v = value.strip()
    if not _WALLET.match(v):
        raise ValueError("wallet address must be of the form 0x + 40 hex characters")
    return v
