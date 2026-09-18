"""Unit tests for services/designs/worker.py: the atomic claim SQL, the error taxonomy
(D-04/D-05) mapped to outcomes with backoff, outcome persistence on a MagicMock session,
and run_generation end to end on the real FakeProvider + LocalStorage + CircuitBreaker
with the session factory mocked (no database)."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from tests.unit.designs_testkit import load_designs

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
CLAIMED = {
    "id": 7, "customer_email": "c@x.io", "prompt": "p", "effective_prompt": "p",
    "personalise": False, "attempts": 1,
}


@pytest.fixture(scope="module")
def d():
    return load_designs()


@pytest.fixture(scope="module")
def worker(d):
    return d.worker


def _session_factory(session=None):
    """A sessionmaker stand-in: `with factory() as db` yields the same MagicMock."""
    session = session or MagicMock()
    session.__enter__.return_value = session
    factory = MagicMock(return_value=session)
    return factory, session


def _breaker(d, threshold=2):
    return d.circuit_breaker.CircuitBreaker("test", failure_threshold=threshold, recovery_timeout=30)


def _row(prompt, attempts=1):
    return {**CLAIMED, "prompt": prompt, "effective_prompt": prompt, "attempts": attempts}


def test_claim_sql_shape(worker):
    sql = worker.CLAIM_SQL.text
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "status = 'generating'" in sql
    assert "attempts = attempts + 1" in sql
    assert "retry_after IS NULL OR retry_after <= now()" in sql
    assert "RETURNING" in sql


def test_claim_next_returns_mapping_or_none(worker):
    factory, session = _session_factory()
    session.execute.return_value.mappings.return_value.first.return_value = CLAIMED
    assert worker.claim_next(session_factory=factory) == CLAIMED
    session.commit.assert_called_once()

    factory, session = _session_factory()
    session.execute.return_value.mappings.return_value.first.return_value = None
    assert worker.claim_next(session_factory=factory) is None


def test_outcome_prompt_rejected(d, worker):
    out = worker.outcome_for_error(d.providers.PromptRejected("nope"), attempts=1, now=NOW)
    assert out == worker.Outcome(status="failed", failure_reason="nope")


def test_outcome_config_error_is_generic(d, worker):
    out = worker.outcome_for_error(d.providers.ProviderConfigError("openai 400: invalid model"), attempts=1, now=NOW)
    assert out.status == "failed"
    assert out.failure_reason == "The image provider is not configured correctly; please try again later"
    assert "openai" not in out.failure_reason


def test_outcome_provider_error_retries_with_backoff(d, worker):
    err = d.providers.ProviderError("boom")
    assert worker.outcome_for_error(err, attempts=1, now=NOW) == worker.Outcome(
        status="queued", retry_after=NOW + timedelta(seconds=5), attempts=None
    )
    assert worker.outcome_for_error(err, attempts=2, now=NOW) == worker.Outcome(
        status="queued", retry_after=NOW + timedelta(seconds=30), attempts=None
    )
    third = worker.outcome_for_error(err, attempts=3, now=NOW)  # == DESIGNS_MAX_ATTEMPTS default
    assert third.status == "failed"
    assert third.failure_reason == "The image provider is unavailable right now; please try again later"


def test_outcome_circuit_open_does_not_consume_attempt(d, worker):
    out = worker.outcome_for_error(d.circuit_breaker.CircuitOpenError("image_provider"), attempts=1, now=NOW)
    assert out == worker.Outcome(
        status="queued", retry_after=NOW + timedelta(seconds=worker.CB_RECOVERY_TIMEOUT), attempts=0
    )


def test_outcome_unknown_exception_is_provider_error(worker):
    first = worker.outcome_for_error(RuntimeError("x"), attempts=1, now=NOW)
    assert first.status == "queued" and first.retry_after == NOW + timedelta(seconds=5)
    last = worker.outcome_for_error(RuntimeError("x"), attempts=3, now=NOW)
    assert last.status == "failed"


def test_apply_outcome_ready(worker):
    db = MagicMock()
    row = db.get.return_value
    worker.apply_outcome(
        db, 7, worker.Outcome(status="ready", image_key="k.png"),
        provider_name="fake", params={"size": "1024x1536"}, now=NOW,
    )
    assert row.status == "ready"
    assert row.image_key == "k.png"
    assert row.finished_at == NOW
    assert row.provider == "fake"
    assert row.params == {"size": "1024x1536"}
    assert row.failure_reason is None
    db.commit.assert_called_once()


def test_apply_outcome_queued_writes_retry_and_attempts(worker):
    db = MagicMock()
    row = db.get.return_value
    untouched = row.finished_at
    retry = NOW + timedelta(seconds=30)
    worker.apply_outcome(
        db, 7, worker.Outcome(status="queued", retry_after=retry, attempts=0),
        provider_name="fake", params={}, now=NOW,
    )
    assert row.status == "queued"
    assert row.retry_after == retry
    assert row.attempts == 0
    assert row.finished_at is untouched
    db.commit.assert_called_once()

    # a vanished row is a no-op, not a crash
    gone = MagicMock()
    gone.get.return_value = None
    worker.apply_outcome(gone, 7, worker.Outcome(status="ready", image_key="k.png"), "fake", {}, NOW)
    gone.commit.assert_not_called()


def test_run_generation_success_writes_png(d, worker, tmp_path):
    factory, session = _session_factory()
    store = d.storage.LocalStorage(tmp_path)
    d.metrics.GENERATIONS_TOTAL.reset_mock()
    status = asyncio.run(worker.run_generation(
        _row("a lighthouse"), provider=d.providers.FakeProvider(), storage=store,
        breaker=_breaker(d), session_factory=factory, now=NOW,
    ))
    assert status == "ready"
    row = session.get.return_value
    assert row.status == "ready"
    assert d.storage.KEY_RE.fullmatch(row.image_key)
    assert (tmp_path / row.image_key).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert row.finished_at == NOW
    d.metrics.GENERATIONS_TOTAL.labels.assert_called_with(provider="fake", status="ready")


def test_run_generation_reject(d, worker, tmp_path):
    factory, session = _session_factory()
    store = d.storage.LocalStorage(tmp_path)
    cb = _breaker(d)
    status = asyncio.run(worker.run_generation(
        _row("x [reject]"), provider=d.providers.FakeProvider(), storage=store,
        breaker=cb, session_factory=factory, now=NOW,
    ))
    assert status == "failed"
    row = session.get.return_value
    assert row.status == "failed"
    assert "rejected" in row.failure_reason
    assert list(tmp_path.iterdir()) == []
    assert cb._state == "closed"


def test_run_generation_fail_then_breaker_opens(d, worker, tmp_path):
    store = d.storage.LocalStorage(tmp_path)
    cb = _breaker(d, threshold=2)
    provider = d.providers.FakeProvider()

    def run(attempts):
        factory, session = _session_factory()
        status = asyncio.run(worker.run_generation(
            _row("x [fail]", attempts=attempts), provider=provider, storage=store,
            breaker=cb, session_factory=factory, now=NOW,
        ))
        return status, session.get.return_value

    status, row = run(1)
    assert status == "queued"
    assert row.retry_after == NOW + timedelta(seconds=5)
    assert cb._state == "closed"

    status, row = run(2)
    assert status == "queued"
    assert row.retry_after == NOW + timedelta(seconds=30)
    assert cb._state == "open"

    status, row = run(3)  # circuit open: the attempt is handed back, not consumed
    assert status == "queued"
    assert row.attempts == 2
    assert row.retry_after == NOW + timedelta(seconds=worker.CB_RECOVERY_TIMEOUT)
    assert list(tmp_path.iterdir()) == []
