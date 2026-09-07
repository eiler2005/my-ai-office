"""Every publishing worker's destination must reach the allowlist.

Regression for 2026-09-07: the allowlist was built by sweeping bridge `.env`
files only. Last30Days declares its topic in the reviewed signals config, so it
was never collected -- five publishing workers, four allowlisted topics -- and
every release died in `delivery.send()` with "Destination is not in this domain's
allowlist" after the research had already run.
"""
import json

import pytest

from benka_integrations.production import _delivery_targets

CHAT = "-1003592370241"


@pytest.fixture
def private(tmp_path):
    bridges = tmp_path / "bridges"
    bridges.mkdir()
    for name, prefix, topic in (
        ("agentmail-personal", "EMAIL_DIGEST", "119"),
        ("agentmail-work", "EMAIL_DIGEST", "125"),
        ("signals", "SIGNALS", "122"),
        ("telethon", "DIGEST", "126"),
    ):
        (bridges / f"{name}.env").write_text(
            f"{prefix}_SUPERGROUP_ID={CHAT}\n{prefix}_TOPIC_ID={topic}\n")
    config = tmp_path / "config" / "signals"
    config.mkdir(parents=True)
    (config / "config.json").write_text(json.dumps({
        "last30days": {
            "telegram": {"topic_id": 414},
            "presets": {
                "personal-feed-v1": {"telegram": {"topic_id": 414}},
                "platform-pulse-v1": {"telegram": {"topic_id": 414}},
            },
        },
        "sources": {"telegram": [{"chat_id": -1002334074574}]},
    }))
    return tmp_path


def test_the_last30days_topic_reaches_the_allowlist(private):
    assert f"telegram:{CHAT}:414" in _delivery_targets(private)


def test_every_publishing_destination_is_present(private):
    targets = _delivery_targets(private)
    for topic in ("119", "122", "125", "126", "414"):
        assert f"telegram:{CHAT}:{topic}" in targets, f"topic {topic} missing"
    assert len(targets) == 5, "five publishing workers, five destinations"


def test_a_source_chat_is_never_mistaken_for_a_destination(private):
    """Signals reads those chats; it must not gain the right to publish to them."""
    assert not any("1002334074574" in t for t in _delivery_targets(private))


def test_no_last30days_section_leaves_the_env_sweep_untouched(private):
    (private / "config/signals/config.json").write_text(json.dumps({"sources": {}}))
    assert len(_delivery_targets(private)) == 4


def test_result_is_sorted_and_deduplicated(private):
    targets = _delivery_targets(private)
    assert targets == sorted(set(targets))


def test_a_missing_bridge_file_fails_loudly(tmp_path):
    """A short allowlist is the bug this module exists to prevent.

    Tolerating an absent bridge env would silently drop a destination and refuse
    that worker's sends at runtime -- the exact failure that went unnoticed for a
    day. Preparation against an incomplete tree must stop instead.
    """
    (tmp_path / "bridges").mkdir()
    (tmp_path / "config" / "signals").mkdir(parents=True)
    (tmp_path / "config/signals/config.json").write_text("{}")
    with pytest.raises(FileNotFoundError):
        _delivery_targets(tmp_path)
