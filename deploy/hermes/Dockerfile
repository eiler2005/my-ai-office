FROM ghcr.io/astral-sh/uv:0.8.22@sha256:9874eb7afe5ca16c363fe80b294fe700e460df29a55532bbfea234a0f12eddb1 AS uv
FROM node:26-bookworm-slim@sha256:9e6f9357d371591e32ab6f2d8a26d63bdd0d17c29eee3f4f3e7e454d9634bf73 AS dashboard_build
WORKDIR /hermes
COPY vendor/hermes-agent ./
RUN npm ci --workspace web --include-workspace-root --ignore-scripts --no-audit --no-fund \
    && npm run build --workspace web
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS runtime_base
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates curl tzdata libstdc++6 libatomic1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 benka && useradd --uid 1000 --gid 1000 --create-home benka \
    && mkdir -p /state/hermes/uploads /vault && chown -R 1000:1000 /state /vault
WORKDIR /opt/benka
COPY --from=dashboard_build /usr/local/bin/node /usr/local/bin/node
COPY --from=dashboard_build /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY vendor/hermes-agent ./vendor/hermes-agent
COPY --from=dashboard_build /hermes/hermes_cli/web_dist ./vendor/hermes-agent/hermes_cli/web_dist
RUN uv sync --frozen --extra hermes --no-dev
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
ENTRYPOINT ["python", "-m", "benka_integrations.service"]
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
