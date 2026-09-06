# Boot Checklist

> [!NOTE]
> **Deployed prompt artifact, not documentation.** This file is mounted into the running agent and
> is part of Benka's runtime behaviour. It is written in Russian because Benka converses with its
> owner in Russian; translating it would change what the agent does. See
> [CONTRIBUTING.md](../CONTRIBUTING.md#language) for the language rule.

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
