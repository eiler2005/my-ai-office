# Протокол проверок и готовности

Дата: 2026-09-06. **Статус `MIGRATION_IN_PROGRESS`**. Публикация кода не означает `READY_NOT_ACTIVE` или завершение миграции.
По указанию Дениса дальнейшие сборки и тесты выполняются на VPS; GitHub Actions не используется.
Производственные токены/бот/почта/Syncthing в репетиционных тестах не используются.

## Уже проверено

До уточнения места тестирования выполнен локальный изолированный прогон:

| Набор | Результат |
|---|---|
| Hermes safety/migration/archive/cron/profiles/maintenance + native model fixtures | 42 passed |
| AgentMail | 19 passed |
| Telegram Digest | 21 passed |
| Signals / Last30Days | 98 passed |
| Wiki-import | 26 passed |
| Итого | **206 passed** |
| Native Hermes plugin / cron / AIAgent contract | 7 tools зарегистрированы; paused cron idempotent; API-параметры совместимы |
| Compose configuration | `config --quiet` проходит |
| История и working tree на секреты | Начальный скан: 1119 объектов, 30 reviewed совпадений, 0 неразобранных; повторяется перед публикацией |
| VPS inventory | Read-only проверены оба VPS; подробности в закрытых JSON-отчётах |

Native model tests используют настоящий закреплённый `AIAgent` и локальный HTTP/SSE fixture:
проверены отсутствие инструментов/унаследованной памяти, 401 → резерв и завершение по timeout.
Они не доказывают доступность реальных OAuth/provider аккаунтов.

Snapshot tests проверяют SHA всего архива/каждого файла, tamper, path traversal, повторный импорт,
прерванный restore и отсутствие перезаписи. Queue/delivery tests проверяют slot dedupe, pending reconciliation,
confirmed message IDs и запрет повторения uncertain sends. Это не замена реальному Telegram smoke.

## Проверки на VPS

Результаты серверного прогона добавляются после выполнения. Использовать отдельные имена контейнеров, volumes и
ограничения ресурсов. Состояние production и соседние проекты не подключать.

| Проверка | Статус до серверной репетиции | Что закрывает |
|---|---|---|
| Сборка закреплённого Docker image, включая dashboard и Last30Days | PENDING | Воспроизводимость Linux runtime |
| Регрессии в контейнере на VPS | PENDING | Повторение изолированных suites в целевой архитектуре |
| Standby с отключённой сетью | PENDING | Нет polling, cron/delivery и production secrets |
| Native plugin/cron/model contracts на VPS | PENDING | Совместимость pinned Hermes в целевой среде |
| Реальный Redis и рестарт контейнера | PENDING | Durable slot/receipt/PEL восстановление |
| TLS/mTLS, authentication, WebSocket dashboard | PENDING | Реальная панель за Caddy |

## До `READY_NOT_ACTIVE`

- Закрыть реестр фактических source files, cron всех уровней, размеров томов и pinned образов LightRAG/OmniRoute/Syncthing.
- Перенести необходимые изменения незакоммиченного OpenClaw проекта, не включая незавершённое обновление runtime автоматически.
- Подготовить полный закрытый deployment manifest: все workers, scoped Redis/wiki/RAG, модели, пути, volumes, домен панели.
- Проверить domain routing/ACL/context isolation с реальным Gateway и отдельным тестовым ботом; подготовить проверенные SOUL/USER/MEMORY/skills.
- Выполнить репетицию на проверенной резервной копии, native importer dry-run/import, повтор/прерывание/восстановление и поиск архива.
- Проверить оба ящика, Telegram sources/cursors, оба Last30Days пресета, triage, идеи/promotion, контрольные LightRAG запросы.
- Проверить каждый provider/reserve, неверный JSON, auth errors, timeout и отказ всех моделей с детерминированным результатом.
- Провести совместный прогон Telegram запроса, дайджеста и индексации; оценить OOM/restarts/рост очереди.
- Проверить рестарт, перезагрузку и восстановление на VPS; соседние сервисы остаются здоровыми.
- Проверить откат до и после новых записей, включая deliveries, cursor merge и pending; одного vault-delta отчёта недостаточно.
- Оставить production connections выключенными и все производственные cron paused. Только после этого зафиксировать READY.

Для внешних проверок ещё нужны место хранения конфигурации отдельного тестового Telegram-бота, домен панели/сертификаты,
проверенная резервная копия и окончательные закрытые привязки контуров. Секреты в чат или Git не помещать.

## После отдельной команды переключения

Повторить inventory/drift review, перенести свежую холодную копию за весь период ожидания, проверить единственного polling owner.
Закрыть всю функциональную матрицу плана. Наблюдать минимум 48 часов с реальными ежедневными запусками.
Еженедельное обслуживание проверить на копии; подтвердить восстановление. До этого миграция не считается завершённой.

## Формат записи каждого прогона

Записывать дату, Git SHA + dirty flag, image ID, pinned Hermes SHA, dataset class, команду, counts/result и оставшиеся gaps.
Логи с содержимым писем/диалогов, receipt IDs, endpoint details и auth хранятся приватно; в Git — только обезличенный результат.
Health-check не закрывает функциональную приёмку.
