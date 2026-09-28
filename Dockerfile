FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home --uid 10001 orlweb
COPY pyproject.toml README.md ./
COPY orl_web ./orl_web
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir .
USER orlweb
EXPOSE 8080
CMD ["uvicorn", "orl_web.app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
