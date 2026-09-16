"""Client for communicating with the payments service.

Stripe is never called from here: payments owns the Stripe SDK and creates the
Hosted Checkout session; this module only speaks HTTP to that service.
"""
import os
from typing import Optional

import httpx

from circuit_breaker import CircuitBreaker, CircuitOpenError  # noqa: F401
from service_auth import internal_headers

PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payments:8000")
TIMEOUT = httpx.Timeout(10.0, connect=5.0)

# Circuit breaker singleton for payments service (D-02)
payment_cb = CircuitBreaker(
    service="payments",
    failure_threshold=int(os.getenv("CB_FAILURE_THRESHOLD", "5")),
    recovery_timeout=float(os.getenv("CB_RECOVERY_TIMEOUT", "30")),
)


class PaymentServiceError(Exception):
    """Raised when payment service request fails."""
    pass


class EscrowRejectedError(PaymentServiceError):
    """payments answered 409: the contract's require() refused (reason = bare revert string)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class EscrowContractMissingError(PaymentServiceError):
    """payments answered 404: no contract at that address."""


class EscrowUnavailableError(PaymentServiceError):
    """payments answered 503: chain unreachable / escrow disabled."""


async def create_checkout_session(
    order_id: int,
    customer_email: str,
    line_items: list[dict],
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None
) -> dict:
    """
    Create a Stripe checkout session.

    Args:
        order_id: The order ID to associate with this session
        customer_email: Customer's email
        line_items: List of items with name, quantity, unit_amount (in cents)
        success_url: URL to redirect on success
        cancel_url: URL to redirect on cancel

    Returns:
        Checkout session with id and checkout_url
    Raises CircuitOpenError when payments circuit is open.
    """
    payload = {
        "order_id": order_id,
        "customer_email": customer_email,
        "line_items": line_items
    }

    if success_url:
        payload["success_url"] = success_url
    if cancel_url:
        payload["cancel_url"] = cancel_url

    async def _call() -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=internal_headers()) as client:
            try:
                response = await client.post(
                    f"{PAYMENT_SERVICE_URL}/v1/checkout/sessions",
                    json=payload
                )

                if response.status_code == 200:
                    return response.json()
                else:
                    raise PaymentServiceError(
                        f"Failed to create checkout session: {response.status_code} - {response.text}"
                    )

            except httpx.RequestError as e:
                raise PaymentServiceError(f"Payment service unavailable: {e}")

    return await payment_cb.call(_call)


async def get_checkout_session(session_id: str) -> dict:
    """
    Get checkout session by ID.
    Raises CircuitOpenError when payments circuit is open.
    """
    async def _call() -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=internal_headers()) as client:
            try:
                response = await client.get(
                    f"{PAYMENT_SERVICE_URL}/v1/checkout/sessions/{session_id}"
                )

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 404:
                    raise PaymentServiceError(f"Session {session_id} not found")
                else:
                    raise PaymentServiceError(
                        f"Failed to get session: {response.status_code}"
                    )

            except httpx.RequestError as e:
                raise PaymentServiceError(f"Payment service unavailable: {e}")

    return await payment_cb.call(_call)


# ============== Escrow (phase 8) ==============
#
# Every call goes through payment_cb like the Stripe ones. The breaker keys on
# exception CLASS NAMES: EscrowRejectedError (409) and EscrowContractMissingError
# (404) are whitelisted in circuit_breaker._BUSINESS_ERROR_NAMES and never trip
# it; EscrowUnavailableError (503) and PaymentServiceError do, because then
# payments really is failing us.

def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail", response.text))
    except ValueError:
        return response.text


def _raise_for_escrow(response: httpx.Response, what: str) -> None:
    if response.status_code == 200:
        return
    if response.status_code == 409:
        raise EscrowRejectedError(_detail(response))
    if response.status_code == 404:
        raise EscrowContractMissingError(_detail(response))
    if response.status_code == 503:
        raise EscrowUnavailableError(_detail(response))
    raise PaymentServiceError(f"Failed to {what}: {response.status_code} - {response.text}")


async def get_escrow_config() -> dict:
    """GET /v1/escrow/config -> {enabled, chain_id, rpc_url, wei_per_usd, courier_share_bps, owner_address}."""
    async def _call() -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=internal_headers()) as client:
            try:
                response = await client.get(f"{PAYMENT_SERVICE_URL}/v1/escrow/config")
                _raise_for_escrow(response, "get escrow config")
                return response.json()
            except httpx.RequestError as e:
                raise PaymentServiceError(f"Payment service unavailable: {e}")

    return await payment_cb.call(_call)


async def create_escrow(order_id: int, customer_address: str, amount_usd: str) -> dict:
    """POST /v1/escrow -> {contract_address, deploy_tx_hash, amount_wei}."""
    payload = {
        "order_id": order_id,
        "customer_address": customer_address,
        "amount_usd": amount_usd,
    }

    async def _call() -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=internal_headers()) as client:
            try:
                response = await client.post(f"{PAYMENT_SERVICE_URL}/v1/escrow", json=payload)
                _raise_for_escrow(response, "deploy escrow contract")
                return response.json()
            except httpx.RequestError as e:
                raise PaymentServiceError(f"Payment service unavailable: {e}")

    return await payment_cb.call(_call)


async def get_escrow_state(address: str) -> dict:
    """GET /v1/escrow/{address} -> {state, owner, customer, courier, price_wei, balance_wei}."""
    async def _call() -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=internal_headers()) as client:
            try:
                response = await client.get(f"{PAYMENT_SERVICE_URL}/v1/escrow/{address}")
                _raise_for_escrow(response, "get escrow state")
                return response.json()
            except httpx.RequestError as e:
                raise PaymentServiceError(f"Payment service unavailable: {e}")

    return await payment_cb.call(_call)


async def get_escrow_invoice(address: str) -> dict:
    """GET /v1/escrow/{address}/invoice -> {to, value, data, chain_id} (unsigned pay() tx)."""
    async def _call() -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=internal_headers()) as client:
            try:
                response = await client.get(f"{PAYMENT_SERVICE_URL}/v1/escrow/{address}/invoice")
                _raise_for_escrow(response, "get escrow invoice")
                return response.json()
            except httpx.RequestError as e:
                raise PaymentServiceError(f"Payment service unavailable: {e}")

    return await payment_cb.call(_call)


async def assign_escrow_courier(address: str, courier_address: str) -> dict:
    """POST /v1/escrow/{address}/courier -> {tx_hash, state}."""
    async def _call() -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=internal_headers()) as client:
            try:
                response = await client.post(
                    f"{PAYMENT_SERVICE_URL}/v1/escrow/{address}/courier",
                    json={"courier_address": courier_address},
                )
                _raise_for_escrow(response, "assign escrow courier")
                return response.json()
            except httpx.RequestError as e:
                raise PaymentServiceError(f"Payment service unavailable: {e}")

    return await payment_cb.call(_call)


async def release_escrow(address: str) -> dict:
    """POST /v1/escrow/{address}/release -> {tx_hash, state}."""
    async def _call() -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=internal_headers()) as client:
            try:
                response = await client.post(f"{PAYMENT_SERVICE_URL}/v1/escrow/{address}/release")
                _raise_for_escrow(response, "release escrow")
                return response.json()
            except httpx.RequestError as e:
                raise PaymentServiceError(f"Payment service unavailable: {e}")

    return await payment_cb.call(_call)


async def cancel_escrow(address: str) -> dict:
    """POST /v1/escrow/{address}/cancel -> {tx_hash, state} (refunds the customer if funded)."""
    async def _call() -> dict:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers=internal_headers()) as client:
            try:
                response = await client.post(f"{PAYMENT_SERVICE_URL}/v1/escrow/{address}/cancel")
                _raise_for_escrow(response, "cancel escrow")
                return response.json()
            except httpx.RequestError as e:
                raise PaymentServiceError(f"Payment service unavailable: {e}")

    return await payment_cb.call(_call)
