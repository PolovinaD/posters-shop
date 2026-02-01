"""
Payment Service Client

Interacts with the payment service (Stripe mock) to create checkout sessions.

In production, you would use the official Stripe SDK:
```python
import stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
session = stripe.checkout.Session.create(...)
```
"""
import os
from typing import Optional

import httpx

PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payments:8000")
TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class PaymentServiceError(Exception):
    """Raised when payment service request fails."""
    pass


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
    
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
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


async def get_checkout_session(session_id: str) -> dict:
    """Get checkout session by ID."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
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

