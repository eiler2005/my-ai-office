"""Per-topic behaviour must survive on Hermes, which has no per-topic config.

Under the predecessor, workspace/TELEGRAM_POLICY.md gave each Telegram topic its
own rules. Hermes mounts none of that, and a plugin prompt section receives only
session_id, model, provider, platform, profile_name and cwd -- no chat or thread.
The Telegram session id is the one place the thread survives, so the surface is
recovered from it and rendered per session.
"""
from benka_integrations import plugin


class Ctx:
    def __init__(self, surfaces=None):
        self.surfaces = surfaces
        self.sections = {}

    def get_config(self, key):
        return self.surfaces if key == "surfaces" else None

    def register_tool(self, **kwargs):
        pass

    def register_system_prompt_section(self, id, content, **kwargs):
        self.sections[id] = content


SESSION = "agent:personal:telegram:group:-1003592370241:{thread}"


def test_ideas_thread_asks_for_the_ideas_capture_mode():
    ctx = Ctx({"777": "ideas"})
    render = plugin._surface_prompt(ctx)
    text = render({"session_id": SESSION.format(thread="777")})
    assert "capture_mode=ideas" in text
    assert "promote_fingerprint" in text


def test_knowledgebase_thread_asks_for_the_knowledgebase_mode():
    ctx = Ctx({"232": "knowledgebase"})
    text = plugin._surface_prompt(ctx)({"session_id": SESSION.format(thread="232")})
    assert "capture_mode=knowledgebase" in text
    assert "capture_mode=ideas" not in text


def test_a_conversation_surface_turns_capture_off():
    ctx = Ctx({"9": "conversation"})
    text = plugin._surface_prompt(ctx)({"session_id": SESSION.format(thread="9")})
    assert "not capture" in text or "Do not save" in text


def test_the_base_rules_are_always_present():
    ctx = Ctx({"232": "knowledgebase"})
    for thread in ("232", "999"):
        text = plugin._surface_prompt(ctx)({"session_id": SESSION.format(thread=thread)})
        assert "обсуди:" in text
        assert "Never ingest entire mailboxes automatically" in text


def test_an_unmapped_thread_keeps_the_base_rules_only():
    ctx = Ctx({"232": "knowledgebase"})
    text = plugin._surface_prompt(ctx)({"session_id": SESSION.format(thread="999")})
    assert text == plugin.BASE_PROMPT


def test_no_configured_map_is_inert():
    """Deployments without a surface map behave exactly as before."""
    assert plugin._surface_prompt(Ctx(None))({"session_id": SESSION.format(thread="232")}) == plugin.BASE_PROMPT
    assert plugin._surface_prompt(Ctx({}))({"session_id": "anything"}) == plugin.BASE_PROMPT


def test_a_missing_or_odd_session_id_never_raises():
    ctx = Ctx({"232": "knowledgebase"})
    render = plugin._surface_prompt(ctx)
    for info in ({}, {"session_id": ""}, {"session_id": "cli"}, None):
        assert render(info) == plugin.BASE_PROMPT


def test_the_section_is_registered_as_a_callable():
    ctx = Ctx({"232": "knowledgebase"})
    plugin.register(ctx)
    assert callable(ctx.sections["benka.wiki-first"])
