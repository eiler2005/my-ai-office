# Переключение и откат

> Фактическое переключение выполнено 2026-09-06 после отдельной команды Дениса. Свежий snapshot
> хранится в приватном production state VPS Hermes, без копии на Mac; все Docker-сервисы source VPS
> остановлены и сохранены. См. [cutover record](cutover-record-2026-09-06.md). Дальнейшие разделы —
> процедура отката и повторного переноса, а не команда автоматически перезапускать OpenClaw.

**Выполнять только после отдельной команды Дениса.** Двухнедельное ожидание не открывает окно автоматически.
До переключения закрыть [приёмку кандидата](acceptance.md) и [журнал расхождений](drift-log.md).

## До остановки

Повторно проверить inventory обоих VPS, наличие работающей резервной копии, доступ Mac и достаточность диска.
На исходном VPS мало свободного места: не создавать там дополнительный многогигабайтный архив.
Потоковый экспорт направляется на защищённый диск Mac. Измерить скорость передачи и восстановления заранее.
Бюджет окна — четыре часа; начать откат не позднее третьего, если приёмка не проходит.

Зафиксировать окончательные Git SHA, upstream pins, image IDs, deployment manifest и секреты по назначению.
Rehearsal state отделить от чистого production destination; удалить его из путей финального импорта.
Повторить изменившиеся проверки. При функциональном пробеле OpenClaw продолжает работу до его устранения.

## Свежий холодный снимок

1. Отключить постановку новых заданий OpenClaw, дождаться завершения активных; экспортировать pending и uncertain deliveries.
2. Остановить только относящиеся к Беньке cron, polling, bridge workers и процессы записи. Приостановить Syncthing на Mac и старом VPS.
3. Записать Bot API update watermark, Telethon cursors, оба почтовых watermark, Redis PEL и подтверждённые message IDs.
4. Остановить Redis/LightRAG/OmniRoute перед копированием их файлов либо использовать проверенный согласованный механизм snapshot конкретной БД.
5. Скопировать по SSH на Mac все компоненты и образы; сверить manifest файлов и SHA. Соседние проекты не останавливать.

Подготовленный `benka snapshot` работает с **уже согласованным локальным layout**, а не сам останавливает сервер.
Структура корня: `openclaw/`, `workspace/`, `vault/`, `integrations/`, `redis/`, `lightrag/`, `omniroute/`, `config/`, `secrets/`.
Для томов использовать реальные mount sources из закрытого inventory. Копирование работающей БД обычным `cp` не допускается.
Symlinks и специальные файлы требуют явной подготовки; мигратор их отвергает.
Образы Docker и host-level конфигурацию хранить отдельными проверенными архивами рядом со snapshot, вне Git.

Cold receipt JSON содержит `writers_stopped: true`, `syncthing_paused: true`, список всех девяти `components`.
Отсутствующие компоненты тоже должны быть явно учтены оператором; `absent_components` в manifest проверить до импорта.
Receipt фиксирует выполненные действия, а не заменяет остановку writers.

```bash
umask 077
.venv/bin/benka snapshot /private/final-layout /private/final-export --cold-receipt /private/cold-receipt.json
.venv/bin/benka restore /private/final-export/snapshot.tar /private/final-export/manifest.json /private/restores
.venv/bin/benka restore /private/final-export/snapshot.tar /private/final-export/manifest.json /private/restores --apply
```

Без `--apply` выполняется только проверка. Импорт идёт через staging и atomic rename в каталог по SHA snapshot.
Повторный запуск проверяет все ранее импортированные файлы; изменённый импорт не считается успешным.
Прерывание и неполный архив должны оставлять старый runtime нетронутым.
После проверки перенести staging в соответствующие volumes/bind mounts и выставить UID/GID/права для каждого сервиса.

## Перенос пользовательских данных Hermes

Исходный OpenClaw хранит config и workspace раздельно. В отдельном curated workspace подготовить проверенные
SOUL, IDENTITY, AGENTS, USER и MEMORY. MEMORY ограничена 2200 символами, USER — 1375; дневники не помещать в эту память.
Пересмотреть инструменты, инструкции OpenClaw, пути и доверенные границы; исходные prompt-инструкции не копируются слепо.

```bash
.venv/bin/benka claw-layout /private/restored/openclaw /private/curated-workspace /private/claw-layout
HERMES_HOME=/private/new-hermes-home .venv/bin/hermes claw migrate --source /private/claw-layout --preset user-data --dry-run
```

Изучить вывод pinned importer, затем выполнить ту же команду без `--dry-run` с проверенным workspace target.
Hermes 0.21.0 создаёт стандартный `SOUL.md` при первом запуске CLI, включая dry-run. Конфликт с ним
может остановить весь импорт при exit code 0. Проверять фактические файлы и отчёт, а не только код процесса.
Только в новом изолированном destination, после проверки списка конфликтов, повторить dry-run с `--overwrite`,
затем применить с этим флагом и сохранить штатный pre-migration backup. Не использовать `--overwrite`
для непроверенного каталога с существующими пользовательскими данными. Сверить SOUL и `memories/{USER,MEMORY}.md`.
Проверенные навыки переносить отдельно, установить `plugins/benka` и `skills/benka-*`, применить domain profiles и paused cron.
Штатный импорт не превращает OpenClaw bridges/plugins/cron/Telegram bindings в Hermes-интеграции автоматически.

```bash
.venv/bin/benka archive-index /private/domain-transcripts /private/domain-state/archive.sqlite
```

Сверить импортированные источники и отчёт `skipped`. Полные разговоры доступны через поиск с источником и строкой;
в Hermes начинаются новые сессии. Каждый контур получает свой архив и компактную память.

## Включение

Настроить и проверить секреты/OAuth, модели и каждый резерв, embedding endpoint, wiki, Redis и разрешения профилей.
Для каждого production manifest оператор создаёт отдельный read-only activation receipt:
`command=ACTIVATE_HERMES_BY_DENIS`, точный `manifest_sha256`, SHA **финального** snapshot, `old_writers_stopped=true`.
Значения заполняются после реальной команды и проверки остановки; файл не хранится в Git и недоступен tools агента.

Включить единственный production polling Gateway, проверить Telegram inbound → ответ в нужной теме и follow-up.
Затем включить проверенные cron jobs/workers, наблюдать накопившуюся очередь и дедупликацию.
Перед возобновлением Syncthing сравнить vault с Mac; подключить новое device identity без неожиданных удалений.
Проверять все функции минимум 48 часов; еженедельную wiki-процедуру дополнительно прогнать на копии.

## Откат

Триггеры: нет Telegram ingress, нарушены темы/ACL, потеря данных, повторные публикации, отказ wiki/RAG, нестабильный runtime.

До новых записей: остановить Hermes Gateway/workers/cron/Syncthing; вернуть исходные данные и известные образы,
сверить единственного polling owner, возобновить OpenClaw.

После новых записей: сначала сохранить холодное состояние Hermes. Не заменять актуальные данные старым архивом.

```bash
.venv/bin/benka rollback-delta /private/baseline-vault /private/hermes-vault /private/old-vault > /private/rollback-report.json
```

Команда составляет трёхсторонний отчёт: безопасные новые/изменённые файлы, уже совпавшие, конфликты и удаления для сверки.
Она ничего не перезаписывает. Оператор переносит согласованные wiki/raw артефакты, архивирует новые диалоги Hermes,
сверяет подтверждённые deliveries, cursor advances и Redis pending в обоих runtime.
Новый RDB нельзя механически подменить старым: согласовать streams/PEL/dedupe семантически, включая неопределённые отправки.
Повторный запуск старых обработчиков разрешён только после этой сверки.

Старый стек и проверенный архив хранить минимум 14 дней **после приёмки Hermes**. Удаление — отдельная операция.
