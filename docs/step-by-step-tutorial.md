# 📺 Step-by-Step Installation Tutorial

This comprehensive tutorial walks you through every single step to get the full stack up and running on your local machine or server.

> Looking for a concise cheat sheet? Check [installation.md](installation.md).

---

## Before You Begin

### Requirements
- **Docker Desktop** (Windows/macOS) or **Docker Engine + Compose v2** (Linux) installed and running.
- **~8 GB of RAM** available for smooth local LLM execution.
- **~10 GB of free disk space** for Docker images and the local AI weights.
- A **Gmail** account (or SMTP/IMAP credentials) dedicated to newsletter ingestion and email delivery.
- Basic command line familiarity.

### Verify Docker Installation
Open your terminal and run:

```bash
docker --version
docker compose version
docker ps
```

If all three commands execute without error, your Docker daemon is ready.

---

## Step 1 — Clone the Repository

```bash
git clone https://github.com/ChrisAutodidacte/local-ai-news-monitor-n8n.git
cd local-ai-news-monitor-n8n
```

Verify that `docker-compose.yml`, `README.md`, and the `admin/`, `workflows/`, `sql/` directories are present.

---

## Step 2 — Configure Environment Secrets (`.env`)

The repository contains zero hardcoded secrets. Copy the sample environment file:

```bash
cp .env.example .env
```

Open `.env` in your favorite editor and configure:

| Variable | Description | Recommended Generation |
|---|---|---|
| `DB_PASSWORD` | PostgreSQL password | Pick a strong password |
| `FLASK_SECRET_KEY` | Admin session encryption | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SEARXNG_SECRET` | Search engine secret | `openssl rand -hex 32` |
| `TZ` | Container timezone | e.g. `UTC`, `America/New_York`, `Europe/Paris` |

---

## Step 3 — Launch the Entire Docker Stack

Start all containers in detached mode:

```bash
docker compose up -d
```

Check container status:

```bash
docker compose ps
```

All 6 services (`monitor_postgres`, `monitor_n8n`, `monitor_ollama`, `monitor_searxng`, `monitor_searxng_redis`, `monitor_admin`) should report `running` or `healthy`.

---

## Step 4 — Pull Your Local AI Model (Ollama)

Download the default lightweight model directly into the Ollama container:

```bash
docker exec monitor_ollama ollama pull qwen2.5:1.5b
```

Once finished, verify that the model is loaded:

```bash
docker exec monitor_ollama ollama list
```

---

## Step 5 — Configure n8n & Import Workflows

1. Navigate to **http://localhost:5678** in your web browser.
2. Complete the initial local admin signup.
3. Import the workflows from the [`workflows/`](../workflows/) folder:
   - Click **Workflows** → **Add Workflow** → Menu **⋮** (top right) → **Import from File**.
   - Import the sub-workflows (`Sub-*`, `WF-*`) first, followed by the master workflows (`Maitre de la Veille`, `Analyseur Veille Ollama`, `Rapport Veille du Matin`).

---

## Step 6 — Connect n8n Credentials

1. **Ollama Credential:**
   - Under n8n **Credentials**, create an **Ollama API** credential.
   - Base URL: `http://ollama:11434`
2. **Gmail / Email Credential:**
   - Create a **Gmail OAuth2** or **SMTP/IMAP** credential and link it to the respective email trigger/send nodes.

---

## Step 7 — Access the Admin Dashboard

Open **http://localhost:8090**:
- **Dashboard:** Real-time metrics on queued articles, analyzed stories, and source status.
- **Sources:** Add search queries, RSS/newsletter senders, or web scraping endpoints.
- **Subscribers:** Manage newsletter recipients and customized topic preferences.
- **Topics:** Create, edit, and organize newsletter interest categories.

---

## Step 8 — Enable Automated Schedules

Inside n8n, activate the scheduled triggers:
- Ingestion workflows (collect news overnight).
- Analysis pipeline (summarize with Ollama).
- Morning digest and newsletter dispatch.

You now have a 100% private, sovereign, automated AI news intelligence system running entirely on your own infrastructure!
