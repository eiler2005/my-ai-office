FROM ghcr.io/astral-sh/uv:0.11.6@sha256:b1e699368d24c57cda93c338a57a8c5a119009ba809305cc8e86986d4a006754 AS uv
FROM node:26-bookworm-slim@sha256:9e6f9357d371591e32ab6f2d8a26d63bdd0d17c29eee3f4f3e7e454d9634bf73 AS node
FROM python:3.14-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS runtime_deps
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates curl tzdata libstdc++6 libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 benka && useradd --uid 1000 --gid 1000 --create-home benka \
    && mkdir -p /state/hermes/uploads /vault && chown -R 1000:1000 /state /vault
WORKDIR /opt/benka
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY vendor/hermes-agent ./vendor/hermes-agent
RUN uv sync --frozen --extra hermes --no-dev

FROM runtime_deps AS dashboard_build
WORKDIR /opt/benka/vendor/hermes-agent
RUN /opt/benka/.venv/bin/python -c 'from pathlib import Path; from pm import ensure, installed_package; ensure("pnpm", explicit=True); Path("/usr/local/bin/pnpm").symlink_to(installed_package("pnpm").binary)' \
    && node scripts/build/node-deps.mjs --source . --workspace web \
    && /opt/benka/.venv/bin/python -I scripts/generate_icons.py --source . --out /tmp/hermes-icons \
    && HERMES_WEB_BUILD_LIGHT=1 node scripts/build/web.mjs --source . --icons /tmp/hermes-icons --out /tmp/hermes-web

FROM runtime_deps AS runtime_base
COPY --from=dashboard_build /tmp/hermes-web ./vendor/hermes-agent/hermes_cli/web_dist
RUN .venv/bin/python vendor/hermes-agent/scripts/write_install_stamp.py \
    --output vendor/hermes-agent/install-stamp.json --source docker --distribution docker \
    --update-mechanism external --base-version 0.23.3 --distance 0 \
    --commit caafe5389ae585ef77387a962aee05b1bcf17029
COPY artifacts ./artifacts
COPY plugins ./plugins
COPY skills ./skills
COPY deploy/hermes ./deploy/hermes
ARG LAST30DAYS_COMMIT=01812ec1851e5c3d92a9049a41b7da4adbfbcb5d
RUN git clone https://github.com/mvanhorn/last30days-skill.git /opt/last30days-skill \
    && git -C /opt/last30days-skill checkout "$LAST30DAYS_COMMIT" \
    && .venv/bin/python -m benka_integrations.last30days_build /opt/last30days-skill \
    && .venv/bin/python artifacts/signals-bridge/last30days_patches/patch_last30days_skill.py /opt/last30days-skill
ENV PATH="/opt/benka/.venv/bin:$PATH" \
    HERMES_HOME=/state/hermes \
    BENKA_ARTIFACTS=/opt/benka/artifacts \
    BENKA_MANIFEST=/run/benka/manifest.json \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Europe/Moscow
USER 1000:1000
WORKDIR /state
ENTRYPOINT ["/opt/benka/.venv/bin/python", "-m", "benka_integrations.service"]
CMD ["standby"]

FROM runtime_base AS test
USER root
WORKDIR /opt/benka
RUN uv sync --frozen --extra test --extra hermes --no-dev
COPY tests ./tests
COPY scripts/test-hermes.py scripts/verify-hermes-contract.py scripts/verify-redis-vps.py scripts/lightrag-ingest.sh ./scripts/
USER 1000:1000
ENTRYPOINT ["python", "/opt/benka/scripts/test-hermes.py"]

FROM runtime_base AS runtime
