# TradingView author subscriptions for Signals

The Signals worker checks an author's RSS feed on its existing ruleset schedule. It alerts on
newly published ideas with the configured exchange and futures families. The original contract,
author, publication time, original link, and attribution appear in the Telegram message.
The alert follows a publication ID across polls, rule overlap, and changes to the post.

## Vesperfin and contract rollover

The initial rule watches `vesperfin` on RUS for Si and CR. It matches any continuous contract
such as `RUS:SI1!`, plus contracts in the H, M, U and Z cycles with a one-, two-, or four-digit
year such as `RUS:CRZ2026` and `RUS:SIH2027`. The rule can match several expiries at the same
time. Each publication keeps its own ticker and chart. [Author feed](https://ru.tradingview.com/feed/?username=vesperfin)

## Configuration

Copy the `source` object from the [reviewed example](../artifacts/signals-bridge/rules/tradingview.vesperfin.json)
into `sources.tradingview_rss` in the private Signals config. Add its `rule` to the existing
scheduled ruleset's `rules` list. In production, use `trading-si-watch`. For another author,
give the source and rule new IDs and set the author in both places. For a different exchange or
instrument family, set `exchange` and `families` on the rule.

- `link` sends title, author, contract, timestamp and source link. It is the default.
- `chart` also sends the unmodified RSS chart with attribution in the caption. The Vesperfin
  rule uses this mode. [TradingView attribution terms](https://www.tradingview.com/policies/#4-attribution)
- `full` adds the original RSS description, split into Telegram-sized messages. Use this mode
  where the original text can be republished. Posts with a missing or visibly abbreviated
  description direct the reader to the source.

The adapter verifies the publisher and exchange-qualified ticker in RSS. It only accepts chart
URLs on the TradingView CDN with the same idea ID as the post. A chart absent from RSS or removed
from the CDN results in a text notification with the original link. Transient media failures
leave the delivery pending. TradingView content goes to the notification renderer directly.

## Activation, backfill, and delivery receipts

New sources skip the past by default. Set `start_at` to an explicit ISO timestamp with timezone
before the first successful poll to include a bounded backfill. Redis persists that watermark,
so a restart or repeated RSS response cannot replay the window. RSS has a bounded history and the
worker reports possible gaps if the last successful poll predates the oldest returned item.

The worker saves newly accepted ideas and their delivery payloads in Redis before sending. It
drains pending deliveries even when an RSS poll fails and uses a stable Hermes journal identity
per Telegram part. Confirmed messages survive retries, including a confirmed chart followed by
a failed text part. For an ambiguous send, verify the Telegram topic and the Hermes delivery
receipt before clearing or retrying it. See [reconciliation](hermes/operations.md#schedules-and-queues).

## Verification

Run `.venv/bin/python scripts/test-hermes.py --suite signals --suite hermes`. The cases cover
the exchange and author filters, rollover and continuous symbols, chart selection, body
splitting, overlapping matches, first activation, backfill, and recovery after a partial send.
The production check confirms the selected job and its Telegram chart receipt in Signals.

The initial production backfill on November 26, 2026 used a 48-hour window. Signals delivered
one matching `CRZ2026` idea. The latest `SIZ2026` idea was earlier than the window. The chart,
original link, and topic were verified by reading the delivered Telegram message.
