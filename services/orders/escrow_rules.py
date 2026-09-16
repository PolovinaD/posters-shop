"""Pure escrow rules for the orders service.

Imports only `re` on purpose (same reasoning as logistics/worker_rules.py): the
unit tests import the production rule directly, without SQLAlchemy, logging or
a database in the way, and schemas.py shares the wallet regex from here.
"""
import re

WALLET_RE = r"^0x[0-9a-fA-F]{40}$"
_WALLET = re.compile(WALLET_RE)


def is_wallet_address(value) -> bool:
    """True for a 0x-prefixed 40-hex-character Ethereum address (case preserved)."""
    return isinstance(value, str) and bool(_WALLET.match(value))


def decide_reconcile_action(
    order_status: str,
    escrow_status: str | None,
    courier_wallet: str | None,
    chain_state: str | None,
) -> str:
    """What the reconciler should do for one open escrow order.

    Returns one of: mark_paid | bind_courier | sync_in_delivery | refund |
    mark_failed | noop. `chain_state` None means there is no contract code at
    the stored address (a wiped Ganache volume).
    """
    if escrow_status in ("awaiting_payment", "funded") and chain_state is None:
        return "mark_failed"
    # A cancelled/failed order whose contract is still open holds (or can still
    # receive) the customer's ether: reservation_expired refunds best-effort and
    # cancels regardless, so this is the retry that closes that gap.
    if order_status in ("cancelled", "failed") and chain_state in ("awaiting_payment", "funded"):
        return "refund"
    if (
        order_status == "reserved"
        and escrow_status == "awaiting_payment"
        and chain_state in ("funded", "in_delivery", "released")
    ):
        return "mark_paid"
    if (
        escrow_status == "funded"
        and chain_state == "in_delivery"
        and order_status not in ("cancelled", "failed")
    ):
        return "sync_in_delivery"
    if (
        escrow_status == "funded"
        and courier_wallet
        and chain_state == "funded"
        and order_status not in ("cancelled", "failed")
    ):
        return "bind_courier"
    return "noop"
