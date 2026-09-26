# Installation & Setup Guide

This guide walks you through setting up the complete stack from scratch.

## 1. Prerequisites

- **Docker** and **Docker Compose** (v2)
- ~8 GB of available RAM (Ollama + full stack)
- A **Gmail** account (or custom SMTP/IMAP) for newsletter ingestion and email delivery

## 2. Configuration

```bash
git clone https://github.com/ChrisAutodidacte/local-ai-news-monitor-n8n.git
cd local-ai-news-monitor-n8n
cp .env.example .env
```

Edit `.env` and configure your secure credentials:

| Variable | Recommendation |
|---|---|
| `DB_PASSWORD` | Strong random password |
| `FLASK_SECRET_KEY` | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SEARXNG_SECRET` | `openssl rand -hex 32` |
| `TZ` | Your timezone (e.g. `UTC`, `America/New_York`, `Europe/Paris`) |

## 3. Starting the Stack

```bash
docker compose up -d
docker compose ps        # All containers should be "running" or "healthy"
```

Upon first startup, PostgreSQL automatically runs [`sql/init.sql`](../sql/init.sql) to provision all tables and default topics.

## 4. Download Your Local AI Model

```bash
docker exec monitor_ollama ollama pull qwen2.5:1.5b
```

> **Model flexibility:** Ollama supports a huge range of local models (Gemma 3, Llama 3, Mistral, Qwen 2.5). Depending on your available hardware and quality needs, pull your desired model (e.g., `qwen2.5:3b`, `gemma3:4b`) and select it inside the n8n analysis workflow. Refer to the model sizing matrix in the main [README](../README.md#-choosing-your-local-ai-model).

## 5. Import Workflows into n8n

1. Open **http://localhost:5678** and complete the initial local n8n setup.
2. For each file in [`workflows/`](../workflows/): click **⋮ → Import from File**.
3. Best practice: Import sub-workflows (`Sub-*`, `WF-*`) first, followed by root orchestrators (`Maitre de la Veille`, `Analyseur Veille Ollama`, `Rapport Veille du Matin`).

## 6. Configure n8n Credentials

For security reasons, credentials are not included in the repository:

- **Gmail** (OAuth2) — For reading incoming newsletter feeds and sending outbound emails. Attach this to the Gmail nodes.
- **Ollama** — Set base URL to `http://ollama:11434`. Connect to the Ollama node in the analysis workflow.

> Note: SearXNG requires zero API credentials; n8n queries it directly via internal container networking at `http://searxng:8080/search?format=json`.

## 7. Setup Monitoring Sources & Subscribers

Open the Flask Admin UI at **http://localhost:8090**:

- **Sources** → Add RSS/newsletter/scraping feeds and customize parsing keywords.
- **Topics** → Fine-tune your newsletter interest categories.
- **Subscribers** → Add subscribers or let users self-enroll via email.

## 8. Activate Schedules

Inside n8n, **turn on (activate)** the scheduled workflows (nightly ingestion, morning digest).

---

## Troubleshooting

| Symptom | Resolution |
|---|---|
| Admin UI reports DB connection failure | Run `docker compose ps`: ensure `postgres` container status is *healthy* |
| n8n cannot reach Ollama | Verify credential URL is `http://ollama:11434` (Docker DNS, not `localhost`) |
| SearXNG returns HTML instead of JSON | Ensure `json` is present under `search.formats` in `searxng/settings.yml` |
| Ollama generation is slow | Model is too heavy for CPU/RAM: switch to `qwen2.5:1.5b` or enable GPU acceleration |
