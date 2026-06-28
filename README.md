# BN Square Agent

BN Square Agent is a local automation console for collecting Binance Square posts, generating account-specific rewritten posts, attaching a matching Binance chart screenshot, and publishing through a remote MCP publisher.

## Features

- Local FastAPI web console with static frontend in `dist/`
- Multi-account cookie management stored in SQLite
- Binance Square creator monitoring through real profile APIs
- Material queue with TTL expiration
- Automatic material consumption loop
- Per-account writing workflow with LLM review and rewrite
- Style RAG with DashScope embeddings and Chroma
- Automatic Binance futures chart screenshot via Playwright
- Remote MCP publishing via `publish_binance_square`

## Safety Notes

Do not commit runtime data or secrets. The repository ignores:

- `.env`
- `data/`
- `chroma_db/`
- local agent/tooling folders

Cookies, API keys, generated posts, and captured samples are stored locally only.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Copy `.env.example` to `.env` if you prefer file-based configuration, or configure everything in the web console.

```powershell
copy .env.example .env
```

## Run

```powershell
python -B run.py serve --host 127.0.0.1 --port 8787
```

Open:

```text
http://127.0.0.1:8787/
```

## Web Configuration

The web console can persist these settings into SQLite:

- LLM API key/base URL/model
- DashScope API key and embedding model
- MCP endpoint and publish behavior
- automatic material polling and consumption settings

Use the separate **Test LLM** and **Test Embedding** buttons to validate each connection.

## Workflow

1. Add Binance account cookies.
2. Add Binance Square creator profile URLs as material sources.
3. The monitor collects new posts every configured interval.
4. Fresh material expires after the configured TTL if unused.
5. The background consumer picks new material and generates per-account final posts.
6. The publisher captures a matching Binance chart and calls the remote MCP tool.

## Project Layout

```text
ai/           LLM-backed agents
core/         settings and config
dist/         local frontend
knowledge/    Chroma / embedding RAG
models/       Pydantic schemas
publishing/   MCP publisher, chart screenshots, account checks
sources/      material source monitors
storage/      SQLite persistence
workflows/    LangGraph workflows and operator
```

