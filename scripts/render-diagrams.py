#!/usr/bin/env python3
"""Generate the light/dark SVG diagram pairs for docs/assets/.

One definition per diagram, rendered twice through a theme. Keeping the pair in
one source is the only way they stay in sync when a box is renamed.

Constraints these files must satisfy (GitHub sanitizes SVG served to <img>):
  - no external fonts, no @import, no <script>
  - system font stack only
  - role="img" + <title>/<desc> for screen readers
  - viewBox set so the image scales inside a Markdown column
"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parents[1] / "docs" / "assets"
FONT = "ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"

DARK = {
    "bg": "#0c1923", "grid": "#a2cfdb", "grid_op": ".05",
    "zone": "#101f2a", "zone_stroke": "#2c4552",
    "panel": "#15252f", "stroke": "#3c5c69",
    "text": "#eef4f6", "muted": "#9fbbc4", "faint": "#7695a1",
    "accent": "#64dac7", "accent_fill": "#15353e", "accent_stroke": "#5cb9ad",
    "blue": "#8cbaf3", "blue_fill": "#152b38", "blue_stroke": "#4d7186",
    "amber": "#e8be7b", "amber_fill": "#242f34", "amber_stroke": "#8e8060",
    "rose": "#f0a08c", "rose_fill": "#2b2028", "rose_stroke": "#8d6161",
    "line": "#587885",
}

LIGHT = {
    "bg": "#f6fafb", "grid": "#2c6070", "grid_op": ".05",
    "zone": "#ecf3f5", "zone_stroke": "#cadbe1",
    "panel": "#ffffff", "stroke": "#b4cbd3",
    "text": "#0e222c", "muted": "#476470", "faint": "#5f7d89",
    "accent": "#0f7d6b", "accent_fill": "#e2f5f1", "accent_stroke": "#63bfb0",
    "blue": "#2f5fa4", "blue_fill": "#e8f0fb", "blue_stroke": "#8fb2dd",
    "amber": "#8a6011", "amber_fill": "#fbf1de", "amber_stroke": "#d9b878",
    "rose": "#a4472c", "rose_fill": "#fbeae5", "rose_stroke": "#dda694",
    "line": "#7b98a3",
}


# ---------------------------------------------------------------- primitives

def esc(s):
    return escape(str(s))


def header(w, h, title, desc, t):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="t d">
  <title id="t">{esc(title)}</title>
  <desc id="d">{esc(desc)}</desc>
  <defs>
    <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
      <path d="M32 0H0V32" fill="none" stroke="{t['grid']}" stroke-opacity="{t['grid_op']}"/>
    </pattern>
    <marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0 10 5 0 10z" fill="{t['line']}"/>
    </marker>
    <marker id="ara" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0 10 5 0 10z" fill="{t['accent']}"/>
    </marker>
    <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0 10 5 0 10z" fill="{t['rose']}"/>
    </marker>
    <marker id="arb" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0 10 5 0 10z" fill="{t['blue']}"/>
    </marker>
    <marker id="arm" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0 0 10 5 0 10z" fill="{t['amber']}"/>
    </marker>
  </defs>
  <rect width="{w}" height="{h}" rx="14" fill="{t['bg']}"/>
  <rect width="{w}" height="{h}" rx="14" fill="url(#grid)"/>
  <g font-family="{FONT}">'''


FOOTER = "  </g>\n</svg>\n"


def zone(x, y, w, h, label, t, label_col=None):
    c = label_col or t["faint"]
    return (f'    <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{t["zone"]}" '
            f'stroke="{t["zone_stroke"]}" stroke-dasharray="6 5"/>\n'
            f'    <text x="{x + 16}" y="{y + 24}" fill="{c}" font-size="12.5" '
            f'font-weight="600" letter-spacing="1.9">{esc(label)}</text>\n')


def box(x, y, w, h, kicker, title, t, tone="panel", lines=(), mono=False):
    fill = {"panel": t["panel"], "accent": t["accent_fill"], "blue": t["blue_fill"],
            "amber": t["amber_fill"], "rose": t["rose_fill"]}[tone]
    stroke = {"panel": t["stroke"], "accent": t["accent_stroke"], "blue": t["blue_stroke"],
              "amber": t["amber_stroke"], "rose": t["rose_stroke"]}[tone]
    kcol = {"panel": t["muted"], "accent": t["accent"], "blue": t["blue"],
            "amber": t["amber"], "rose": t["rose"]}[tone]
    s = (f'    <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{fill}" '
         f'stroke="{stroke}" stroke-width="1.4"/>\n')
    cy = y + 22
    if kicker:
        s += (f'    <text x="{x + 14}" y="{cy}" fill="{kcol}" font-size="10.5" '
              f'font-weight="600" letter-spacing="1.4">{esc(kicker)}</text>\n')
        cy += 21
    else:
        cy = y + 25
    if title:
        s += (f'    <text x="{x + 14}" y="{cy}" fill="{t["text"]}" font-size="15" '
              f'font-weight="600">{esc(title)}</text>\n')
        cy += 18
    for ln in lines:
        fam = f' font-family="{MONO}"' if mono else ""
        s += (f'    <text x="{x + 14}" y="{cy}" fill="{t["muted"]}" font-size="11.5"{fam}>'
              f'{esc(ln)}</text>\n')
        cy += 15
    return s


def person(cx, cy, label, sub, t):
    return (f'    <circle cx="{cx}" cy="{cy - 16}" r="15" fill="{t["accent_fill"]}" stroke="{t["accent"]}" stroke-width="1.6"/>\n'
            f'    <path d="M{cx - 22} {cy + 26}a22 22 0 0 1 44 0" fill="{t["accent_fill"]}" stroke="{t["accent"]}" stroke-width="1.6"/>\n'
            f'    <text x="{cx}" y="{cy + 48}" text-anchor="middle" fill="{t["text"]}" font-size="14" font-weight="600">{esc(label)}</text>\n'
            f'    <text x="{cx}" y="{cy + 65}" text-anchor="middle" fill="{t["muted"]}" font-size="11.5">{esc(sub)}</text>\n')


def path(d, t, dash=None, tone="line", head=True, tail=False):
    col = {"line": t["line"], "accent": t["accent"], "rose": t["rose"],
           "blue": t["blue"], "amber": t["amber"]}[tone]
    mk = {"line": "ar", "accent": "ara", "rose": "arr", "blue": "arb", "amber": "arm"}[tone]
    a = f' marker-end="url(#{mk})"' if head else ""
    b = f' marker-start="url(#{mk})"' if tail else ""
    da = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'    <path d="{d}" fill="none" stroke="{col}" stroke-width="1.6"'
            f'{da}{a}{b}/>\n')


def cap(x, y, text, t, anchor="middle", col=None, size=11):
    return (f'    <text x="{x}" y="{y}" text-anchor="{anchor}" fill="{col or t["faint"]}" '
            f'font-size="{size}">{esc(text)}</text>\n')


def title_block(x, y, kicker, title, t):
    return (f'    <text x="{x}" y="{y}" fill="{t["accent"]}" font-size="11.5" font-weight="600" '
            f'letter-spacing="2.2">{esc(kicker)}</text>\n'
            f'    <text x="{x}" y="{y + 27}" fill="{t["text"]}" font-size="21" '
            f'font-weight="700">{esc(title)}</text>\n')


# ------------------------------------------------------------------ diagrams

def c4_context(t):
    W, H = 1180, 660
    s = header(W, H, "System context: My AI Office",
               "C4 level 1. Denis interacts with My AI Office, which reads approved mail, Telegram "
               "and research sources, calls external model providers, and publishes briefings back "
               "into Telegram.", t)
    s += title_block(40, 44, "C4 LEVEL 1 · SYSTEM CONTEXT", "My AI Office", t)
    s += cap(40, 98, "Who uses it, what it reads, and what it depends on.", t, anchor="start")

    # centre system
    s += (f'    <rect x="415" y="266" width="350" height="128" rx="12" fill="{t["accent_fill"]}" '
          f'stroke="{t["accent"]}" stroke-width="2"/>\n')
    s += cap(590, 300, "SOFTWARE SYSTEM", t, col=t["accent"], size=10.5)
    s += (f'    <text x="590" y="333" text-anchor="middle" fill="{t["text"]}" font-size="22" '
          f'font-weight="700">My AI Office</text>\n')
    s += cap(590, 356, "Self-hosted agent, workers, knowledge base", t, col=t["muted"], size=12)
    s += cap(590, 375, "One private VPS · 13 containers", t, col=t["muted"], size=12)

    s += person(140, 300, "Denis", "Owner and operator", t)

    s += box(40, 452, 300, 92, "INTERFACE + SOURCE", "Telegram", t, tone="blue",
             lines=["Bot DM, forum topics, MTProto session",
                    "~150–200 followed channels"])
    s += box(370, 452, 240, 92, "SOURCE", "AgentMail", t, tone="blue",
             lines=["Personal mailbox", "Work mailbox"])
    s += box(640, 452, 300, 92, "SOURCE", "Research platforms", t, tone="blue",
             lines=["Reddit · Hacker News · GitHub · X",
                    "Bluesky · YouTube · Polymarket · web"])
    s += box(840, 150, 300, 96, "DEPENDENCY", "Model providers", t, tone="amber",
             lines=["OpenAI — primary interactive route",
                    "Qwen, DeepSeek — fallback chain"])
    s += box(40, 150, 300, 96, "DEPENDENCY", "Obsidian vault on the Mac", t, tone="amber",
             lines=["Syncthing, bidirectional",
                    "The wiki the owner can edit by hand"])
    s += box(970, 452, 170, 92, "OPERATOR", "Dashboard", t,
             lines=["Caddy, TLS + mTLS", "Hermes auth"])

    s += path("M182 292H405", t, tone="accent")
    s += cap(295, 283, "asks, saves, decides", t, col=t["accent"])
    s += path("M405 340H182", t, tone="accent")
    s += cap(295, 361, "briefings, alerts, answers", t, col=t["accent"])

    s += path("M190 246V266H415", t, tone="amber", tail=True)
    s += path("M840 198H765V266", t)
    s += cap(806, 190, "bounded calls", t)
    s += path("M190 452V420H415V394", t)
    s += path("M490 452V394", t)
    s += path("M790 452V420H700V394", t)
    s += path("M1010 452V420H765V394", t, dash="5 5")

    s += (f'    <path d="M40 596H1140" stroke="{t["zone_stroke"]}"/>\n')
    s += cap(40, 624, "Solid: data flows continuously.   Dashed: on demand or on a schedule.",
             t, anchor="start")
    s += cap(1140, 624, "ADR-0001 · ADR-0002 · ADR-0008", t, anchor="end", col=t["faint"])
    return s + FOOTER


def c4_container(t):
    W, H = 1240, 862
    s = header(W, H, "Container view: the benka-hermes Compose project",
               "C4 level 2. Thirteen containers grouped by responsibility: one public edge, the "
               "Hermes agent layer, the Redis bus with six workers, and the knowledge services.", t)
    s += title_block(40, 44, "C4 LEVEL 2 \u00b7 CONTAINERS", "benka-hermes \u00b7 13 services on one host", t)
    s += cap(40, 98, "Only one container has a published listener. Everything else binds internally.",
             t, anchor="start")

    s += zone(36, 120, 268, 150, "PUBLIC EDGE", t, t["rose"])
    s += box(56, 156, 228, 92, "THE ONLY PUBLISHED PORT", "caddy", t, tone="rose",
             lines=["TLS + mTLS on :8451", "Client certificate required"])

    s += zone(330, 120, 500, 150, "HERMES AGENT LAYER", t, t["accent"])
    s += box(350, 156, 208, 92, "ORCHESTRATION", "gateway", t, tone="accent",
             lines=["Telegram polling \u00b7 profiles", "native tools \u00b7 cron owner"])
    s += box(602, 156, 208, 92, "OPERATOR UI", "dashboard", t, tone="accent",
             lines=["Shares the Gateway", "PID + network namespace"])

    s += zone(856, 120, 348, 150, "MODEL ROUTING", t, t["amber"])
    s += box(876, 156, 308, 92, "ASSIGNED WORKLOADS ONLY", "omniroute", t, tone="amber",
             lines=["Own provider and OAuth state",
                    "Not the universal route for every call"])

    s += zone(36, 300, 1168, 256, "EXECUTION LAYER \u00b7 one slot, one run", t, t["blue"])
    s += box(56, 340, 236, 174, "INTEGRATION BUS", "redis", t, tone="blue",
             lines=["Streams + consumer groups", "Slot dedupe \u00b7 pending list",
                    "Delivery receipts", "benka:reconcile", "AOF-persisted"])

    workers = [
        ("worker-email-personal", "Personal mailbox, digests"),
        ("worker-email-work", "Work mailbox, triage"),
        ("worker-telegram", "Channel digest, Telethon"),
        ("worker-signals", "Rules, alerts, mini-batches"),
        ("worker-last30days", "Personal Feed, Platform Pulse"),
        ("worker-maintenance", "Wiki lifecycle, LightRAG upkeep"),
    ]
    for i, (name, sub) in enumerate(workers):
        col, row = i % 3, i // 3
        s += box(316 + col * 296, 340 + row * 96, 276, 78, "", name, t, lines=[sub])
    s += path("M292 379H316", t, tone="blue")
    s += path("M292 475H316", t, tone="blue")
    s += cap(52, 540, "Each worker: its own manifest, config, cursor, consumer group, and one "
             "allowlisted delivery route \u2014 a worker cannot choose a destination from the "
             "content it just read.", t, anchor="start", col=t["blue"])

    s += zone(36, 596, 1168, 176, "KNOWLEDGE SERVICES", t, t["amber"])
    s += box(56, 638, 356, 100, "SOURCE OF TRUTH", "wiki", t, tone="amber",
             lines=["Writes source-backed Markdown first,",
                    "then asks LightRAG to index it"])
    s += box(444, 638, 356, 100, "DERIVED INDEX", "lightrag", t, tone="amber",
             lines=["Graph + vector retrieval over an",
                    "explicit allowlist of roots"])
    s += box(832, 638, 372, 100, "READ-ONLY INPUT", "Vault + private archive", t,
             lines=["Owner-editable Obsidian Markdown; SQLite FTS",
                    "archive searched only on explicit request"])

    s += path("M284 202H350", t, tone="rose")
    s += cap(317, 194, "proxy", t, col=t["rose"])
    s += path("M558 202H602", t, tone="accent", dash="4 4", tail=True)
    s += path("M810 202H876", t, dash="5 5")
    s += path("M454 248V286H174V340", t, tone="accent")
    s += cap(462, 282, "cron enqueues one job per slot", t, anchor="start", col=t["accent"])
    s += path("M300 556V638", t, dash="5 5")
    s += cap(308, 604, "workers write", t, anchor="start")
    s += path("M412 688H444", t, tone="amber")
    s += cap(428, 712, "index", t, col=t["amber"])
    s += path("M832 688H804", t, dash="5 5")

    s += cap(1204, 812, "ADR-0003 \u00b7 ADR-0005 \u00b7 ADR-0010", t, anchor="end", col=t["faint"])
    return s + FOOTER


def job_lifecycle(t):
    W, H = 1180, 560
    s = header(W, H, "Lifecycle of one scheduled job",
               "A cron slot becomes a stable run id, a queued job, a claimed job, a validated "
               "artifact, and finally a confirmed delivery. An unknown outcome goes to manual "
               "reconciliation and is never retried automatically.", t)
    s += title_block(40, 44, "STATE MACHINE", "One slot, one run — and what happens when it is unclear", t)

    states = [
        (40, 150, "01", "cron slot", ["Hermes cron fires for a", "time slot in Europe/Moscow"]),
        (256, 150, "02", "stable run id", ["Derived from the slot,", "not from the clock"]),
        (472, 150, "03", "queued", ["XADD to the stream;", "slot dedupe is atomic"]),
        (688, 150, "04", "claimed", ["Consumer group; entry", "sits in the pending list"]),
        (904, 150, "05", "processing", ["Fetch · cursor · rules ·", "bounded model call"]),
    ]
    for x, y, n, title, lines in states:
        s += box(x, y, 196, 104, n, title, t, lines=lines)
    for x in (236, 452, 668, 884):
        s += path(f"M{x} 202H{x + 20}", t)

    s += box(256, 336, 196, 104, "06", "validated", t, lines=["Strict JSON or the", "deterministic fallback"])
    s += box(472, 336, 196, 104, "07", "sent", t, lines=["hermes send to an", "allowlisted route"])
    s += box(688, 336, 236, 104, "08", "confirmed", t, tone="accent",
             lines=["success + message_id,", "no skipped flag"])
    s += path("M1002 254V300H452V336", t)
    s += cap(700, 292, "result", t)
    s += path("M452 388H472", t)
    s += path("M668 388H688", t)

    s += box(40, 336, 196, 104, "FALLBACK", "deterministic", t, tone="blue",
             lines=["Rule-based output when", "every provider fails"])
    s += path("M236 372H256", t, tone="blue")

    s += box(944, 336, 196, 104, "UNCERTAIN", "reconcile", t, tone="rose",
             lines=["benka:reconcile —", "a human decides"])
    s += path("M924 388H944", t, tone="rose")
    s += cap(1042, 462, "Never retried automatically.", t, col=t["rose"])
    s += cap(1042, 479, "No automatic cleanup.", t, col=t["rose"])

    s += cap(806, 462, "The completed record is written", t)
    s += cap(806, 479, "before XACK, so a crash between", t)
    s += cap(806, 496, "the two repeats work rather than losing it.", t)

    s += (f'    <path d="M40 512H1140" stroke="{t["zone_stroke"]}"/>\n')
    s += cap(40, 538, "A successful exit code is not a delivery. Only a message_id is.",
             t, anchor="start", col=t["accent"])
    s += cap(1140, 538, "ADR-0003 · ADR-0007", t, anchor="end", col=t["faint"])
    return s + FOOTER


def memory_layers(t):
    W, H = 1180, 620
    s = header(W, H, "The five memory layers",
               "Live state, raw evidence, the curated wiki, the retrieval index, and compact agent "
               "memory each answer a different question. The wiki is the store; retrieval is "
               "derived from it.", t)
    s += title_block(40, 44, "KNOWLEDGE MODEL", "Five layers, five different questions", t)

    rows = [
        (140, "LIVE STATE", "Running services, current jobs, fresh source data",
         "What is true right now?", "Checked against the system, never recalled from memory.", "rose"),
        (232, "RAW EVIDENCE", "Imported material, original sources, private transcripts",
         "What exactly was said?", "Kept for provenance. Not indexed, not loaded into context.", "panel"),
        (324, "CURATED WIKI", "Decisions, research, entities, idea chains — plain Markdown",
         "What did we conclude?", "The source of truth. Obsidian-compatible and owner-editable.", "accent"),
        (416, "RETRIEVAL INDEX", "LightRAG graph + vector over an allowlist of roots",
         "Where have I seen this?", "Derived from the wiki. Rebuildable; never the only copy.", "amber"),
        (508, "AGENT MEMORY", "Compact stable facts and preferences",
         "What should I already know?", "Small on purpose. Not a place to accumulate history.", "blue"),
    ]
    for y, kicker, what, question, note, tone in rows:
        s += box(40, y, 470, 76, kicker, what, t, tone=tone)
        s += (f'    <text x="546" y="{y + 30}" fill="{t["text"]}" font-size="14" '
              f'font-weight="600">{esc(question)}</text>\n')
        s += cap(546, y + 52, note, t, anchor="start", col=t["muted"], size=12)

    s += path("M22 150V576", t, head=False)
    for y in (178, 270, 362, 454, 546):
        s += path(f"M22 {y}H36", t)

    s += (f'    <text x="1140" y="150" text-anchor="end" fill="{t["accent"]}" font-size="12" '
          f'font-weight="600" letter-spacing="1.6">CAPTURE IS EXPLICIT</text>\n')
    s += cap(1140, 172, "Whole mailboxes and ordinary chat", t, anchor="end")
    s += cap(1140, 189, "are not indexed by default.", t, anchor="end")

    s += (f'    <path d="M40 596H1140" stroke="{t["zone_stroke"]}"/>\n')
    s += cap(40, 604, "", t)
    s += (f'    <text x="40" y="{H - 12}" fill="{t["muted"]}" font-size="12" '
          f'font-family="{MONO}">source → explicit capture → wiki artifact → index → grounded answer</text>\n')
    s += cap(1140, H - 12, "ADR-0005", t, anchor="end", col=t["faint"])
    return s + FOOTER


DIAGRAMS = {
    "c4-context": c4_context,
    "c4-container": c4_container,
    "job-lifecycle": job_lifecycle,
    "memory-layers": memory_layers,
}

OUT.mkdir(parents=True, exist_ok=True)
for name, fn in DIAGRAMS.items():
    for suffix, theme in (("light", LIGHT), ("dark", DARK)):
        p = OUT / f"{name}-{suffix}.svg"
        p.write_text(fn(theme), encoding="utf-8")
        print(f"wrote {p.name}  ({p.stat().st_size:,} bytes)")
