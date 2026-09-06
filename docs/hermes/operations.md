# Эксплуатация Hermes

## Текущий production status

С 2026-09-06 Бенька работает на VPS Hermes. Актуальная запись переключения и проверки находится в
[cutover-record-2026-09-06.md](cutover-record-2026-09-06.md). Старые разделы о candidate/rehearsal ниже
сохранены как процедура повторной репетиции; они не являются инструкцией для остановки работающего production.

Текущий статус и ограничения — в [протоколе](acceptance.md). Эти команды не являются разрешением переключить production.

## Установка

Внутри образа использовать Python 3.12, `uv sync --frozen --extra hermes` и Git submodules. Для тестов добавить `--extra test`.
На хост VPS Python-зависимости агента не устанавливаются: тестовый Docker target `test` включает необходимое окружение.

### Изолированный builder для VPS-проверок

Сценарий `scripts/run-hermes-vps-tests.sh` использует отдельный Docker Buildx builder `benka-migration`. Перед
первым прогоном на VPS создать и загрузить его один раз:

```bash
docker buildx inspect benka-migration >/dev/null 2>&1 || \
  docker buildx create --name benka-migration --driver docker-container --bootstrap
```

Builder используется только для candidate images. Production Compose не переключает его и не получает доступ к
Docker socket из контейнеров агента.

Hermes закреплён на `01ae7a5668ce0fa2efca524a4567cacdd0786c95`; Last30Days — на
`01812ec1851e5c3d92a9049a41b7da4adbfbcb5d` с прежними Reddit/GitHub адаптациями.
Обновление любого pin требует повторения native-contract и регрессий.

Dockerfile собирает Hermes dashboard отдельной Node-стадией и устанавливает Python API из submodule.
Runtime работает от UID/GID 1000, с read-only root, ограничением памяти/CPU/PID и без Docker socket.
Логи контейнеров ротируются. Для SQLite задан `journal_mode: delete`; включать WAL можно только после проверки
исправленной версии SQLite из upstream. Не переносить работающую SQLite как один файл без WAL/SHM.

Не применять `chown -R` ко всему production state: Redis хранит AOF от UID/GID 999, OmniRoute пишет SQLite
от root, а Caddy с `cap_drop: ALL` читает mTLS key через группу root. После запуска финализатора владельца
можно вернуть только для `state/runtime`, `private/activation`, `private/manifests` и `private/bridges` —
это UID/GID 1000. Владелец Redis, OmniRoute и `private/panel/tls` при этом не меняется.

Compose по умолчанию запускает только offline standby. В `rehearsal` находятся шаблоны Gateway, dashboard,
одного worker, wiki, Redis и Caddy. Это шаблон одного изолированного контура; перед полной репетицией необходимо
создать отдельные worker instances/volumes/secrets для обоих ящиков, Telegram, Signals, Last30Days, RAG и maintenance.
LightRAG, OmniRoute и Syncthing требуют отдельного проверенного deployment manifest с live image digests и томами.
Они не подменяются пустыми новыми сервисами при импорте.

```bash
docker compose -f deploy/hermes/compose.yaml config --quiet
docker compose -f deploy/hermes/compose.yaml build candidate
docker compose -f deploy/hermes/compose.yaml up -d candidate
docker compose -f deploy/hermes/compose.yaml ps
```

Каталоги `/state`, profile homes и vault должны принадлежать UID/GID 1000. Для готовых bind mounts выставить
права до запуска. Private manifest и секреты монтировать read-only вне доступных агенту путей.

## Manifest и режимы

`BENKA_MANIFEST` указывает на JSON `schema: 1`; обязательны `mode` и один `domain` из personal/work/family/sandbox.

| Режим | Условия |
|---|---|
| standby | Любые побочные действия отвергаются; no network у default candidate |
| rehearsal | `data_class=test`, `production_connections=false`, явно перечисленные `enabled_operations` |
| production | Отдельная команда владельца, receipt с SHA manifest, SHA свежего snapshot и stopped writers |

Operations: `gateway`, `dashboard`, `worker`, `poll`, `send`, `enqueue`, `wiki`, `wiki_read`, `wiki_write`, `index`, `archive_read`.
Разрешать только необходимые конкретному сервису операции. Значения по умолчанию пустые.
Receipt — операционная блокировка, не криптографическая авторизация владельца; создавать его может только оператор
после отдельной команды Дениса. Генератора автоматической активации и таймера в проекте нет.

## Профили и Telegram

### Личный канал Беньки и первый диалог

Финализатор production-конфигурации назначает домашним Telegram-каналом только личный DM единственного
доверенного пользователя из контура `personal`. Форум, рабочая группа и семейный маршрут не могут стать
домашним каналом по умолчанию: результаты cron и межплатформенные уведомления не должны попадать в общий чат.
Если в `personal` нет ровно одного пользователя, финализатор оставляет домашний канал незаданным и требует
осознанной настройки оператором.

Для импортированного Беньки `onboarding.profile_build` всегда установлен в `off`. Стандартный Hermes-опросник
первого контакта предназначен для чистой установки; здесь профиль, память и правила уже подготовлены. Не
выполнять `/sethome` в форумной теме: это изменит маршрут уведомлений для всего Gateway.

Каждый multiplex-профиль получает собственный manifest в закрытом `private/benka-manifests/`; Gateway монтирует
этот каталог read-only как `/run/benka/profiles/`. Поле `manifest_path` в profile config обязано указывать на
`/run/benka/profiles/<domain>.json`. Не подменять его общим Gateway manifest: доменные ограничения инструментов
и данных должны сохраняться при каждом вызове плагина.

Финализатор переводит profile manifests в `production` и создаёт отдельный activation receipt на каждый контур.
Для `personal` он создаёт отдельные read-only файлы Redis, wiki и LightRAG в `private/profile-secrets/personal/`.
Контуры `work`, `family` и `sandbox` остаются read/archive-only, пока оператор не подготовит их собственные
проверенные credential files и не расширит разрешённые операции отдельным изменением политики.

В закрытом `bindings.json` задать все четыре контура:

```json
{"domains": {
  "personal": {"users": [101], "admins": [], "routes": [{"chat_id": -1001, "thread_id": 1}]},
  "work": {"users": [101], "admins": [], "routes": [{"chat_id": -1001, "thread_id": 2}]},
  "family": {"users": [102], "admins": [], "routes": [{"chat_id": -1002}]},
  "sandbox": {"users": [101], "admins": [], "routes": [{"chat_id": -1003}]}
}}
```

Это синтетические идентификаторы для описания формата; реальные берутся из проверенного закрытого реестра.

```bash
.venv/bin/benka profiles-prepare deploy/hermes/private/bindings.json .migration/profile-staging --repo "$PWD"
```

Генератор создаёт private staging, SOUL-заготовки, два skills, plugin, раздельные `.env`, config и manifest каждого
профиля. Telegram **выключен во всех профилях**. Проверенные личность и инструкции нужно внести до репетиции.
После проверки компактных USER/MEMORY включить `memory.memory_enabled` и `memory.user_profile_enabled` только в соответствующих интерактивных профилях. В шаблоне они выключены; фоновые AIAgent всегда запускаются без этой памяти.
Один root Gateway владеет polling и маршрутизирует сообщения в domain profiles; unmatched route не получает инструментов.
Проверить native profile routing, доступ постороннего пользователя и отсутствие чужих файлов/памяти в собранном контексте.
Пустые списки admin IDs и отключённые опасные toolsets сохранять до отдельной проверки политик Hermes.
Не выдавать terminal/file/browser/cronjob/kanban toolsets пользовательским сессиям. `delegate_task` разрешён
только для одного изолированного Sol-subagent без терминала, файлов, браузера, памяти или повторной
делегации; он нужен для сложных многошаговых задач.

Разместить созданные `benka-manifests/*.json` в read-only `/run/benka/profiles/`, а credential files —
в `/run/benka/profile-secrets/<domain>/`. Config содержит пути; значения не разделяются через global env между multiplex profiles.
Для панели выбрать отдельный scoped `HERMES_HOME` и разрешённый профиль; не открывать общий административный профиль семье.

## Модели и интеграции

Интерактивная лестница использует отдельный ChatGPT Codex OAuth в закрытом Hermes auth store:

| Уровень | Модель и назначение |
|---|---|
| Вспомогательные операции | `gpt-5.6-luna`, minimal/low reasoning: заголовки, compression и background review |
| Обычный диалог | `gpt-5.6-terra`, medium reasoning |
| Сложная многошаговая задача | Один `delegate_task` на `gpt-5.6-sol`, high reasoning, затем Terra проверяет и объединяет результат |
| Отказ OpenAI маршрута | `qwen3.7-flash`, затем `deepseek-v4-flash` как аварийные fallback-провайдеры |

Переход в Sol вызывается только для исследования, проектирования или проверки с несколькими шагами. Простые
вопросы, статусы и короткие правки не создают subagent. Наличие Qwen в цепочке означает только отказоустойчивость,
а не выбор основной модели.

`BENKA_MODEL_PROVIDERS_FILE` — путь к приватному JSON-массиву вида `[{"model": "...", "provider": "...",
"base_url": "...", "api_key": "..."}]`. Максимум четыре маршрута. Штатный OAuth настраивается средствами Hermes;
существующий OmniRoute сохраняет свои маршруты и OAuth state. Не вставлять реальные ключи в примеры или shell history.

Модель каждой фоновой задачи запускается отдельным процессом с пустым временным Hermes home, без tools,
memory/context files и сохранения сессии. Есть лимиты turns/tokens/time, строгий JSON и fallback по маршрутам.
Существующие валидаторы и детерминированные результаты интеграций сохранены.

Worker получает прежние переменные сервиса с переназначенными путями: `EMAIL_CONFIG_PATH`/`CONFIG_PATH`,
state, sessions, vault mounts, URL wiki/RAG и Redis. Точные имена сверять с `load_config` конкретного сервиса.
Для native send этому worker нужен отдельный настроенный Hermes home и доверенный `delivery_targets` allowlist.
Не запускать старые entrypoint/cron bridge HTTP endpoints вместе с новым worker.

`benka_integrations.delivery` запускает `hermes send` из того же virtualenv, что и worker Python, и только
затем использует `PATH` как резерв. Перед обновлением send-capable worker проверять наличие
`/opt/benka/.venv/bin/hermes` внутри контейнера. Receipt `uncertain` не означает подтверждённую доставку:
сначала сверить целевую Telegram-тему, затем принять одно зафиксированное операторское решение о восстановлении.

## Расписания и очереди

Закрытый reviewed-source JSON для `jobs-prepare` содержит:

- `timezone: Europe/Moscow`, `server_verified: true` после живой сверки;
- `email.personal` и `email.work`: `enabled`, `stream`, `group`, `inbox_ref`, `poll_schedule`, `slots` с `time` и `digest_type`;
- `telegram`: `enabled`, `domain`, `slots`;
- `signals`: список `enabled`, `domain`, `ruleset_id`, `schedule`;
- `last30days`: список `enabled`, `domain`, `preset_id`, `schedule`;
- `maintenance`: список `enabled`, `domain`, `action` (wiki-daily/wiki-weekly/rag-scan), `schedule`.
- `signals_cleanup`: `enabled`, `schedule`; сохраняет очистку старых событий Signals (исходный интервал — один час).

```bash
.venv/bin/benka jobs-prepare deploy/hermes/private/reviewed-schedules.json > .migration/job-registry.json
BENKA_MANIFEST=/private/standby-manifest.json HERMES_HOME=/private/hermes-home .venv/bin/benka cron-prepare /private/hermes-home
```

Скопировать только jobs данного контура в его manifest; использовать отдельные Redis credentials/ACL.
Cron script читает `cron_connection_file` с `redis_url`, потому что Hermes очищает окружение script-only jobs.
Задания создаются paused, повторная подготовка обновляет их по стабильному имени, удалённые задания остаются paused.
Не запускайте CLI `cron-prepare` с HERMES_HOME, отличающимся от переданного home.

`benka worker` обрабатывает один выбранный `worker.pipeline` и stream/group из manifest.
Slot dedupe атомарен в Redis. Восстановленные pending и ошибки уходят в `benka:reconcile` с исходным payload.
Запись completed подтверждается до XACK, чтобы падение между ними не повторяло работу.

Неопределённые `sending/uncertain` receipts и `benka:reconcile` разбирать вручную: проверить Telegram, сохранённые артефакты,
курсоры и pending; записать решение в приватный операционный журнал. Слепой перезапуск нового run_id может создать дубль.
Проверять возраст/размер очередей, а не только живой процесс worker. Очередь сверки не имеет автоматической очистки.

## Wiki / LightRAG

Wiki и RAG требуют токенов. Файловые пути ограничены корнем контура; URL-ingest по умолчанию запрещён.
`rag_source_root` и `rag_index_roots` задаются явно. `legacy_path_map` переводит старые абсолютные пути очереди
в относительные пути нового корня; неизвестные пути и `..` отвергаются.
Upload receipt означает принятие документа; успешный поиск и завершение индексации проверяются отдельно.
Переносить embedding model identity и размерность 3072 без изменения графа на новую несовместимую модель.

## Панель

Caddy на 8451 требует server cert/key и доверенную client CA в private/tls. TLS/mTLS дополняются аутентификацией Hermes:
`HERMES_DASHBOARD_BASIC_AUTH_USERNAME`, `HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH`, `HERMES_DASHBOARD_BASIC_AUTH_SECRET`.
Конкретную схему проверить на pinned версии. Стабильный auth secret хранится вне Git.
Проверить обычный HTTP, WebSocket upgrade, сессии, повторный вход и отрицательные запросы без пароля/клиентского сертификата.
Домены/сертификаты/SNI согласуются с существующим владельцем инфраструктуры; 80/443 остаются за соседями.

## Ожидание и наблюдение

До отдельной команды на переключение: immutable candidate, production credentials отсутствуют/выключены,
cron paused, polling только у OpenClaw, тестовый vault не синхронизируется с Mac.
Любую ротацию секрета или изменение исходного поведения отражать в [журнале расхождений](drift-log.md).
После переключения нужны минимум 48 часов реальных запусков всех ежедневных сценариев, стабильные очереди и память.
