# anotify-server

Lightweight WebSocket relay server for agent notifications.

## How It Works

```
                         ┌─────────────────────────────────┐
                         │        anotify-server            │
                         │                                  │
  HTTP POST /api/notify  │  ┌─────────┐    ┌────────────┐  │   WebSocket /ws
  ──────────────────────►│  │ FastAPI  │───►│  Broadcast │  │──────────────────►
                         │  │  REST    │    │  to all WS │  │   Desktop clients
  GET /api/health        │  │  API     │    │  clients   │  │
  ◄──────────────────────│  └─────────┘    └────────────┘  │
                         │                                  │
                         │  ┌─────────────────────────────┐ │
                         │  │  In-memory history (100 max) │ │
                         │  └─────────────────────────────┘ │
                         └─────────────────────────────────┘
```

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/notify` | Bearer token | Send a notification |
| GET | `/api/history` | Bearer token | Get last 50 notifications |
| GET | `/api/health` | None | Server status + client count |
| WS | `/ws` | Bearer token (header or `?token=`) | WebSocket for desktop clients |

> Auth note: a configured token is enforced in **every** mode, including
> `--public`. Public mode only drops the auth requirement when *no* token is
> set, so a public relay is locked down simply by setting a token.

## Running Locally

```bash
cd server/
pip install fastapi uvicorn websockets
python server.py --port 7799 --token YOUR_SECRET
```

### With Docker (example)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY server.py .
RUN pip install fastapi uvicorn websockets
EXPOSE 7799
CMD ["python", "server.py", "--port", "7799"]
```

```bash
docker build -t anotify-server .
docker run -p 7799:7799 -e ANOTIFY_TOKEN=secret anotify-server
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ANOTIFY_TOKEN` | Auth token (if not passed via `--token`) | (none — auth disabled) |

## Public Instance

A public relay runs at `your-server.example`. You can use it without self-hosting:

```bash
anotify config --server https://your-server.example --token YOUR_TOKEN
```

## Security Notes

- Token auth uses constant-time comparison (`hmac.compare_digest`)
- A configured token is enforced in all modes — set `ANOTIFY_TOKEN` (or
  `--token` / `--token-file`) to lock down a relay, even one started with
  `--public`. Without a token, the server accepts all connections (dev only).
- Desktop clients send the token via the `Authorization` header (kept out of
  URLs/proxy logs); a `?token=` query param is accepted as a fallback.
- Use a reverse proxy (nginx/caddy) for TLS termination in production
- The history buffer is in-memory only — restarts clear it
