FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Avval faqat bog'liqliklar — kod o'zgarganda qayta yuklanmasin
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY config ./config
RUN uv sync --frozen --no-dev

# root bo'lmagan foydalanuvchi; /data — Telegram session fayli uchun volume
RUN useradd --create-home app && mkdir /data && chown app:app /data
USER app
ENV PATH="/app/.venv/bin:$PATH"

CMD ["python", "-m", "elon.bot.main"]
