# Realtime Chat — Backend

A real-time chat API built with Django Channels, designed specifically to
demonstrate four things: WebSocket server & connections, real-time event
broadcasting, REST APIs & data flow, and horizontal scaling to multiple
clients across multiple server processes.

Frontend companion repo: [real-time-chat-client](https://github.com/Zorlam/real-time-chat-client)

## Why this project

Most "real-time chat" tutorials stop at a single server broadcasting to
whoever's connected to it. This project goes further: authentication
happens over the WebSocket handshake itself (not just REST), events
reach you even for conversations you don't currently have open, and the
"scales horizontally" claim is actually proven — not just architected —
by running two independent server processes and confirming a message
sent through one is delivered to a client connected only to the other,
coordinated entirely through Redis.

## Architecture

**Django + Django Channels + Daphne (ASGI)**, not `manage.py runserver` —
Django's default dev server is plain WSGI and can't handle a WebSocket
upgrade request at all. Every route in this project (HTTP and WebSocket)
goes through Daphne.

**Two separate WebSocket consumers, for two different jobs:**

- `ChatConsumer` — one connection per open room. Handles messages,
  typing indicators, presence, read receipts, and deletion. Only reaches
  clients who currently have that specific room open.
- `NotificationConsumer` — one always-on connection per logged-in user,
  independent of whatever room (if any) is open. This is what makes a
  brand-new DM, or a message in a conversation you haven't opened,
  actually show up live instead of requiring a page refresh.

**Redis as the channel layer** — the mechanism that lets one server
process broadcast an event to a client connected to a *different* server
process. This is what "scaling to multiple clients" actually means here:
not just handling many connections on one machine, but coordinating
across multiple stateless replicas. `channels_redis` handles this; a
small custom module (`chat/presence.py`) also talks to Redis directly
for connection-counting, so online/offline status stays correct even
when the same user has multiple tabs or devices open.

**JWT authentication over WebSockets** — Channels has no built-in
equivalent to a REST `Authorization` header for the initial handshake, so
a custom middleware (`chat/jwt_auth_middleware.py`) reads a token from
the connection URL's query string and validates it *before* the
connection is even accepted.

**REST for state, WebSocket for events** — REST endpoints handle
everything that already happened (message history, room lists, starting
a DM), while WebSocket events handle everything happening right now
(a message arriving, someone typing, a read receipt). The two are
integrated, not just parallel: a plain REST call (like starting a new
DM) can trigger a live WebSocket push to the other person's
notification channel.

## Features

- **Auth** — JWT (access + refresh, with rotation), registration, login,
  silent token refresh
- **Rooms** — public/group rooms, message history with cursor pagination
- **Direct messages** — 1:1 conversations with a deterministic room
  identity per pair of users
- **Message requests** — a DM from someone new starts as a pending
  request; the recipient can accept or decline, and replying
  auto-accepts
- **Presence** — real online/offline status, tracked via a Redis
  connection counter so multiple tabs/devices don't cause flickering
- **Typing indicators** — ephemeral, never persisted to the database
- **Read receipts** — "seen" state per conversation, broadcast live
- **Message deletion** — soft delete, sender-only, broadcasts to the
  other participant(s) live
- **User search & profiles** — exact-match username lookup (supports an
  `@` prefix), public profile view
- **Rate limiting** — global throttle plus stricter limits on
  login/register specifically (the actual brute-force protection point)
- **WebSocket resilience** — automatic reconnection with exponential
  backoff, and a ping/pong heartbeat to detect dead connections that
  otherwise look open

## Tech stack

| Layer | Choice |
|---|---|
| Framework | Django + Django REST Framework |
| Real-time | Django Channels + Daphne |
| Channel layer | Redis (`channels_redis`) |
| Database | PostgreSQL (SQLite for local dev) |
| Auth | `djangorestframework-simplejwt` |
| Tests | Django's test runner + DRF `APITestCase` + Channels `WebsocketCommunicator` |
| Deployment | Docker Compose (2 replicas + Redis + Postgres + Nginx) |

## API reference

**Auth**
```
POST   /api/auth/register/
POST   /api/auth/login/
POST   /api/auth/refresh/
GET    /api/auth/me/
```

**Rooms & messages**
```
GET    /api/rooms/
GET    /api/rooms/<id>/messages/
POST   /api/rooms/<id>/read/
```

**Direct messages**
```
GET    /api/dms/
GET    /api/dms/requests/
POST   /api/dms/start/
POST   /api/dms/<id>/accept/
POST   /api/dms/<id>/decline/
```

**Users**
```
GET    /api/users/?search=<username>
GET    /api/users/<id>/profile/
```

**WebSocket**
```
ws/chat/<room_name>/?token=<jwt>       — per-room events
ws/notifications/?token=<jwt>          — always-on, cross-conversation events
```

Client → server events on `ws/chat/`: a plain `{"content": "..."}` to
send a message, plus `{"type": "typing", "is_typing": bool}`,
`{"type": "read"}`, `{"type": "delete_message", "message_id": id}`, and
`{"type": "ping"}`.

Server → client events: `message`, `user_joined`, `user_left`,
`presence`, `typing`, `read`, `message_deleted`, `pong`. The
notifications socket sends a single minimal `{"event": "update"}` —
deliberately generic, so the frontend just refetches its room/DM lists
rather than the server duplicating serialization logic there.

## Local setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows; use `source venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
copy .env.example .env         # `cp` on macOS/Linux
python manage.py migrate
python manage.py createsuperuser
```

You'll also need Redis running locally:
```bash
docker run -d --name redis -p 6379:6379 redis
```

Start the server with Daphne (not `runserver`):
```bash
daphne -p 8000 config.asgi:application
```

## Running with Docker Compose

This is the more interesting way to run it — two backend replicas behind
an Nginx load balancer, coordinating through a shared Redis instance and
Postgres database:

```bash
docker compose up --build
docker compose exec backend1 python manage.py migrate
docker compose exec backend1 python manage.py createsuperuser
```

The app is reachable at `http://localhost:8000`. See `DEPLOYMENT.md` for
details, including how to confirm both replicas are actually handling
traffic.

## Proving the scaling claim

It's easy to *say* an app scales horizontally; this project actually
demonstrates it. Run two independent Daphne processes sharing one Redis
instance:

```bash
daphne -p 8001 config.asgi:application
daphne -p 8002 config.asgi:application
```

Connect one client to port 8001 and another to port 8002, then send a
message from the first. It arrives on the second — even though the two
processes have no direct connection to each other at all. The only thing
coordinating them is Redis's pub/sub, acting as the Channels layer. The
same holds for the notification system: a REST call handled by one
process can push a live WebSocket event to a client connected to the
other.

## Testing

```bash
python manage.py test
```

37 tests across both apps — REST endpoint behavior and authorization,
and WebSocket consumer behavior (auth-gated connections, message
broadcast, private-room authorization, deletion, heartbeat). The suite
runs against an isolated in-memory database and doesn't require Redis to
be running (WebSocket tests use Channels' in-memory channel layer, and
the Redis-backed presence functions are mocked), so it's safe to run
anywhere, including CI, without any external services set up.

## Project structure

```
config/          # settings, ASGI routing, root URLs
accounts/        # custom User model, registration/login, profiles
chat/            # rooms, messages, DMs, consumers, presence tracking
Dockerfile
docker-compose.yml
nginx.conf
DEPLOYMENT.md    # detailed deployment + scaling verification steps
```