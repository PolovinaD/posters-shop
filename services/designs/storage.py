"""Image storage behind one ABC (D-08, AIP-05).

LocalStorage - files under DESIGNS_STORAGE_DIR (the compose `designs-data` volume),
               served by the designs service itself at GET /images/{key}.
S3Storage    - boto3 put/get by exact key; on EKS the credentials come from IRSA (the
               pod's ServiceAccount role), never from keys in code or env. boto3 is
               imported lazily so unit tests and the local backend need it installed
               only in the service image.

Keys are `uuid4().hex + ".png"` (KEY_RE): unguessable, so the image route can stay
unauthenticated (<img> cannot send a bearer), and traversal-proof — both backends
refuse anything that does not match. Backend selection: STORAGE_BACKEND (local | s3).
"""
import os
import pathlib
import re
import uuid
from abc import ABC, abstractmethod

from logger import get_logger

logger = get_logger(__name__)

KEY_RE = re.compile(r"^[0-9a-f]{32}\.png$")


def new_image_key() -> str:
    """A fresh storage key: 32 hex chars + .png (matches KEY_RE)."""
    return f"{uuid.uuid4().hex}.png"


class Storage(ABC):
    """Abstract image store keyed by KEY_RE keys."""

    @abstractmethod
    def put(self, key: str, data: bytes) -> None:
        """Store PNG bytes under key. Raise ValueError for a key that does not match KEY_RE."""
        raise NotImplementedError

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Return the PNG bytes for key. Raise FileNotFoundError when missing (or when the
        key is malformed) so the route answers 404."""
        raise NotImplementedError


class LocalStorage(Storage):
    """Filesystem store rooted at DESIGNS_STORAGE_DIR; never reads outside the root."""

    def __init__(self, root) -> None:
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes) -> None:
        if not KEY_RE.fullmatch(key):
            raise ValueError(f"invalid image key: {key}")
        (self.root / key).write_bytes(data)

    def get(self, key: str) -> bytes:
        if not KEY_RE.fullmatch(key):
            raise FileNotFoundError(key)
        path = self.root / key
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()


class S3Storage(Storage):
    """S3 store. `client` is injectable for tests; otherwise boto3 builds one lazily and
    picks up the IRSA web-identity env on EKS automatically (no keys in code)."""

    def __init__(self, bucket: str, region: str, client=None) -> None:
        if client is None:
            import boto3  # lazy: unit tests and the local backend need no boto3

            client = boto3.client("s3", region_name=region)
        self.bucket = bucket
        self._s3 = client

    def put(self, key: str, data: bytes) -> None:
        if not KEY_RE.fullmatch(key):
            raise ValueError(f"invalid image key: {key}")
        self._s3.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType="image/png",
            CacheControl="public, max-age=31536000, immutable",
        )

    def get(self, key: str) -> bytes:
        if not KEY_RE.fullmatch(key):
            raise FileNotFoundError(key)
        try:
            return self._s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self._s3.exceptions.NoSuchKey:
            raise FileNotFoundError(key)


def get_storage() -> Storage:
    """Select the backend by STORAGE_BACKEND (default: local)."""
    backend = os.getenv("STORAGE_BACKEND", "local").lower()
    if backend == "s3":
        bucket = os.getenv("DESIGNS_S3_BUCKET", "")
        if not bucket:
            raise RuntimeError("STORAGE_BACKEND=s3 requires DESIGNS_S3_BUCKET")
        region = os.getenv("DESIGNS_S3_REGION") or os.getenv("AWS_REGION", "eu-north-1")
        logger.info("Storage backend selected", backend="s3", root_or_bucket=bucket, region=region)
        return S3Storage(bucket, region)
    root = os.getenv("DESIGNS_STORAGE_DIR", "/data/images")
    logger.info("Storage backend selected", backend="local", root_or_bucket=root)
    return LocalStorage(root)
