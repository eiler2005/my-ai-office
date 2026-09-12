# Telegram surfaces

[Documentation map](../README.md) · [Workflows](../workflows.md) · [Knowledge](../knowledge.md) ·
[Security](../security.md)

Telegram is not one bot chat. It is a set of **purpose-specific surfaces**, and a surface is a
behavioural contract: what the owner sends there, what Benka does with it, and what Benka must not
do. This page is the reference for that contract.

> [!IMPORTANT]
> **If you are an agent or an LLM working on this repository, read the
> [Where the behaviour is defined](#where-the-behaviour-is-defined) section before changing
> anything.** A surface's behaviour is not configured per topic. It lives in two deployed places,
> and changing them requires an image rebuild and a new session.

## Why surfaces exist

The office pushes: briefings, alerts, digests, and answers arrive without being asked for. Five
workflows on different cadences — a five-minute Signals tick, five daily digests, eight work-mail
slots — merged into one chat produce a feed nobody reads.

Each workflow therefore publishes to its own topic in a private forum supergroup, so a stream can be
read, muted, or searched on its own. Direction matters:

- **Outbound** surfaces are written by a worker. The destination is configuration, never inference
  ([ADR-0002](../adr/0002-telegram-as-the-operating-surface.md)).
- **Inbound** surfaces are read by Benka, and what happens to a message depends on which surface it
  arrived in.

Routing happens **before tools are attached**: the Gateway resolves the sender and route to a
`personal`, `work`, `family`, or `sandbox` profile, then assembles only that profile's context. An
unmatched route gets no tools at all.

## The surfaces

| Surface | Direction | What the owner puts there | What Benka does | What it must not do |
| --- | --- | --- | --- | --- |
| **Owner DM** | Both | Anything — the primary conversation | Answers, follows up, asks for approval. This is the home channel for cron results and system notices. | Take a consequential action without approval. The home channel is bound to one trusted personal owner and nothing else. |
| **Knowledgebase** | Both | Forwarded posts, links, documents, long notes, and questions | **Captures by default** (see below), and answers questions from the curated knowledge base with citations | Run a web search by default; report a save as done without a real wiki path |
| **Ideas** | Inbound | Half-formed thoughts, links, fragments | Captures immediately with light curation, so keeping an idea costs nothing | Treat a capture as finished canonical knowledge; duplicate a chain on promotion |
| **inbox-email** | Outbound | — | Posts scheduled personal-mail briefings, 4×/day | Post raw email bodies |
| **work-email** | Outbound | — | Posts work briefings with the original sender resolved from forwarded mail and actionable/informational triage, 8 slots | Mix work and personal state; post raw bodies |
| **telegram-digest** | Outbound | — | Posts the channel digest 5×/day: scored, deduplicated, category-balanced, source-linked | Choose its own destination; publish without a confirmed receipt |
| **signals** | Outbound | — | Posts matched, time-sensitive alerts from configured rules, every 5 min | Forward every source event; call a model when no rule fired |
| **last30daysTrend** | Outbound | — | Posts the daily research digest at 07:00 | Suppress the whole run because one source failed |
| **inbox / tasks / approvals / system / rag-log** | Both | Operational dialogue | Ops commands, task lifecycle, approval requests, deploy and health notes, retrieval observability | Store sensitive payloads in memory — the approval *outcome* is kept, not the payload |
| **Family** | Both | Family conversation | Responds conservatively, on mention or reply | Write long-term memory without explicit approval |
| **Sandbox** | Both | Test traffic | Anything, in isolation | Write into production memory without an explicit promotion |

Outbound surfaces share one rule: **a worker may publish only to its configured allowlisted route,
and cannot select a chat or topic from the content it processed.** That is the boundary that stops a
malicious forwarded post from redirecting output.

## Knowledgebase, in detail

This surface has the most behaviour, and it is the one that regressed after the migration.

**Capture is the default, not an extra step.** Each of these is a capture request, and Benka calls
`wiki_ingest` itself, extracting title, source, date and a short summary:

- a forwarded post
- a URL
- long multi-line content
- an explicit save instruction

**Short, question-shaped messages are searches**, not captures. They run retrieval over the curated
knowledge base, open the strongest references, and answer with citations.

**When a message could be either, capture it.** A page the owner did not need is cheap; a lost
source is not.

The personal profile explicitly permits the `text` and `url` source types. That permission is part
of the private production manifest rather than a model instruction: a correct decision to capture
a link must still reach the wiki service. The other profiles stay text-only until their owner and
data boundary are reviewed.

**`обсуди:` is the opt-out** — the only one. Benka may not decline to capture because the content
looks unimportant.

A save is reported as done **only** with a real `wiki/research/**` path in the result. Indexing
status is reported separately, because a failed index does not erase a created page
([ADR-0005](../adr/0005-wiki-first-capture-rag-as-retrieval.md)).

Web search is opt-in in this surface. The point is the local knowledge base; the internet is a
separate, explicit step.

## Ideas, in detail

Good capture friction is bad idea friction, so Ideas captures **anything** — links, forwarded posts,
fragments — with `capture_mode=ideas` and lighter curation.

Promotion later uses `capture_mode=promotion` with the existing `promote_fingerprint`, so it
**enriches the existing chain** rather than creating a second artifact.

## Where the behaviour is defined

This is the part that is easy to get wrong, and it is why a per-surface change is more work than it
looks.

Topic behaviour is expressed as instructions to the model, in two deployed places — plus one small
piece of deployment configuration that tells the agent *which* surface it is in.

| Place | What it holds | Deployed how |
| --- | --- | --- |
| [`src/benka_integrations/plugin.py`](../../src/benka_integrations/plugin.py) — the `benka.wiki-first` system prompt section | The capture rule, the search/capture distinction, the `обсуди:` opt-out | **Inside the runtime image.** Requires a rebuild. |
| [`skills/benka-knowledge/SKILL.md`](../../skills/benka-knowledge/SKILL.md) | The same rules in fuller form, plus retrieval and archive guidance | Copied into each profile home under `skills/` |

### Telling the agent which surface it is in

Hermes gives a plugin prompt section only `session_id`, `model`, `provider`, `platform`,
`profile_name` and `cwd` — **no chat id and no thread id**. Without help, the agent cannot tell
Knowledgebase from Ideas, so `capture_mode=ideas` and the promotion chain are unreachable and the
capture rule applies everywhere equally.

The Telegram session id is the one place the thread survives:

```text
agent:<profile>:telegram:group:<chat_id>:<thread_id>
```

The plugin therefore registers its prompt section as a **callable**, resolves the trailing thread id
against a `surfaces` map in the profile's plugin settings, and appends surface-specific guidance:

```yaml
plugins:
  entries:
    benka:
      settings:
        manifest_path: /run/benka/profiles/personal.json
        surfaces:
          "232": knowledgebase
          "<thread>": ideas
          "<thread>": conversation
```

Recognised surfaces are `knowledgebase`, `ideas` and `conversation` — the last one turns capture off
for a topic that is for talking or that only receives an outbound feed. A thread that is not in the
map, or a deployment with no map at all, gets the base rules and behaves exactly as it did before, so
the mechanism is inert until configured.

The predecessor kept the same mapping in `telegram-topic-map.json`, which is preserved in the cutover
snapshot. That file is where the production thread ids came from; it is deployment-private and its
values do not belong in this repository.

Because the map is configuration rather than code, adding a topic needs a Gateway restart and a new
session — **not** an image rebuild.

> [!CAUTION]
> **`workspace/TELEGRAM_POLICY.md` is not deployed.** The predecessor mounted `workspace/` into the
> agent, and that file carried the per-surface table. Hermes mounts none of it. The file is kept as a
> behavioural record only — editing it changes nothing at runtime, and reading it as current
> behaviour is a mistake. See [`docs/hermes/drift-log.md`](../hermes/drift-log.md), row `D007`.

## Changing a surface's behaviour

Three steps, and skipping the third is the usual reason a change appears to do nothing:

1. **Edit the rule** in the system prompt section and the skill, keeping the two consistent.
2. **Rebuild and deploy**, because the prompt section is in the image. Package the candidate, run
   `scripts/run-hermes-vps-tests.sh` on the VPS, then recreate the Gateway with `--no-deps` and copy
   the skill files into the profile homes.
3. **Start a new session on every affected surface** — `/new` in the topic.

Step 3 is not optional. Hermes freezes a plugin's system prompt into a session when the session is
created and persists it verbatim, so an open conversation keeps the old instructions indefinitely.
The procedure and the query that reveals which prompt a session is actually running are in
[operations](../hermes/operations.md#changing-the-agents-instructions).

## What the migration lost, and why

The predecessor kept per-surface behaviour in a mounted workspace file. Hermes has no equivalent
concept: instructions come from the profile's `SOUL.md`, its skills, and plugin prompt sections. The
per-surface rules were not carried into any of those, so Knowledgebase silently stopped capturing
forwarded posts while its pinned message and the README kept promising it.

The rules now live in the two places that are actually deployed, and this page is the reference so
the contract has a home in the documentation rather than only in a prompt.

Historical detail, including the permission matrix and the original topic taxonomy, is in
[`docs/archive/openclaw/12-telegram-channel-architecture.md`](../archive/openclaw/12-telegram-channel-architecture.md)
and
[`docs/archive/openclaw/17-knowledge-management.md`](../archive/openclaw/17-knowledge-management.md).
Those describe the retired runtime and are not current.

## Related

- [Workflows](../workflows.md) — the two execution paths and the workflow catalogue
- [Knowledge](../knowledge.md) — the five memory layers and what capture writes
- [Schedules](schedules.md) — when each outbound surface receives its post
- [ADR-0002](../adr/0002-telegram-as-the-operating-surface.md) — why Telegram, and why topics
