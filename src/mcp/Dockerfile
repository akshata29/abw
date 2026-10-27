FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

USER appuser
EXPOSE 8080

CMD ["uvicorn", "abw_mcp.app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]

