# Boot Checklist

> [!NOTE]
> **Predecessor-era prompt artifact.** This file configured the retired OpenClaw runtime, which
> mounted `workspace/` into the agent. **Hermes does not**: the live prompt surface is each profile's
> `SOUL.md` plus its installed skills, and nothing here is read at runtime.
>
> It is kept as a behavioural record — some rules here were carried into
> [`skills/`](../skills/), and some were not. It stays in Russian for the same reason the archive
> does. See [CONTRIBUTING.md](../CONTRIBUTING.md#language).

При каждом запуске новой сессии:

1. [ ] Загружен `MEMORY.md` (~2KB, всегда)
2. [ ] Загружен `memory/INDEX.md` → определены файлы сегодня/вчера
3. [ ] Загружен дневной файл сегодня (если есть)
4. [ ] Загружен дневной файл вчера (только если сегодня <3 записей)
5. [ ] LightRAG: `GET http://lightrag:9621/health` → статус зафиксирован (неблокирующий)
6. [ ] Незакрытые задачи из предыдущей сессии отмечены
7. [ ] Anti-sycophancy режим: **АКТИВЕН**
8. [ ] Готов: *"Гав. Слушаю."*

**Лимит старта: ~5–8KB. `raw/` не грузить. Архивные дневники — только через lightrag_query.**
