# My AI Office — Бенька на Hermes

Код интеграций и комплект переноса личного помощника Беньки с OpenClaw на Hermes Agent.
Целевой репозиторий: [eiler2005/my-ai-office](https://github.com/eiler2005/my-ai-office), приватный.

**Текущий статус: `MIGRATION_IN_PROGRESS`. OpenClaw остаётся единственной производственной системой.**
Подготовлены пакет, адаптеры, миграторы, конфигурация кандидата и локальные проверки.
Серверная репетиция и функциональная приёмка ещё не завершены. Этот репозиторий не означает, что Hermes уже запущен в production.

После достижения `READY_NOT_ACTIVE` OpenClaw продолжает работать ещё примерно две недели.
Денис переключает систему отдельной командой; перед этим переносится свежее состояние.
Календарная дата и обычный `docker compose up` переключение не выполняют.

## Документация

| Документ | Содержание |
|---|---|
| [План миграции](docs/25-hermes-migration-plan.md) | Согласованные этапы A–F, ожидание, приёмка и ограничения |
| [Реестр переноса](docs/hermes/inventory.md) | Компоненты, функции, состояния, версии, сведения о VPS из reddit-compass |
| [Установка и эксплуатация](docs/hermes/operations.md) | Пакет, профили, секреты, расписания, контейнеры, диагностика |
| [Переключение и откат](docs/hermes/cutover-rollback.md) | Холодная копия, повторный импорт, свежие данные, возврат после новых записей |
| [Протокол проверок](docs/hermes/acceptance.md) | Что проверено, что ещё требуется до READY и production |
| [Журнал расхождений](docs/hermes/drift-log.md) | Изменения OpenClaw до переключения и их перенос в Hermes |
| [Исходная документация OpenClaw](README.openclaw.md) | Исторический контекст; прежние команды развёртывания не являются установкой Hermes |

## Состав

- `src/benka_integrations/`: Python API Hermes, Redis jobs, доставка с подтверждениями, wiki-инструменты, архив, миграторы и CLI.
- `plugins/benka/`: нативная регистрация семи инструментов Hermes.
- `skills/benka-*`: wiki-first, Ideas и правила запуска сценариев.
- `artifacts/{agentmail-email,telethon-digest,signals-bridge,wiki-import}`: сохранённые алгоритмы с заменёнными runtime-вызовами и доставкой.
- `deploy/hermes/`: закреплённая сборка, Compose и примеры выключенных конфигураций.
- `vendor/hermes-agent`: Git submodule, версия 0.21.0, commit `01ae7a5668ce0fa2efca524a4567cacdd0786c95`.
- `scripts/test-hermes.py`, `scripts/verify-hermes-contract.py`: воспроизводимые проверки на VPS; GitHub Actions не используется.

Telegram Gateway, CLI и веб-панель используют Hermes. Cron ставит задания в Redis, обработчики выполняют прежние сценарии.
Общий отправитель вызывает `hermes send --json`; неизвестный результат отправки попадает на сверку.
Обсидиановская wiki остаётся основным хранилищем знаний, LightRAG — поисковым слоем.
Старые диалоги и дневники индексируются в приватный SQLite FTS-архив, отдельно от компактной памяти Hermes.

## Подготовка на VPS

```bash
git clone --recurse-submodules https://github.com/eiler2005/my-ai-office.git
cd my-ai-office
docker buildx create --name benka-migration --driver docker-container --driver-opt memory=4g,cpu-period=100000,cpu-quota=200000
docker buildx build --builder benka-migration --load --target test -f deploy/hermes/Dockerfile -t benka-hermes:test .
docker run --rm --network none --read-only --tmpfs /tmp:size=256m --memory 2g --cpus 2 benka-hermes:test
docker run --rm --network none --read-only --tmpfs /tmp:size=256m --memory 2g --cpus 2 --entrypoint python benka-hermes:test /opt/benka/scripts/verify-hermes-contract.py
docker compose -f deploy/hermes/compose.yaml config --quiet
```

Hermes устанавливается внутри образа как editable-пакет из закреплённого submodule: upstream не поддерживает обычную wheel-установку.
Запуск тестов изолирует состояние и не использует производственные `.env`. Сборщик создаётся один раз; уже существующий
`benka-migration` повторно создавать не нужно. Полный серверный прогон с проверкой durable Redis — `scripts/run-hermes-vps-tests.sh`
для пакета, созданного `scripts/package-hermes-candidate.py` из явно staged Git-файлов.

```bash
docker buildx build --builder benka-migration --load --target runtime -f deploy/hermes/Dockerfile -t benka-hermes:candidate .
docker compose -f deploy/hermes/compose.yaml up -d --no-build candidate
```

Эти команды предназначены для изолированной серверной репетиции.
Сервис `candidate` работает с `network_mode: none`; Gateway, workers, Redis и панель входят в отдельный профиль `rehearsal`.
Настройка рабочих подключений описана в [эксплуатационной инструкции](docs/hermes/operations.md).

## Git и данные

История исходного проекта сохранена в отдельном checkout. Исходный remote и незакоммиченные изменения OpenClaw не меняются.
Публикация требует проверки истории и текущих файлов на секреты. Ветки резервных копий до очистки истории требуют отдельного разбора.
В Git не входят vault, архивы, `.env`, OAuth, Hermes auth/state, Telethon sessions, Redis, LightRAG и сертификаты.
Приватная видимость репозитория дополняет эти ограничения.
