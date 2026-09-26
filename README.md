# 🤖 Local AI News Monitor & Automated Newsletter (n8n + Ollama)

> 🇫🇷 **Looking for the French version?** See the French repository: [auto-veille-n8n-ia-local](https://github.com/ChrisAutodidacte/auto-veille-n8n-ia-local)

> An end-to-end, **100% self-hosted AI news monitoring platform** that automatically gathers intelligence, analyzes and categorizes articles using a **local LLM (Ollama)**, and distributes **morning executive digests and personalized newsletters** — with zero paid external APIs and zero data leaving your server.

<p align="center">
  <img alt="n8n"        src="https://img.shields.io/badge/n8n-workflows-EA4B71?logo=n8n&logoColor=white">
  <img alt="Ollama"     src="https://img.shields.io/badge/Ollama-Local%20AI-000000?logo=ollama&logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white">
  <img alt="Flask"      src="https://img.shields.io/badge/Flask-Admin%20UI-000000?logo=flask&logoColor=white">
  <img alt="Docker"     src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white">
  <img alt="License"    src="https://img.shields.io/badge/License-MIT-green">
</p>

---

## 🎬 Demonstration

> 📺 **Video Overview & Walkthrough**: _(Link coming soon on [Chris Figures It Out](https://www.youtube.com/@ChrisFiguresItOut))_
>
> Prefer a written walkthrough? Check out our **[Step-by-Step Installation Tutorial](docs/step-by-step-tutorial.md)**.

---

## 💡 Why This Project?

Manual industry monitoring and curation is an exhausting chore: checking countless newsletters, browsing niche websites, filtering signal from noise, and summarizing takeaways.

This project **automates the entire intelligence pipeline**:
1. **Automated Collection**: Periodically ingests information from incoming newsletter emails, SearXNG search queries, and direct web scraping.
2. **Local AI Analysis**: A local model running on your machine (via **Ollama**) reads every queued article, generates concise and detailed summaries, classifies it by topic, and tags relevant keywords.
3. **Smart Distribution**: Admins receive an executive daily briefing every morning, while subscribers receive curated newsletters filtered to their specific topics of interest.

Everything runs **completely self-hosted on your own hardware** without API fees, usage limits, or cloud surveillance — true data sovereignty.

---

## 🏗️ Architecture

```
                          ┌─────────────────────────────────────────┐
                          │              n8n (workflows)             │
                          │                                          │
   📧 Newsletters  ─────► │  Ingestion  ─►  Article Queue            │
   🔎 Web Search   ─────► │  (email /       (table: articles_veille) │
   🌐 Web Scraping ─────► │   search /            │                  │
                          │   scraping)           ▼                  │
                          │              🧠 Local Ollama LLM         │
                          │              summary · topic · keywords  │
                          │                       │                  │
                          │         ┌─────────────┴───────────────┐  │
                          │         ▼                             ▼  │
                          │  📊 Morning Digest        📰 Subscriber   │
                          │     (daily summary)          Newsletters │
                          └─────────────────────────────────────────┘
                                          │
                                          ▼
                          🐘 PostgreSQL  ◄──►  🛠️ Flask Admin
                          (articles, sources,   (dashboard, CRUD
                           subscribers, topics)  sources & topics)
```

For deeper architectural details and data models, see **[docs/architecture.md](docs/architecture.md)**.

---

## 🧰 Technology Stack

| Component | Role |
|---|---|
| **[n8n](https://n8n.io)** | Workflow orchestration (collection, queue management, AI calls, email dispatch) |
| **[Ollama](https://ollama.com)** | Local AI engine for reading, summarizing and tagging (`qwen2.5:1.5b` by default) |
| **[SearXNG](https://docs.searxng.org)** | Privacy-respecting meta search engine for API-key-free web discovery |
| **PostgreSQL 16** | Relational datastore for articles, sources, subscribers, and send logs |
| **Flask** | Lightweight administrative web interface (Port 8090) |
| **Docker Compose** | One-command orchestration for the entire stack |

---

## 🧠 Choosing Your Local AI Model

Because the entire stack runs in Docker, **it behaves identically on Windows, Linux, or macOS**. The only variable is your hardware capacity, which dictates the size and speed of your chosen Ollama model:

| Machine Specs | Recommended Model Size | Analysis Quality | Speed |
|---|---|---|---|
| Modest PC / 8 GB RAM (CPU only) | ~1.5–2 B (e.g. `qwen2.5:1.5b`, `gemma3:1b`) | Fair & fast | Light footprint |
| Standard Desktop / 16 GB RAM | ~3–4 B (e.g. `qwen2.5:3b`, `gemma3:4b`) | Good | Balanced |
| Workstation / Server with GPU | 7 B+ (e.g. `qwen2.5:7b`, `gemma3:12b`, `llama3.1:8b`) | Excellent | Very fast |

Switching models takes one line: `docker exec monitor_ollama ollama pull <model-name>`, then update the model parameter in the n8n analysis workflow. The database, webhooks, and administrative UI remain strictly unchanged.

> 💡 **NVIDIA GPU Acceleration:** Uncomment the GPU block in `docker-compose.yml` to give Ollama direct CUDA access.

---

## 🚀 Quick Start

> **Prerequisites**: Docker & Docker Compose installed and running.

```bash
# 1. Clone the repository
git clone https://github.com/ChrisAutodidacte/local-ai-news-monitor-n8n.git
cd local-ai-news-monitor-n8n

# 2. Configure your environment
cp .env.example .env
#   → Edit .env to set your passwords and secret keys

# 3. Launch the full stack
docker compose up -d

# 4. Pull your local AI model
docker exec monitor_ollama ollama pull qwen2.5:1.5b
```

Once running:
- **n8n Web UI** → http://localhost:5678 (Import workflows from the [`workflows/`](workflows/) directory)
- **Admin Dashboard** → http://localhost:8090

Full setup guide & credential configuration: **[docs/installation.md](docs/installation.md)**.

---

## 🧠 Methodology: Supervised Multi-Model Development

This project was not built in a single shotgun generative prompt. It was engineered under human supervision using a **collaborative two-model architecture**, mirroring an agile team with pair programming and peer review:

**1. The "Architect" Role (Advanced reasoning model, e.g. Claude Opus)**
- Explores requirements and designs system architecture.
- Drafts actionable specification sheets (`docs/specs/`) designed for step-by-step execution.
- Maintains the master progress tracker.

**2. The "Developer" Role (Fast implementation model, e.g. Claude Sonnet)**
- Implements each unit step by step, strictly following the architectural specification.
- Summarizes technical diffs upon completion of each phase.

**The Supervision Loop**

```
   Architect (Opus)              Developer (Sonnet)
   ────────────────              ──────────────────
   Designs spec         ───────► Implements step
   + roadmap tracker                     │
          ▲                              ▼
          │                       Sends recap of
   Reviews, validates,  ◄───────  completed step
   adjusts if needed
          │
          └──────────► Next step… (rinse and repeat)
```

This deliberate multi-model pairing provides diverse perspectives at each phase, catching blind spots early. The design specifications and phase plans are versioned inside [`docs/`](docs/).

---

## 🗺️ Roadmap

- [x] **Phase 1** — Newsletter ingestion + Ollama local analysis + morning executive report
- [x] **Admin Dashboard** — Web UI for source management, subscribers, and topics
- [x] **Subscriber Automation** — Natural language email commands for self-service subscription & preferences
- [ ] **Phase 2** — Extended SearXNG web discovery & live content scraping
- [ ] **Smart Content Extraction** — JSON-LD / Readability / Trafilatura noise filters

---

## ⚠️ Security Notice

This repository provides a battle-tested template. Before production deployment:
- Always change all default passwords in `.env`.
- Never commit your `.env` file (protected by `.gitignore`).
- Your email/SMTP and OAuth credentials are created directly inside your local n8n instance and are never stored in this repository.

---

## 📄 License

Distributed under the **MIT License**. See [LICENSE](LICENSE) for details. Free for personal and commercial use.

---

## 👨‍💻 About the Author — Chris Figures It Out

I’m **Chris**, a self-taught creator and software craftsman who likes to figure things out.

I explore AI, automation, software engineering, and sovereign digital tools — not by pretending to have all the answers, but by actually testing things, breaking things, and building practical solutions to real-world business challenges.

> *No hype. No guru talk. Just one simple principle:*  
> **"If there’s a problem, let’s figure it out."**

---

### 💼 Contact & Custom Work
* 📺 English Channel: **[@ChrisFiguresItOut](https://www.youtube.com/@ChrisFiguresItOut)**
* 📺 French Channel: **[@ChrisAutodidacte](https://www.youtube.com/@ChrisAutodidacte)**
* 🌐 Business & Consulting: **[chrisconseil.fr](https://chrisconseil.fr)** (Custom AI automation & software workflows)
