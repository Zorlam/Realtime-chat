FROM python:3.12-slim

WORKDIR /app

# System deps for psycopg2 (Postgres client) and general build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt psycopg2-binary

COPY . .

EXPOSE 8000

# Daphne, not manage.py runserver — same reason as always: runserver is
# plain WSGI and can't handle the WebSocket upgrade requests this app
# depends on.
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
