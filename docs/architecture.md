# Architecture & Data Flow

This document details how the system components interact and how data flows through the pipeline.

## Core Principle: Decoupling Collection from AI Analysis

The **collection workflows** never make direct AI calls. Their sole mission is to ingest raw incoming data (newsletters, search results, web pages) and insert it into the `articles_veille` table with the status `a_analyser`.

A dedicated **analysis workflow** then processes queued articles **one by one** (batch size of 1) using Ollama. This serialization guarantees stability: it prevents local GPU/RAM exhaustion, keeps ingestion resilient against model latency, and allows individual articles to be re-analyzed independently if needed.

## End-to-End Data Pipeline

```
Sources (sources_veille, active = true)
        │
        ▼
[Collection]  email (Gmail) · search (SearXNG) · web_scraping (HTTP)
        │   insertion with ON CONFLICT DO NOTHING (deduplication)
        ▼
articles_veille  (status = a_analyser)
        │
        ▼
[Ollama Analysis]  short/long summary · main topic · keywords · target audience
        │   status → analyse (or error)
        ▼
        ├──► [Daily Morning Report]   24h intelligence digest → admin email
        └──► [Subscriber Newsletters] topic selection per user → queue → dispatch
```

## Database Tables Overview

| Table | Purpose |
|---|---|
| `sources_veille` | Active monitoring sources + JSONB configuration |
| `articles_veille` | Collected articles enriched with Ollama AI metadata |
| `newsletter_themes` | Curated topics available for newsletter subscription |
| `newsletter_abonnes` | Subscribers, preferred topics, and dispatch frequency |
| `newsletter_envois` | Dispatch logs ensuring zero duplicate article sends |
| `newsletter_queue` | Outbox queue of compiled HTML newsletters |
| `newsletter_emails_commandes` | Inbound natural language email commands (subscribe, cancel...) |
| `newsletter_suggestions_themes` | Subscriber-suggested topics awaiting admin approval |

Complete SQL definitions: [`sql/init.sql`](../sql/init.sql).

## Source Configuration (`sources_veille.config`)

The `config` JSONB column adapts to each `type_source`:

| `type_source` | Expected Keys |
|---|---|
| `email` | `sender`, `gmail_label`, `priorites[]`, `ignore[]` |
| `search` | `search_query`, `max_results`, `priorites[]`, `ignore[]` |
| `web_scraping` | `url`, `motif_url`, `max`, `priorites[]`, `ignore[]` |

`priorites` and `ignore` keywords allow smart weighting without breaking collection workflows.

## Docker Containers

| Container | Image | Port | Internal DNS |
|---|---|---|---|
| `monitor_postgres` | postgres:16-alpine | 5432 | `postgres` |
| `monitor_n8n` | n8nio/n8n | 5678 | `n8n` |
| `monitor_ollama` | ollama/ollama | 11434 | `ollama` |
| `monitor_searxng` | searxng/searxng | 8080 | `searxng` |
| `monitor_searxng_redis` | redis:7-alpine | — | `searxng-redis` |
| `monitor_admin` | build `./admin` | 8090 | `monitor_admin` |

All services communicate through the shared `monitor_network` bridge network using container service names (e.g., n8n queries Ollama at `http://ollama:11434` and SearXNG at `http://searxng:8080`).
