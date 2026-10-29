# Build context must be the repository root.
FROM python:3.12.8-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HTTP_HOST=0.0.0.0 \
    HTTP_PORT=3000
WORKDIR /workspace
COPY pyproject.toml uv.lock ./
COPY apps ./apps
COPY packages ./packages
RUN uv sync --frozen --no-dev --package commerce-api-gateway --no-editable \
    && useradd --system --uid 10001 appuser
USER appuser
EXPOSE 3000
CMD ["/opt/venv/bin/python", "-m", "commerce_gateway"]
