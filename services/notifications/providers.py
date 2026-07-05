"""
Pluggable email provider abstraction for the notifications service.

Two implementations:
- LoggingProvider: renders the email to the structured log (local dev / demo,
  requires NO AWS credentials).
- SesProvider: sends a real email through AWS SES via boto3.

Provider selection is driven by the EMAIL_PROVIDER environment variable
(get_provider()): "ses" -> SesProvider, anything else -> LoggingProvider.
"""
from abc import ABC, abstractmethod
import os

import boto3

from logger import get_logger

logger = get_logger(__name__)


class EmailProvider(ABC):
    """Abstract email transport."""

    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> None:
        """Send a plain-text email. Raise on failure so the caller can retry."""
        raise NotImplementedError


class LoggingProvider(EmailProvider):
    """Local-dev provider: logs the rendered email instead of sending it.

    No AWS credentials required — used for docker-compose and thesis demos.
    """

    def send(self, to: str, subject: str, body: str) -> None:
        logger.info("Email (logging provider)", to=to, subject=subject, body=body)


class SesProvider(EmailProvider):
    """AWS SES provider.

    Credentials are NOT handled in code: in production they come from IRSA
    (an IAM role granting ses:SendEmail bound to the pod's ServiceAccount).
    boto3 picks up the role automatically — there is no stored access key here.

    SES_REGION must match the region where EMAIL_FROM is a verified sender
    identity. The EKS cluster runs in eu-north-1, so production may override
    SES_REGION accordingly (the code default below is eu-central-1).
    """

    def __init__(self) -> None:
        self.region = os.getenv("SES_REGION", "eu-central-1")
        self.sender = os.getenv("EMAIL_FROM", "no-reply@postershop.example")
        self._client = boto3.client("ses", region_name=self.region)

    def send(self, to: str, subject: str, body: str) -> None:
        self._client.send_email(
            Source=self.sender,
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body}},
            },
        )


def get_provider() -> EmailProvider:
    """Select the email provider based on EMAIL_PROVIDER (default: logging)."""
    provider = os.getenv("EMAIL_PROVIDER", "logging").lower()
    if provider == "ses":
        return SesProvider()
    return LoggingProvider()
