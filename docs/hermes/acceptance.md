# Протокол проверок и готовности

Дата: 2026-09-06. **Статус `ACTIVE_ON_HERMES`; 48-часовое наблюдение продолжается.**
Фактическое переключение, свежий snapshot и остановка source Docker-сервисов зафиксированы в
[cutover record](cutover-record-2026-09-06.md). Публикация кода сама по себе не является активацией;
этот cutover выполнен только после отдельной команды владельца.
По указанию Дениса дальнейшие сборки и тесты выполняются на VPS; GitHub Actions не используется.
Производственные токены/бот/почта/Syncthing в репетиционных тестах не используются.

## Корректирующее развёртывание Telegram и profile manifests

После production cutover выполнено корректирующее развёртывание на VPS Hermes. Изолированный candidate-прогон
подтвердил сборку runtime и test images, **209** регрессионных проверок, native Hermes contracts, synthetic
`claw migrate` и Redis recovery. Полный `finalize` дополнительно был выполнен на отдельной локальной копии
production-state на VPS с `network=none` до изменения живого состояния.

В production финализатор назначил home channel личному DM единственного trusted owner, отключил
`onboarding.profile_build`, выпустил четыре profile manifests и четыре activation receipts. Gateway был
пересоздан на проверенном образе и вернулся в состояние `healthy`; загрузка personal manifest внутри запущенного
контейнера подтверждена. Compose также пересоздал сервис wiki как зависимость Gateway; его persistent volume
не изменялся, а остальные Benka workers продолжили работу без перезапуска.

Проверка не отправляла искусственное сообщение в реальный Telegram-чат и не повторяла delivery. Внешний
Telegram smoke остаётся частью наблюдения: владелец проверяет обычное сообщение в личном DM Беньки после
развёртывания.

## Восстановление Telegram Digest в 17:00 МСК

Нативный cron своевременно поставил выпуск в Redis, но production worker не нашёл `hermes send` в своём
`PATH`. Бинарник находился рядом с Python worker в virtualenv; ошибка возникала до подтверждения Telegram
message identifier и была правильно сохранена как `uncertain`, без автоматического повтора.

Исправление выбирает CLI из virtualenv, а затем использует `PATH` только как резерв. Новый staged candidate
на VPS прошёл те же **209** регрессионных проверок, native contracts и Redis recovery. В production был
пересоздан исключительно `worker-telegram` с Compose `--no-deps`; Gateway, wiki и соседние сервисы не
перезапускались.

Перед восстановлением read-only проверка истории целевой темы не нашла сообщения Беньки за 16:55–17:10 МСК.
После этого один контролируемый run сформировал выпуск для номинального окна 14:00–17:00 МСК, завершился
нормально и получил подтверждённые receipts. Повторная независимая проверка истории нашла обе части выпуска.
Первоначальные `uncertain` receipt и запись reconciliation сохранены в закрытом операционном журнале и не
должны воспроизводиться.

## Проверено на VPS Hermes

Серверный прогон выполнен в контейнерах с read-only root, без production secrets, с ограничением 2 CPU / 2 GiB RAM.
Регрессии и native contracts работают с `network=none`; Redis проверялся в отдельной `internal` Docker-сети без опубликованных портов.
Test dataset — только синтетические fixtures. GitHub Actions отсутствует.

| Набор | Результат |
|---|---|
| Hermes safety/migration/archive/cron/profiles/maintenance + native model fixtures | 45 passed |
| AgentMail | 19 passed |
| Telegram Digest | 21 passed |
| Signals / Last30Days | 98 passed |
| Wiki-import | 26 passed |
| Итого | **209 passed** |
| Native Hermes plugin / cron / AIAgent contract | 7 tools зарегистрированы; paused cron idempotent; API-параметры совместимы |
| Compose configuration | `config --quiet` проходит |
| История и working tree на секреты | Перед merge commit: 1226 объектов, 34 reviewed совпадения, 0 неразобранных; self-test сканера проходит |
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
| Сборка закреплённого Docker image, включая dashboard и Last30Days | PASS | Linux runtime и отдельный test target собраны |
| Регрессии в контейнере на VPS | PASS, 209 тестов | Все пять suites проходят |
| Standby с отключённой сетью | PASS, CLI и работающий контейнер | standby/sandbox/automatic_cutover=false; healthy до и после restart, network none |
| Native plugin/cron/model contracts на VPS | PASS | 7 tools, paused cron, native model fixtures |
| Реальный Redis и рестарт контейнера | PASS | AOF сохраняет slot, delivery receipt и pending; pending уходит на сверку, повторного send нет |
| TLS/mTLS, authentication, WebSocket dashboard | PASS, 9 checks | Без client certificate отказ; missing session/wrong password отказ; login, Secure/HttpOnly cookies, HTML/config/sessions API; WS upgrade и запрет replay |
| Native OpenClaw importer | PASS, synthetic data | dry-run, import, повтор, неизменность source, исключение private config и pre-import backup |
| Соседние проекты VPS Hermes | PASS | У всех 9 исходных контейнеров сохранены image ID, status и health |

Повторный проверенный Git tree: `e3350692a5fcb801b57414a4a2121dd88dc8f1c4` (staged candidate export 07).
Runtime image ID: `sha256:ba86d71c6b9fc882ca8d664ed3170a5827a6a8002f95bfb0774e15accd3ce40b`.
Первый полный прогон: tree `f96facd124bc812143fe09152ec6e4ee70dea0ed` (код `c2ab557`).
Закрытые логи: `/opt/benka-hermes/reports/<TREE>/`; итоговый exit code — 0.
Нативный Hermes обнаружил SQLite 3.46.1 и выбрал DELETE journal; WAL не включался.
Первый прогон выявил и помог исправить CRLF при экспорте Git, путь к dashboard build output и отсутствие
reference-скрипта в тестовом образе. Повторный прогон прошёл полностью. До указания о VPS локально ранее проходили 206 тестов.

Затем проверены изменения Compose панели и operator scripts непосредственно на VPS: отдельная ingress сеть Caddy,
bounded trusted proxy в Hermes, Secure cookies, повторный запуск dashboard и native importer rehearsal.
Они не требуют изменения runtime image. HTTPS работает на домене Reddit Compass с отдельным портом 8451;
source Caddy/DNS/SNI маршруты не менялись. Подробности и закрытые access files описаны в [инструкции панели](panel.md).
Полноценный чат с реальными моделями ещё не проверен. TLS certificate refresh пока выполняется оператором.

На source 14 остальных ранее зарегистрированных контейнеров не изменились; отдельный сторонний кандидат OpenClaw
из D003 исчез за время работы. Производственный Gateway сохранён. Перед cutover повторно сверить этот параллельный rollout.

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

Для внешних проверок ещё нужны место хранения конфигурации отдельного тестового Telegram-бота,
проверенная резервная копия и окончательные закрытые привязки контуров. Секреты в чат или Git не помещать.

## После отдельной команды переключения

Повторить inventory/drift review, перенести свежую холодную копию за весь период ожидания, проверить единственного polling owner.
Закрыть всю функциональную матрицу плана. Наблюдать минимум 48 часов с реальными ежедневными запусками.
Еженедельное обслуживание проверить на копии; подтвердить восстановление. До этого миграция не считается завершённой.

## Формат записи каждого прогона

Записывать дату, Git SHA + dirty flag, image ID, pinned Hermes SHA, dataset class, команду, counts/result и оставшиеся gaps.
Логи с содержимым писем/диалогов, receipt IDs, endpoint details и auth хранятся приватно; в Git — только обезличенный результат.
Health-check не закрывает функциональную приёмку.
