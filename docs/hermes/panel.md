# Изолированная панель рядом с Reddit Compass

По указанию Дениса от 2026-09-06 используется **тот же `RC_PUBLIC_HOST`, отдельный порт 8451**.
Адрес читается из действующей конфигурации `rc-caddy` и сохраняется только в закрытом `private/access.json`.
Reddit Compass продолжает обслуживать свой HTTPS-порт 8450. Его DNS, Caddyfile, контейнеры, volumes и
маршрутизатор 443 не изменяются; порты 80/443/8450 не занимаются новым проектом.

## Развёртывание

`deploy/hermes/compose.panel.yaml` создаёт только `benka-hermes-panel-dashboard-1` и
`benka-hermes-panel-caddy-1`. Dashboard подключён только к отдельной internal Docker-сети, без доступа наружу,
production secrets, Gateway, Redis, моделей, почты, Telethon и расписаний. Caddy дополнительно подключён
к собственной сети ingress: Docker не публикует порты контейнера, у которого есть только internal network.
Dashboard использует уже собранный web_dist.
Корневые файловые системы read-only, ресурсные лимиты заданы. Docker socket и host runtime не монтируются.

Caddy принимает TLS на 8451 и требует клиентский сертификат от отдельного CA Беньки.
После mTLS Hermes дополнительно требует отдельный пароль. Используется встроенный basic auth provider,
scrypt hash и постоянный signing secret; сервер хранит HttpOnly/Secure session cookies.
Basic Auth Reddit Compass не используется для входа в Hermes.

Оператор запускает `scripts/prepare-hermes-panel.py` через `sudo python3` на VPS после сборки образа.
Скрипт не запускает сервисы: создаёт `/opt/benka-hermes/panel-rehearsal/private` с правами 0700/0600,
копирует только соответствующие server certificate/key из Caddy volume и выпускает отдельный client certificate.
Контейнер агента не получает server key, client key или CA key. CA key не монтируется в Caddy.
Повторная первоначальная подготовка запрещена, чтобы не заменить существующие пароли и клиентские сертификаты.

После копирования `compose.panel.yaml` и `Caddyfile` в каталог панели:

```bash
sudo docker compose \
  --env-file /opt/benka-hermes/panel-rehearsal/private/panel.env \
  -p benka-hermes-panel \
  -f /opt/benka-hermes/panel-rehearsal/compose.panel.yaml create
sudo python3 /opt/benka-hermes/panel-rehearsal/prepare-hermes-panel.py --trust-panel-proxy
sudo docker compose \
  --env-file /opt/benka-hermes/panel-rehearsal/private/panel.env \
  -p benka-hermes-panel \
  -f /opt/benka-hermes/panel-rehearsal/compose.panel.yaml up -d --no-build
```

`--trust-panel-proxy` разрешает forwarded headers только из CIDR собственной internal сети панели.
Это необходимо для Secure cookies за TLS proxy. После пересоздания сети повторить настройку и перезапустить
только dashboard. Звёздочка или доверие всем адресам не используется.

Для Caddy оставлена только capability `NET_BIND_SERVICE`: её требует file capability закреплённого
официального бинарника даже при слушании порта 8443. Остальные capabilities удалены.

## Доступ и проверки

Закрытый `private/access.json` содержит URL и пароль Hermes. `private/client/benka-operator.p12` —
клиентский сертификат для импорта в Keychain; пароль контейнера — `private/client/p12-password`.
Эти файлы передаются через SSH в защищённый каталог Mac, исключённый из Git. В чат их содержимое не копируется.
Не импортировать client CA как доверенный серверный CA: сервер использует действующий публичный сертификат.

`scripts/verify-hermes-panel-vps.py` запускается только на VPS. Проверяет mTLS refusal, отказ API без сессии,
неверный пароль, успешный login, Secure/HttpOnly cookie, HTML, settings/sessions API,
WebSocket upgrade и невозможность повторно использовать ticket. В отчёте нет endpoint, cookie или credentials.
Эти проверки не подтверждают разговор с моделью или подключение производственного бота.

## Сертификаты и обслуживание

Владельцем ACME renewal остаётся существующий `rc-caddy`. Панель использует отдельную копию, поэтому
обновление сертификата источника само по себе не обновляет её TLS. Оператор выполняет:

```bash
sudo python3 /opt/benka-hermes/panel-rehearsal/prepare-hermes-panel.py --refresh-certificate
# Только если certificate_changed=true:
sudo docker restart benka-hermes-panel-caddy-1
```

Перед заменой проверяются hostname, срок не менее семи дней и соответствие ключа сертификату.
Новый hostname требует отдельной проверки. Скрипт никогда не пишет в volume Reddit Compass.
До производственной приёмки настроить регулярный запуск этой проверки и оповещение об ошибках;
истечение сертификата не является командой переключения OpenClaw → Hermes.
Client certificate действует 90 дней; его обновление и отзыв — отдельная операция оператора.

Остановить тестовую панель можно `docker compose ... stop` только для проекта `benka-hermes-panel`.
Не использовать глобальные `down`, prune, перезапуск Docker или Caddy соседнего проекта.
