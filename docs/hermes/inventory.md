# Реестр переноса

Срез: 2026-09-06. Статус: `MIGRATION_IN_PROGRESS`. Адреса и секреты находятся в закрытом deployment manifest.

## Исходный набор

Кандидат создан отдельным клоном `openclaw_firststeps` от `1d7ffedd7a6fcb6ef10dba5d7ed52e48417f2279`.

В target сохранены также четыре первоначальных коммита My AI Office с обзором, архитектурой, ignore rules и MIT license.
Исходные активные ветки опубликованы под прежними `agent/...` именами; исходный main доступен как `legacy/openclaw-main`.
Миграционный код публикуется в main и migration/hermes-native. Истории объединяются без force push.
Исходный рабочий каталог содержит незакоммиченные изменения подготовки OpenClaw 2026.9.1 и другие правки.
Они не скопированы поверх проверенного runtime автоматически: их сопоставление с сервером ведётся в [журнале расхождений](drift-log.md).
Исторические ветки сохраняются локально. Резервная `backup/pre-scrub-20260411-144635` не предназначена для публикации без отдельной проверки причин очистки истории.

В живом Gateway при первом read-only probe используется image ID
`sha256:b4419b44f35397314015301ea5a248eb31037f05b2c82a777f12ad67d0fb5b97`; контейнер здоров.
Это зафиксированная исходная точка, а не указание обновлять OpenClaw.

## VPS Hermes и соседние проекты

Сведения найдены в `reddit-compass/docs/HOSTING.md`, `reddit-compass/deploy/hostkey/README.md`, Compose этого проекта,
а также `vps_management/docs/ownership-matrix.md` и `docs/containers.md`. Доступ — через alias `vps-hostkey-hermes`
и `vps_management/ansible/scripts/ssh-vps.sh`; секреты читаются штатным механизмом зашифрованного Ansible vault.

| Параметр | Проверено read-only 2026-09-06 |
|---|---|
| Target CPU / RAM | 8 CPU / 15 955 MiB RAM; доступно около 13.4 GiB |
| Target диск `/opt` | Около 113 GiB свободно, 25% занято |
| Существующие Compose-проекты | reddit-compass, moex-futoi, cheap-intelligence, stealth |
| Порты | 80, 443, 8450 заняты; 8451 и 9119 были свободны |
| Hermes Agent / каталог | Команда Hermes и `/opt/benka-hermes` при исходной проверке отсутствовали |
| Source CPU / RAM | 2 CPU / 3 819 MiB RAM; около 1.1 GiB доступно |
| Source диск | 87% занято; около 4.7 GiB свободно |

Порты 80/443 и SNI-маршрутизация принадлежат существующей инфраструктуре. Reddit Compass уже использует 8450.
Кандидат получает отдельный Compose-проект `benka-hermes-candidate`, каталог `/opt/benka-hermes` и Caddy на 8451;
9119 доступен только внутри сети контейнеров. Нужный SNI-маршрут на 443 — отдельная инфраструктурная настройка после выбора домена.
При переносе нельзя выполнять общий `docker compose down`, `docker system prune` или перезапуск чужого прокси.

Повторяемая инвентаризация: `scripts/inventory-hermes-host.py --role source|target`.
Скрипт только читает состояние, выводит имена переменных без значений, не выводит SSH-адреса и тела cron-команд.
Подробные JSON-отчёты сохраняются вне Git. Недоступные размеры отмечаются `unverified`, а не нулём.

Повторный source probe в 10:03 UTC показал около 3.57 GiB свободного места, config около 4.72 GiB,
LightRAG около 1.05 GiB и vault около 56 MiB. Размер Signals не подтверждён из-за прав/таймаута.
Найден дополнительный OpenClaw candidate вне Compose: production image остался прежним, кандидат не включается в baseline.
Автоматический поиск OpenClaw cron в config не дал подтверждённого реестра; отсутствие результата не означает отсутствие заданий.

Зафиксированные live image IDs зависимых сервисов: LightRAG
`sha256:baf0d07eaa73d2e0fa044fdab76767c69480737368a3fd88ffc86af1290f5259`, OmniRoute
`sha256:a70d7cb45db50d409b75c7a69b0255d856098abbc8ed6da48930a308a1953aa8`, Redis
`sha256:8b81dd37ff027bec4e516d41acfbe9fe2460070dc6d4a4570a2ac5b9d59df065`.
Для переноса нужны export/load этих образов либо подтверждённые registry digests; image ID сам по себе не является registry pull URL.

## Функции и данные

| Функция | Код Hermes | Переносимое состояние | Приёмка |
|---|---|---|---|
| Личность и память | curated `claw-layout`, native importer, domain profiles | SOUL/IDENTITY/USER/MEMORY, проверенные skills | Стиль и устойчивые сведения; новые сессии |
| Старые разговоры и дневники | `archive.py`, SQLite FTS5 | JSONL, Markdown, источник и номер строки | Поиск, повторная индексация, отчёт пропусков |
| Telegram ingress / темы | Native Gateway, `profiles.py` | Доверенные numeric IDs, темы, update watermark | Реальный inbound, follow-up, отрицательные ACL-тесты |
| Личная / рабочая почта | `pipelines.py` → `agentmail-email` | Inbox configs, cursors, dedupe, pending и triage | Оба ящика, пересылки, actionable/informational, отсутствие дублей |
| Telegram Digest | `pipelines.py` → `telethon-digest` | Telethon session, folders/channels, cursors, persisted releases | Источники, баланс категорий, корректные ссылки |
| Signals | `pipelines.py` → `signals-bridge` | Rulesets, event streams, locks, source refs, dedupe | Частичный отказ источника, доставка исходных материалов |
| Last30Days | Тот же native worker и pinned skill | Оба пресета, source settings, repeat history | personal-feed / platform-pulse, деградация отдельных источников |
| Wiki / Ideas | `wiki.py`, native plugin, прежний wiki-import | Vault, fingerprint, lifecycle metadata, ingest receipts | Capture, promotion без дубля, `обсуди:` без сохранения |
| LightRAG | `maintenance.py`, прежний embedding endpoint | Граф, KV/vector data, размерность 3072, model identity | Контрольные запросы; upload accepted отдельно от indexed |
| Redis | `queue.py`, `delivery.py` | RDB/AOF, streams/groups/pending, dedupe, доставки | Один slot, повторный запуск, сверка неопределённых отправок |
| OmniRoute | Сохранённый сервис, модельные конфигурации | SQLite/OAuth/routes и provider credentials | Каждый primary/reserve, время отказа, полный fallback |
| Syncthing | Отдельный сервис с новой device identity | Vault и проверенная карта папок | Сверка Mac/target без неожиданных удалений |
| Веб-панель / CLI | Native Hermes, отдельный dashboard, Caddy | Конфигурация, scoped sessions, auth | Вход, чат, WS, настройки, отказ посторонним |

Форматы существующих Redis-полей и wiki `source_type`, `source`, `capture_mode`, `promote_fingerprint`,
`wiki_page_paths`, `raw_path`, `rag_status` сохраняются. Новые ключи имеют префикс `benka:`.
Полные письма не включаются в RAG по умолчанию. В архив каждого контура импортируются только его данные.

## Расписания

Окончательный источник — подтверждённый серверный реестр. Таблица служит сверкой, а не основанием включать отключённое.

| Сценарий | Europe/Moscow | Особенности |
|---|---|---|
| Telegram Digest | 08, 11, 14, 17, 21 | Сохранять `digest_type` и slot; в текущем source используется host cron |
| Личная почта | 08, 13, 16, 20 | Раздельные morning/interval/editorial |
| Рабочая почта | 8 слотов от 08:30 до 19:00 | Промежуточные минуты брать из фактического config |
| Опрос обоих ящиков | Каждые 5 минут | Раздельные streams/groups/inbox refs |
| Signals | Каждые 5 минут | Только включённые rulesets |
| Signals retention | Раз в час по исходному internal scheduler | Переносится в явное Hermes cron-задание после сверки |
| Last30Days | 07:00 | Только фактически включённый preset; второй доступен по запросу |
| LightRAG | Каждые 30 минут | Явный список разрешённых корней; не вся файловая система |
| Wiki daily | 05:45 | `dry_run`, `report` |
| Wiki weekly | Вс 06:15 | `apply`: report, archive, refresh_topics, refresh_overview |

`benka jobs-prepare` переводит проверенный JSON-реестр в определения jobs/workers; `benka cron-prepare` создаёт
нативные **paused** задания с `no_agent=true`, `deliver=local`, `failure_deliver=local`.
`local` — поддерживаемый Hermes способ не отправлять вывод в канал. Только общий sender публикует результаты.

## Секреты по назначению

| Назначение | Хранение / перенос |
|---|---|
| SSH | Существующий Ansible vault, не Git проекта |
| Telegram Bot API | Отдельный тестовый токен для репетиции; production только при переключении |
| Telethon | API ID/hash и `.session`, приватный том с корректным владельцем |
| Два ящика | API/OAuth отдельно по контурам, исходные inbox refs |
| LLM | Private model-providers JSON или штатный Hermes auth; ключи не в prompts/cron |
| Redis | ACL/URL; отдельные scoped credentials и права на streams |
| Wiki / LightRAG | Раздельные токены и URL каждого контура |
| OmniRoute | SQLite с OAuth и ключами, согласованная холодная копия |
| Dashboard | Username, password hash, stable auth secret; Caddy server cert/key и client CA |
| Syncthing | Новая идентичность target; pairing с Mac после сверки данных |

Для `READY_NOT_ACTIVE` ещё нужно завершить сопоставление server files ↔ Git, собрать точные размеры всех томов,
cron всех уровней, маршруты и ACL, закрепить live digests LightRAG/OmniRoute/Syncthing и проверить их восстановление.
