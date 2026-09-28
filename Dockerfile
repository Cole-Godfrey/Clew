FROM python:3.12-slim

WORKDIR /app
ENV UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never
RUN python -m pip install --no-cache-dir uv==0.12.12

COPY pyproject.toml uv.lock LICENSE ./
COPY clew ./clew
RUN uv sync --locked --no-dev --no-editable

RUN groupadd --system app && useradd --system --gid app app \
    && mkdir /data && chown app:app /data
ENV PATH="/app/.venv/bin:${PATH}" CLEW_DATABASE_PATH=/data/clew.sqlite3
USER app

EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn clew.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
