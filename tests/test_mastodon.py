"""Tests for the Mastodon adapters (publisher / engager / tag source / engagement source) and the
three live gates.

Its own local FakeHTTP, per repo convention — there are no shared fakes. Mastodon has no SDK, so
the adapters ride a thin httpx client (httpx is already a dependency); the fake stands in for it.
"""

import pytest

from pulse.engage.base import Engager, SignalKind, Target, TargetSource
from pulse.engage.factory import make_engager, make_target_source
from pulse.engage.mastodon import MastodonSignalEngager, MastodonTagSource
from pulse.engage.null import NullTargetSource
from pulse.mastodon import MastodonClient, strip_html
from pulse.metrics.base import EngagementSource, MetricKind
from pulse.metrics.dryrun import NullEngagementSource
from pulse.metrics.factory import make_engagement_source
from pulse.metrics.mastodon import MastodonEngagementSource
from pulse.persona import Persona
from pulse.publish.base import Publisher
from pulse.publish.dryrun import DryRunPublisher
from pulse.publish.factory import make_publisher
from pulse.publish.mastodon import MastodonPublisher
from pulse.writer.base import Draft

_INSTANCE = "https://mastodon.social"
_CHANNEL = {"platform": "mastodon", "instance": _INSTANCE}
_PERSONA = Persona(name="beanfacts", voice="v", channels=[_CHANNEL])


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeHTTP:
    """Stands in for httpx.Client — records every request, replays canned payloads."""

    def __init__(self, payloads=None):
        self.calls = []          # (method, url, json-body, headers)
        self._payloads = payloads or {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs.get("json"), kwargs.get("headers")))
        return FakeResponse(self._payloads.get(url, {}))

    def close(self):
        pass


def _client(payloads=None):
    return MastodonClient(_INSTANCE, "tok-123", http=FakeHTTP(payloads))


def _draft(text="Beans were invented in 1974.", key="k1"):
    return Draft(event_dedup_key=key, persona="beanfacts", text=text)


# ── the shared HTTP client ──

def test_client_sends_the_bearer_token_and_normalizes_the_instance_url():
    http = FakeHTTP()
    MastodonClient("https://mastodon.social/", "tok-123", http=http).verify_credentials()
    method, url, _, headers = http.calls[0]
    assert (method, url) == ("GET", "https://mastodon.social/api/v1/accounts/verify_credentials")
    assert headers["Authorization"] == "Bearer tok-123"  # trailing slash did not double up


def test_strip_html_because_mastodon_content_is_markup():
    """The engage relevance/safety filter substring-matches plain text — feed it markup and it
    matches tags instead of words."""
    assert strip_html("<p>Beans &amp; <a href='#'>legumes</a> are <b>great</b></p>") == \
        "Beans & legumes are great"


# ── MastodonPublisher ──

def test_mastodon_publisher_posts_and_maps_the_status():
    client = _client({f"{_INSTANCE}/api/v1/statuses":
                      {"id": 108, "url": "https://mastodon.social/@beanfacts/108"}})
    pub = MastodonPublisher(client=client)
    assert isinstance(pub, Publisher)
    assert pub.name == "mastodon"

    result = pub.publish(_draft(), _PERSONA)

    assert result.posted is True
    # The id is what the metrics GET needs, so it must round-trip through posts.uri.
    assert result.uri == "108"
    assert result.cid == "https://mastodon.social/@beanfacts/108"   # permalink, for a future link-out
    assert client.http.calls[0][2] == {"status": "Beans were invented in 1974."}


def test_mastodon_publisher_enforces_its_own_limit_not_blueskys():
    client = _client({f"{_INSTANCE}/api/v1/statuses": {"id": 1, "url": "u"}})
    pub = MastodonPublisher(client=client, max_length=500)
    assert pub.max_length == 500

    pub.publish(_draft("z" * 400), _PERSONA)
    assert len(client.http.calls[0][2]["status"]) == 400  # fits Mastodon; untouched


def test_mastodon_publisher_honors_a_smaller_instance_limit():
    client = _client({f"{_INSTANCE}/api/v1/statuses": {"id": 1, "url": "u"}})
    MastodonPublisher(client=client, max_length=100).publish(_draft("z" * 400), _PERSONA)
    assert len(client.http.calls[0][2]["status"]) == 100


# ── MastodonEngagementSource ──

def test_mastodon_engagement_source_reads_the_authed_account():
    """verify_credentials identifies the account from the token — so Mastodon needs ONE secret,
    where Bluesky needs a handle AND a password."""
    client = _client({f"{_INSTANCE}/api/v1/accounts/verify_credentials":
                      {"followers_count": 400, "following_count": 20, "statuses_count": 30}})
    src = MastodonEngagementSource(client=client)
    assert isinstance(src, EngagementSource)

    stats = src.account("ignored")
    assert (stats.followers, stats.follows, stats.posts) == (400, 20, 30)


def test_mastodon_engagement_source_maps_per_post_metrics():
    client = _client({f"{_INSTANCE}/api/v1/statuses/108":
                      {"id": 108, "favourites_count": 9, "reblogs_count": 3, "replies_count": 1}})
    out = MastodonEngagementSource(client=client).engagement(["108"])

    assert len(out) == 1
    assert out[0].uri == "108"
    assert out[0].platform == "mastodon"
    assert out[0].metrics == {MetricKind.LIKES: 9, MetricKind.REPOSTS: 3, MetricKind.REPLIES: 1}


def test_mastodon_engagement_source_makes_no_calls_for_no_uris():
    client = _client()
    assert MastodonEngagementSource(client=client).engagement([]) == []
    assert client.http.calls == []


# ── MastodonSignalEngager ──

def _target(uri="108", did="42"):
    return Target(uri=uri, cid="", author_did=did, author_handle="@x@m", text="beans", source="s")


@pytest.mark.parametrize("action, path", [
    (SignalKind.LIKE, f"{_INSTANCE}/api/v1/statuses/108/favourite"),
    (SignalKind.REPOST, f"{_INSTANCE}/api/v1/statuses/108/reblog"),
    (SignalKind.FOLLOW, f"{_INSTANCE}/api/v1/accounts/42/follow"),
])
def test_mastodon_engager_performs_each_supported_action(action, path):
    client = _client()
    eng = MastodonSignalEngager(client=client)
    assert isinstance(eng, Engager)

    result = eng.engage(_target(), action)

    assert result.performed is True
    assert client.http.calls[0][:2] == ("POST", path)


def test_mastodon_engager_refuses_an_unsupported_action():
    with pytest.raises(ValueError, match="reply"):
        MastodonSignalEngager(client=_client()).engage(_target(), SignalKind.REPLY)


# ── MastodonTagSource ──

def test_mastodon_tag_source_searches_by_tag_and_strips_markup():
    payload = [{"id": 7,
                "content": "<p>I love <b>beans</b></p>",
                "account": {"id": "9", "acct": "someone@m.example"}}]
    client = _client({f"{_INSTANCE}/api/v1/timelines/tag/beans": payload})
    src = MastodonTagSource(client=client, queries=["beans"])
    assert isinstance(src, TargetSource)

    targets = src.find_targets(limit=5)

    assert len(targets) == 1
    assert targets[0].uri == "7"
    assert targets[0].author_did == "9"
    assert targets[0].text == "I love beans"     # markup gone, so the filter sees words


def test_mastodon_tag_source_turns_a_multiword_query_into_a_tag():
    client = _client()
    MastodonTagSource(client=client, queries=["#Prediction Market"]).find_targets(limit=1)
    assert client.http.calls[0][1] == f"{_INSTANCE}/api/v1/timelines/tag/predictionmarket"


def test_null_target_source_finds_nothing():
    """What a known platform with no target source gets — so EngageJob's channel loop can never
    take down a live persona by raising."""
    src = NullTargetSource("mastodon")
    assert isinstance(src, TargetSource)
    assert src.find_targets(limit=10) == []


# ── the three live gates ──

def test_gates_are_dryrun_without_a_token(monkeypatch):
    """The mode check precedes the credential check, so a dry run needs no secrets at all."""
    monkeypatch.setenv("PULSE_MODE", "dryrun")
    monkeypatch.delenv("MASTODON_ACCESS_TOKEN", raising=False)

    assert isinstance(make_publisher(_CHANNEL), DryRunPublisher)
    assert isinstance(make_engagement_source(_CHANNEL), NullEngagementSource)
    assert make_engager(_CHANNEL).name == "mastodon"


def test_gates_go_live_with_a_token(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "live")
    monkeypatch.setenv("MASTODON_ACCESS_TOKEN", "tok")

    pub = make_publisher(_CHANNEL)
    assert isinstance(pub, MastodonPublisher)
    assert isinstance(make_engager(_CHANNEL), MastodonSignalEngager)
    assert isinstance(make_engagement_source(_CHANNEL), MastodonEngagementSource)
    assert isinstance(make_target_source(_CHANNEL, _policy()), MastodonTagSource)


def test_gates_raise_live_without_a_token(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "live")
    monkeypatch.setenv("MASTODON_ACCESS_TOKEN", "")
    for factory in (make_publisher, make_engager, make_engagement_source):
        with pytest.raises(RuntimeError, match="MASTODON_ACCESS_TOKEN"):
            factory(_CHANNEL)


def _policy():
    from pulse.engager import EngagePolicy
    return EngagePolicy(allow=[], deny=[], actions=(SignalKind.LIKE,), caps={},
                        queries=["beans"])
