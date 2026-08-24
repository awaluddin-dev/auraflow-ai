# AuraFlow AI ⚡

> An autonomous, distributed AI data-cleansing pipeline powered by LangGraph, NestJS, Redis/BullMQ, and PostgreSQL with built-in Human-in-the-Loop (HITL) safety controls.

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Node Version](https://img.shields.io/badge/node-%3E%3D20.0.0-green.svg)](https://nodejs.org/)
[![Package Manager](https://img.shields.io/badge/managed%20by-uv-purple.svg)](https://github.com/astral-sh/uv)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

---

## 📌 Overview

**AuraFlow AI** solves the problem of unreliable, unstructured, and malformed data ingestion. By orchestrating multi-agent feedback loops via **LangGraph** and integrating deterministic business validation rules, AuraFlow AI standardizes entity formats, detects outliers, and flags low-confidence data for human review before persisting it to **PostgreSQL**.

### Key Highlights

- **Multi-Agent Feedback Loop**: Autonomous Parser and Validator agents verify and self-correct extraction errors.
- **Deterministic Business Rule Engine**: Validates domain-specific constraints (e.g., regional salary boundaries, name lengths, date ranges).
- **Human-in-the-Loop (HITL)**: Automatically routes entries with confidence $< 0.90$ or anomalous values to a human triage queue.
- **Distributed & Scalable**: Decoupled ingestion gateway (NestJS + Fastify) and job workers (Redis + BullMQ).
- **Multi-Model Provider Agnostic**: Native integration with Google Gemini, Anthropic Claude, OpenAI, and Groq LLaMA 3.
- **Real-Time Observability**: Live processing progress via Server-Sent Events (SSE) and idempotent webhook delivery.

---

## 🏗️ Architecture

```mermaid
flowchart LR
    A[Raw Input Data] --> B[NestJS / Fastify API]
    B --> C[(Redis + BullMQ)]
    C --> D[LangGraph Worker]

    subgraph D [Python LangGraph Pipeline]
        D1[Parser Agent] --> D2[Validator Agent]
        D2 --> D3{Valid & Conf >= 0.9?}
        D3 -- No / Retries < 3 --> D1
        D3 -- Yes --> D4[Deterministic Rules]
        D4 -- Flagged --> D5[HITL Queue]
    end

    D4 -- Clean --> E[(PostgreSQL)]
    D5 --> E
    E --> F[Webhook / SSE Callback]
```

---

## ⚙️ Data Cleansing & Validation Pipeline

| Validation Stage        | Mechanism           | Validation Criteria                                                             |
| :---------------------- | :------------------ | :------------------------------------------------------------------------------ |
| **Field Extraction**    | LLM Parser Agent    | Extracts structural entities from raw unstructured text/JSON.                   |
| **Self-Correction**     | LLM Validator Agent | Evaluates schema accuracy; triggers re-parsing loop on failure.                 |
| **Name Validation**     | Deterministic Check | Flags single-character tokens or abbreviations ($< 3$ chars).                   |
| **Compensation Bounds** | Deterministic Check | Flags values outside standard ranges ($\text{IDR } 500\text{k} - 500\text{M}$). |
| **Date Boundaries**     | Deterministic Check | Restricts transaction/record years between $2000$ and $2030$.                   |
| **Confidence Scoring**  | Confidence Gate     | Routes records with confidence score $< 0.90$ to HITL review.                   |

---

## 🚀 Quickstart

### Prerequisites

- [uv](https://github.com/astral-sh/uv) (Python package manager)
- [Node.js](https://nodejs.org/) (v20+) and `pnpm` / `npm`
- [Docker](https://www.docker.com/) & Docker Compose (for PostgreSQL and Redis)

### 1. Clone & Set Up Environment Variables

```bash
git clone [https://github.com/awaluddin-dev/auraflow-ai.git](https://github.com/awaluddin-dev/auraflow-ai.git)
cd auraflow-ai

# Copy environment templates
cp .env.example .env
```

Configure your `.env` file:

```env
PORT=3000
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/auraflow
REDIS_HOST=localhost
REDIS_PORT=6379

# LLM Keys (Configure at least one)
GEMINI_API_KEY=your_gemini_key
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
GROQ_API_KEY=your_groq_key
```

### 2. Start Infrastructure via Docker

```bash
docker compose up -d redis postgres
```

### 3. Install Dependencies & Run Workers

```bash
# Set up Python worker
uv sync
uv run python -m worker.main

# In another terminal, start API gateway
npm install
npm run start:dev
```

---

## 📡 API Usage

### Enqueue Data Cleansing Job

```http
POST /api/v1/cleanse
Content-Type: application/json

{
  "raw_payload": "John D. joined PT Maju on 15/08/2023 with monthly comp of 15jt IDR",
  "callback_url": "[https://your-service.com/webhook](https://your-service.com/webhook)"
}
```

### Response

```json
{
  "job_id": "job_984f1a20",
  "status": "QUEUED",
  "stream_url": "/api/v1/cleanse/job_984f1a20/stream"
}
```

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.
