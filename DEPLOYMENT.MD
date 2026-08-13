# Running the multi-server setup

This demonstrates the horizontal-scaling architecture the project was
designed around: two independent backend processes (`backend1`,
`backend2`), coordinated entirely through Redis's pub/sub as the Channels
"channel layer" — no direct connection between the two replicas at all.
An Nginx load balancer sits in front and distributes connections between
them.

## Run it

```bash
docker compose up --build
```

First time only, run migrations against the shared Postgres database:

```bash
docker compose exec backend1 python manage.py migrate
docker compose exec backend1 python manage.py createsuperuser
```

The app is now reachable at `http://localhost:8000` — through Nginx,
which is load-balancing between `backend1` and `backend2` under the hood.
Point your frontend's `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` at
`http://localhost:8000` / `ws://localhost:8000` to use it.

## Proving it's actually load-balanced

Nginx's `least_conn` strategy means you can't always predict which
replica a given connection lands on, but you can watch it happen:

```bash
docker compose logs -f backend1 backend2
```

Open the app in two different browser sessions (e.g. a normal window and
an incognito window, logged in as two different users) and send messages
back and forth. Watch the logs — you'll see WebSocket connections and
message handling split across both `backend1` and `backend2`, and
messages still deliver correctly across them, exactly like the earlier
manual test where a message sent through one process was received by a
client connected to the other.

## Why Postgres here, and SQLite everywhere else

SQLite is a single file — fine for one process, but not safe for
multiple backend replicas writing concurrently. This compose file uses
Postgres specifically because it's a real multi-writer scenario, matching
what an actual production deployment would need. Local single-process
development (`daphne` + `manage.py`) still works fine with SQLite as
before; nothing about that changed.
