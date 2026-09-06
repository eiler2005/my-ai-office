# Knowledge Management: Ideas + Knowledgebase

> [!NOTE]
> **Archived — OpenClaw era.** This document describes the predecessor runtime and is kept as a
> historical engineering record. Production moved to Hermes Agent on **2026-09-06**; the commands
> and state below do not deploy the current system.
>
> Current system: [architecture](../../architecture.md) ·
> [operations](../../hermes/operations.md) ·
> [cutover record](../../hermes/cutover-record-2026-09-06.md)

For the intuitive memory explanation behind this workflow, see
`docs/archive/openclaw/19-llm-wiki-memory-explained.md`.
For the technical memory model, see `docs/archive/openclaw/10-memory-architecture.md`.
For the runtime query path, see `docs/archive/openclaw/15-llm-wiki-query-flow.md`.

This file is the **behavior contract** for `Ideas` and `Knowledgebase`.
It is not the main architecture document for the full memory stack.

Система управления знаниями построена на двух топиках в `Ben'ka_Clawbot_SuperGroup` и трёх бэкендах хранения.

---

## Архитектура

```
Любой источник
  │
  ├─► 💡 Ideas (topic_id=639)        ← быстрый захват, без структуры
  │     │ авто-захват + теги
  │     │ промоушен по команде
  │     ▼
  └─► 📚 Knowledgebase (topic_id=232) ← база знаний
        │ поиск (вопрос → ответ с цитатами)
        │ сохранение (любой контент → авто-структура)
        ▼
   wiki-import bridge
        │
        ├─► Obsidian vault (wiki/**/*.md)   — читаемая база
        ├─► LightRAG index                  — поиск (граф + вектор)
        └─► workspace memory                — контекст агента
```

---

## 💡 Ideas — захват без усилий

**Что кидать:**
- Пересланные посты из Telegram-каналов
- Ссылки на статьи, видео, документы
- Мысли, фрагменты, черновые тезисы
- Скриншоты с подписью

**Как работает (автоматически):**
1. Бенька читает всё в топике без упоминания
2. Извлекает суть, присваивает теги (domain, source_type)
3. Оценивает важность; если < 0.35 — молча игнорирует
4. Создаёт `raw/**` + light-curated `wiki/research/**` через `wiki_ingest(capture_mode=ideas)`
5. Отвечает кратко: `✅ Захвачено в wiki: [тема]`

**Промоушен в Knowledgebase:**
```
Бенька, промоутни лучшее из Ideas за эту неделю
Бенька, сохрани последний пост в базу знаний
Бенька, добавь это в knowledgebase (в ответ на конкретный пост)
```
Бот покажет список и попросит подтверждение перед записью.

**Что НЕ происходит автоматически:**
- Контент не превращается сразу в heavy canonical graph без нужной уверенности
- Бот НЕ пишет длинный анализ на каждый пост

---

## Operating Principle

Главное правило выбора:

- `Ideas` = **не потерять**
- `Knowledgebase` = **запомнить системой**

Выбирать нужно не по теме сообщения, а по намерению:

- если материал сырой, сомнительный, черновой или его просто хочется быстро закинуть во входящий буфер — это `Ideas`
- если материал должен стать частью долговременной базы знаний и потом находиться через поиск — это `Knowledgebase`

Короткая формула:

- `Ideas` — capture now, curate deeper later
- `Knowledgebase` — commit в wiki

Это означает:

- не "почти всё в Ideas"
- не "всё сразу в Knowledgebase"
- а "сырой поток → Ideas, знание которое надо зафиксировать → Knowledgebase"

### Примеры на последних кейсах

**1. Sequoia — _Services: The New Software_**

- Если цель: "интересная статья, потом решу сохранять ли" → `Ideas`
- Если цель: "хочу, чтобы это стало частью базы знаний и находилось потом через поиск" → сразу `Knowledgebase`

**2. Длинный пост про coding agents / смещение работы на края**

- Если цель: "интересное наблюдение, не уверен что это knowledge artifact" → `Ideas`
- Если цель: "это наш принцип / полезная мысль, хочу чтобы система это помнила" → `Knowledgebase`

**3. Короткий вопрос**

- "почему выбрали LightRAG?" → `Knowledgebase`, но в режиме `Search`, а не `Save`

**4. Длинный текст без желания сохранить**

- если ты хочешь именно обсудить, а не коммитить в базу, в `Knowledgebase` начинай сообщение с `обсуди:`

### Личный operating rule

Если материал **скорее да, чем нет** должен попасть в память системы — отправляй сразу в `Knowledgebase`.

Если материал **скорее нет, чем да**, или это просто поток входящих ссылок и мыслей — отправляй в `Ideas`.

---

## 📚 Knowledgebase — поиск и хранение

### Режим 1: Поиск

Напиши любой вопрос открытым текстом:

```
почему выбрали LightRAG?
что знаем про Syncthing?
как работает signals-bridge?
расскажи про eb1 визу
```

Бенька ищет по трём источникам одновременно:
- `LightRAG hybrid` — граф + вектор (workspace + Obsidian wiki + signals)
- `memory search` — BM25 + Gemini (быстрый recall)

После retrieval Бенька должен открыть 2–5 top references и проверить сами страницы. Ответ «ничего релевантного не найдено» допустим только после этой проверки, а не по одним заголовкам/сниппетам.
Из открытых страниц Бенька должен извлечь 2–4 supportable facts или короткие доказательные snippets, а не пересказывать вслепую prose blob из `LightRAG`.
В этом режиме поиск в интернете не должен запускаться по умолчанию. Если локальная база знаний ничего не дала, правильный следующий шаг — честно сказать, что в `Knowledgebase` не найдено релевантного контента, и только потом предложить отдельный интернет-поиск. Интернет допустим сразу только по явной формулировке вроде «поищи в интернете», `latest`, `online` или если запрос требует внешней свежей информации по смыслу.

Если refs уже подтверждают хотя бы часть ответа, generic fallback в стиле «недостаточно информации» запрещён. Вместо этого ответ должен честно фиксировать границы знания: «в открытых refs нашлись X и Y, но прямого подтверждения Z нет».
Для ответов на мысли, посты, принципы и broad themes Бенька должен отвечать не только коротким тезисом, но и более развёрнутым synthesis-блоком: что повторяется, почему это важно и что из этого может быть полезно тебе.
Когда provenance позволяет, в ответе нужен блок `Источники`: `Wiki`, `Исходник` (URL) и `Telegram` deeplink на исходный пост. Абсолютный `raw_source` path допустим только как последний fallback, если другого человеческого source-link нет.

Формат ответа:
```
🔍 Запрос: «почему выбрали LightRAG»

Короткий вывод: LightRAG выбрали как retrieval layer между wiki и runtime-ответом, чтобы доставать исторические решения без загрузки больших объёмов памяти.

• LightRAG в этой системе — derived index, а не source of truth.
Источник: wiki/entities/lightrag.md

• Выбор мотивирован hybrid retrieval и graph-aware recall поверх wiki/workspace корпуса.
Источник: wiki/decisions/why-lightrag.md

• В открытых refs нет признаков, что LightRAG заменяет wiki как canonical storage.
Источник: wiki/decisions/why-lightrag.md

Что это значит:
- wiki остаётся местом, где знание становится видимым и проверяемым
- LightRAG полезен для recall и synthesis, но не должен подменять source pages

Источники:
- Wiki: wiki/entities/lightrag.md
- Wiki: wiki/decisions/why-lightrag.md
- Исходник: если page содержит canonical URL, показать его рядом
```

### Режим 2: Сохранение знания

Пересылай пост, кидай ссылку или пиши текст — **никакой ручной структуры не нужно**.

Бот сам извлекает: title, domain, source, date, summary, sensitivity — и вызывает `wiki_ingest`.
Если в сообщении есть надёжный URL, предпочтительный путь — прямой `wiki_ingest(url)` без лишнего промежуточного пересказа.
Приоритет такой: save-команда, пересланный пост, URL и длинный multiline текст должны идти в сохранение даже если сообщение похоже на рассуждение; в `Search` должны идти только короткие вопросоподобные запросы.
Если хочешь именно обсудить текст в `Knowledgebase`, а не сохранить его, начни сообщение с `обсуди:`.

```
[пересланный пост из канала]
→ ✅ Сохранено: «Новые возможности Claude 4» → AI/LLM

https://some-article.com/interesting
→ ✅ Сохранено: «Статья про X» → AI/research

просто текст который хочу запомнить
→ ✅ Сохранено: «Личная заметка» → personal
```

Бот инжестит в Obsidian wiki сразу, а потом делает immediate LightRAG enqueue по затронутым `wiki/**` страницам.
Если бот вместо `✅ Сохранено: ...` начинает просто спорить или комментировать длинный пост, значит сообщение было ошибочно смаршрутизировано как диалог, а не как ingest.
Если бот говорит только про `LightRAG upload`, `track_id` или `queued`, а реальной `wiki/research/**` страницы нет, это тоже ошибка маршрута.
Рекомендуемый pinned message для топика должен явно обещать: длинный контент здесь сохраняется по умолчанию, а `обсуди:` отключает автосохранение.
Если во время сохранения был промежуточный tool failure, но следующий retry успешно завершил запись, пользовательский итог должен оставаться человеческим: короткое объяснение причины сбоя + подтверждение, что финальное сохранение прошло. Сырой `Edit failed` не должен становиться главным пользовательским сообщением.

---

## Полный флоу: от поста до базы знаний

```
1. Видишь интересный пост в Telegram
   │
   ▼
2. Пересылаешь в 💡 Ideas
   (без комментария — работает само)
   │
   ▼
3. Бенька: ✅ Захвачено: [тема]. Тег: AI/LLM
   │
   ▼
4. Когда удобно (хоть через неделю):
   «Бенька, промоутни лучшее из Ideas»
   │
   ▼
5. Бенька показывает список захваченного,
   ты говоришь «да» / «нет» / «вот этот»
   │
   ▼
6. прямой `wiki_ingest(url|text)` → `raw/**` + `wiki/research/**` → optional canonical updates → LightRAG index
   │
   ▼
7. Через 30 мин поиск находит это в 📚 Knowledgebase
```

Для исторических постов из `📚 Knowledgebase`, которые раньше были сохранены как `raw/articles + LightRAG`
без реальной wiki-страницы, используем backfill helper:

```bash
OPENCLAW_HOST="deploy@<server-host>" bash scripts/backfill-knowledgebase-to-wiki.sh --dry-run
OPENCLAW_HOST="deploy@<server-host>" bash scripts/backfill-knowledgebase-to-wiki.sh --apply
```

Он берёт только неслужебные человеческие сообщения из topic `232` и прогоняет их через
`wiki-import` в два шага: сначала в source-centric light mode, чтобы historical saves точно
материализовались в `wiki/research/**`, а затем точечно запускает `promotion` для high-signal
материалов. Так legacy saves становятся частью настоящей LLM-Wiki, но без массового заднего
раздувания canonical graph.

High-signal auto-promotion intentionally uses a narrow heuristic set:
- URL article source
- strong title markers such as `architecture`, `memory`, `metrics`, `evaluation`, `retrieval`, `taxonomy`, `framework`
- known topic pairs such as `llm + memory`, `llm + metrics`, `agent + architecture`
- body/source signals such as `arxiv.org`, `benchmark`, `grammar`, `evaluation`

Everything else stays in `ideas/light` until Denis explicitly asks for promotion.

Для исторических Telegram-каналов и повторяемых incremental updates см.
[docs/archive/openclaw/18-telegram-historical-ingest.md](18-telegram-historical-ingest.md).

---

## Источники данных для поиска

| Источник | Путь | Обновление |
|---|---|---|
| Obsidian wiki | `/opt/obsidian-vault/wiki/**/*.md` | Syncthing + LightRAG cron 30 мин |
| Workspace memory | `/opt/openclaw/workspace/*.md` | Deploy workspace |
| Signals/digests | `/opt/obsidian-vault/raw/signals/**/*.md` | Telethon Digest → LightRAG cron |
| Ideas explicit save | → wiki/research/ (light curation) | wiki-import bridge |
| Ideas (после промоушена) | existing wiki artifact gets enriched | wiki-import bridge |

---

## Команды быстрого доступа

| Команда | Где | Что делает |
|---|---|---|
| Любой вопрос | 📚 Knowledgebase | Поиск по всей базе |
| Любой пост / ссылка / текст | 📚 Knowledgebase | Авто-структура + сохранение в wiki |
| Любой пост / ссылка / текст | 💡 Ideas | Light-curated save в `wiki/research/**` |
| `Бенька, промоутни из Ideas` | inbox / DM | Пакетный промоушен с подтверждением |
| `Бенька, что в очереди Ideas?` | inbox / DM | Показать накопленное |

---

## Связанные документы

- [docs/archive/openclaw/10-memory-architecture.md](10-memory-architecture.md) — классы памяти (RAW/DERIVED/CURATED)
- [docs/archive/openclaw/11-lightrag-setup.md](11-lightrag-setup.md) — LightRAG API и индексация
- [docs/archive/openclaw/15-llm-wiki-query-flow.md](15-llm-wiki-query-flow.md) — как работает поиск внутри
- [docs/archive/openclaw/18-telegram-historical-ingest.md](18-telegram-historical-ingest.md) — historical Telegram ingest и incremental updates
- [docs/archive/openclaw/12-telegram-channel-architecture.md](12-telegram-channel-architecture.md) — все Telegram-поверхности
