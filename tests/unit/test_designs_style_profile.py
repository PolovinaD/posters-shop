"""Style profile (D-07 tier 2 / D-16, 09-05): services/designs/style_profile.py on a
MagicMock session with a fake summariser — gathering the last prompts + purchase names,
composing the effective prompt, refreshing the profile (and keeping the old summary on a
provider error), and ensure_summary's cache-or-refresh-but-never-raise contract."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from tests.unit.designs_testkit import load_designs

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
EMAIL = "c@x.io"
PROMPTS = [f"prompt {i}" for i in range(25)]  # the DB would cap at 20; the code must too
NAMES = ["Forest Mist (A2)", "Custom: mountains (A3)", "Forest Mist (A2)", "Lisbon Tram (A4)"]
UNIQUE_NAMES = ["Forest Mist (A2)", "Custom: mountains (A3)", "Lisbon Tram (A4)"]


class FakeSummarizer:
    name = "fake"

    def __init__(self, text=None, exc=None):
        self.text, self.exc, self.calls = text, exc, []

    async def summarize(self, prompts, purchases):
        self.calls.append((prompts, purchases))
        if self.exc:
            raise self.exc
        return self.text


@pytest.fixture(scope="module")
def d():
    return load_designs()


@pytest.fixture(scope="module")
def pf(d):
    return d.style_profile


def _db(d, profile=None, prompts=PROMPTS, names=NAMES):
    """A session whose two SELECTs (prompts, then purchase names) answer in order and
    whose db.get answers the StyleProfile lookup."""
    db = MagicMock()
    r1, r2 = MagicMock(), MagicMock()
    r1.scalars.return_value.all.return_value = list(prompts)
    r2.scalars.return_value.all.return_value = list(names)
    db.execute.side_effect = [r1, r2]
    db.get.side_effect = lambda model, key: profile if model is d.models.StyleProfile else None
    return db


def _factory(db):
    db.__enter__.return_value = db
    return MagicMock(return_value=db)


def _compiled(stmt):
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


# ---------------------------------------------------------------------------
# gather_inputs / compose_effective_prompt
# ---------------------------------------------------------------------------

def test_gather_inputs_last_20_prompts_and_purchases(d, pf):
    db = _db(d)
    prompts, purchases = pf.gather_inputs(db, EMAIL)

    assert prompts == PROMPTS[:20]
    assert purchases == UNIQUE_NAMES
    assert pf.PROMPT_WINDOW == 20
    prompt_sql = _compiled(db.execute.call_args_list[0].args[0])
    assert "ORDER BY" in prompt_sql and "DESC" in prompt_sql and "LIMIT" in prompt_sql
    assert f"customer_email = '{EMAIL}'" in prompt_sql
    assert "status != 'failed'" in prompt_sql
    purchase_sql = _compiled(db.execute.call_args_list[1].args[0])
    assert "purchases" in purchase_sql and "DESC" in purchase_sql and "LIMIT" in purchase_sql


def test_compose_effective_prompt(pf):
    assert pf.compose_effective_prompt("a poster", "You lean towards: vintage.") == (
        "a poster\n\nStyle notes: You lean towards: vintage."
    )
    assert pf.compose_effective_prompt("a poster", "  You lean towards: vintage.  ") == (
        "a poster\n\nStyle notes: You lean towards: vintage."
    )
    assert pf.compose_effective_prompt("a poster", "") == "a poster"
    assert pf.compose_effective_prompt("a poster", None) == "a poster"
    assert pf.compose_effective_prompt("a poster", "   ") == "a poster"
    assert pf.STYLE_NOTES_PREFIX == "\n\nStyle notes: "


# ---------------------------------------------------------------------------
# refresh_profile
# ---------------------------------------------------------------------------

def test_refresh_profile_writes_summary_and_counts(d, pf):
    db = _db(d, profile=None)
    fake = FakeSummarizer(text="You like X.")
    prof = asyncio.run(pf.refresh_profile(db, EMAIL, fake, now=NOW))

    assert isinstance(prof, d.models.StyleProfile)
    assert prof.customer_email == EMAIL
    assert prof.summary == "You like X."
    assert prof.prompt_count == 20
    assert prof.purchase_count == 3
    assert prof.stale is False
    assert prof.updated_at == NOW
    db.add.assert_called_once_with(prof)
    db.commit.assert_called_once()
    assert fake.calls == [(PROMPTS[:20], UNIQUE_NAMES)]


def test_refresh_profile_keeps_old_summary_on_provider_error(d, pf):
    existing = SimpleNamespace(customer_email=EMAIL, summary="old", prompt_count=3, purchase_count=1, stale=True, updated_at=None)
    db = _db(d, profile=existing)
    fake = FakeSummarizer(exc=d.providers.ProviderError("429"))
    prof = asyncio.run(pf.refresh_profile(db, EMAIL, fake, now=NOW))

    assert prof is existing
    assert prof.summary == "old"
    assert prof.stale is True
    assert prof.prompt_count == 3
    db.commit.assert_not_called()
    db.add.assert_not_called()
    assert len(fake.calls) == 1


def test_refresh_profile_no_inputs_gives_empty_summary(d, pf):
    db = _db(d, profile=None, prompts=[], names=[])
    fake = FakeSummarizer(text="never")
    prof = asyncio.run(pf.refresh_profile(db, EMAIL, fake, now=NOW))

    assert fake.calls == []
    assert prof.summary == ""
    assert prof.stale is False
    assert (prof.prompt_count, prof.purchase_count) == (0, 0)
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# ensure_summary
# ---------------------------------------------------------------------------

def test_ensure_summary_uses_cached_when_fresh(d, pf):
    cached = SimpleNamespace(customer_email=EMAIL, summary="cached", stale=False)
    db = _db(d, profile=cached)
    fake = FakeSummarizer(text="new")
    out = asyncio.run(pf.ensure_summary(EMAIL, summarizer=fake, session_factory=_factory(db)))

    assert out == "cached"
    assert fake.calls == []
    db.execute.assert_not_called()

    # a fresh profile with an EMPTY summary (no inputs at the time) is None, not ""
    empty = SimpleNamespace(customer_email=EMAIL, summary="", stale=False)
    db = _db(d, profile=empty)
    assert asyncio.run(pf.ensure_summary(EMAIL, summarizer=fake, session_factory=_factory(db))) is None


def test_ensure_summary_refreshes_when_stale_or_missing(d, pf):
    stale = SimpleNamespace(customer_email=EMAIL, summary="old", prompt_count=0, purchase_count=0, stale=True, updated_at=None)
    db = _db(d, profile=stale)
    fake = FakeSummarizer(text="new")
    assert asyncio.run(pf.ensure_summary(EMAIL, summarizer=fake, session_factory=_factory(db))) == "new"
    assert len(fake.calls) == 1
    assert stale.stale is False and stale.summary == "new"
    db.commit.assert_called_once()

    db = _db(d, profile=None)
    fake = FakeSummarizer(text="new")
    assert asyncio.run(pf.ensure_summary(EMAIL, summarizer=fake, session_factory=_factory(db))) == "new"
    assert len(fake.calls) == 1
    assert isinstance(db.add.call_args.args[0], d.models.StyleProfile)


def test_ensure_summary_never_raises(d, pf):
    # the summariser blows up: the old summary is kept and returned
    old = SimpleNamespace(customer_email=EMAIL, summary="old", stale=True)
    db = _db(d, profile=old)
    out = asyncio.run(pf.ensure_summary(EMAIL, summarizer=FakeSummarizer(exc=RuntimeError("boom")), session_factory=_factory(db)))
    assert out == "old"
    db.commit.assert_not_called()

    # no profile at all and the summariser blows up: None
    db = _db(d, profile=None)
    out = asyncio.run(pf.ensure_summary(EMAIL, summarizer=FakeSummarizer(exc=RuntimeError("boom")), session_factory=_factory(db)))
    assert out is None

    # the database itself fails mid-refresh: the summary read before the failure is returned
    old = SimpleNamespace(customer_email=EMAIL, summary="old", stale=True)
    db = _db(d, profile=old)
    db.execute.side_effect = RuntimeError("db gone")
    out = asyncio.run(pf.ensure_summary(EMAIL, summarizer=FakeSummarizer(text="new"), session_factory=_factory(db)))
    assert out == "old"

    # the session factory itself fails: None, no exception
    factory = MagicMock(side_effect=RuntimeError("no pool"))
    assert asyncio.run(pf.ensure_summary(EMAIL, summarizer=FakeSummarizer(text="new"), session_factory=factory)) is None
