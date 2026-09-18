"""Unit tests for services/designs/storage.py: the key scheme, LocalStorage on a temp
dir, S3Storage against a MagicMock boto3 client (boto3 itself is never imported), and
the env-driven backend selection."""
import io
from unittest.mock import MagicMock

import pytest

from tests.unit.designs_testkit import load_designs


@pytest.fixture(scope="module")
def storage():
    return load_designs().storage


def test_key_regex(storage):
    assert storage.KEY_RE.fullmatch("g" * 32 + ".png") is None  # right length, not hex
    assert storage.KEY_RE.fullmatch("0123456789abcdef0123456789abcdef.png")
    assert storage.KEY_RE.fullmatch("../etc/passwd") is None
    assert storage.KEY_RE.fullmatch("0123456789ABCDEF0123456789ABCDEF.png") is None  # uppercase
    assert storage.KEY_RE.fullmatch("x.png") is None
    k1, k2 = storage.new_image_key(), storage.new_image_key()
    assert storage.KEY_RE.fullmatch(k1)
    assert storage.KEY_RE.fullmatch(k2)
    assert k1 != k2


def test_local_put_get_roundtrip(storage, tmp_path):
    s = storage.LocalStorage(tmp_path / "img")
    assert (tmp_path / "img").is_dir()
    key = storage.new_image_key()
    data = b"\x89PNG\r\n\x1a\n" + b"payload"
    s.put(key, data)
    assert s.get(key) == data
    assert (tmp_path / "img" / key).is_file()


def test_local_get_missing_raises(storage, tmp_path):
    s = storage.LocalStorage(tmp_path / "img")
    with pytest.raises(FileNotFoundError):
        s.get(storage.new_image_key())


def test_local_rejects_bad_key(storage, tmp_path):
    s = storage.LocalStorage(tmp_path / "img")
    (tmp_path / "x.png").write_bytes(b"outside")  # exists one level up; must never be read
    with pytest.raises(FileNotFoundError):
        s.get("../x.png")
    with pytest.raises(ValueError):
        s.put("../x.png", b"1")
    assert (tmp_path / "x.png").read_bytes() == b"outside"


def test_s3_put_sets_headers(storage):
    client = MagicMock()
    s = storage.S3Storage("bkt", "eu-north-1", client=client)
    key = storage.new_image_key()
    s.put(key, b"data")
    client.put_object.assert_called_once_with(
        Bucket="bkt", Key=key, Body=b"data", ContentType="image/png",
        CacheControl="public, max-age=31536000, immutable",
    )


def test_s3_get_maps_nosuchkey(storage):
    client = MagicMock()
    client.exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
    s = storage.S3Storage("bkt", "eu-north-1", client=client)
    key = storage.new_image_key()
    client.get_object.side_effect = client.exceptions.NoSuchKey()
    with pytest.raises(FileNotFoundError):
        s.get(key)
    client.get_object.side_effect = None
    client.get_object.return_value = {"Body": io.BytesIO(b"abc")}
    assert s.get(key) == b"abc"


def test_get_storage_local_default(storage, tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("DESIGNS_STORAGE_DIR", str(tmp_path / "d"))
    assert isinstance(storage.get_storage(), storage.LocalStorage)
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.delenv("DESIGNS_S3_BUCKET", raising=False)
    with pytest.raises(RuntimeError):
        storage.get_storage()
