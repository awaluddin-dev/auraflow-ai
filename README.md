# AuraFlow AI

Distributed asynchronous data cleaning system using LangGraph agents and enterprise queue architecture.

Submits raw malformed data via REST API → cleans and validates using LLM agents in a feedback loop → persists structured results to PostgreSQL.

## Architecture

POST /jobs (NestJS/Fastify)
→ BullMQ job (Redis)
→ LangGraph Worker (Python)
→ Parser Agent: clean raw data using LLM
→ Validator Agent: verify output, loop back if invalid
→ HITL (Human-in-the-Loop) Check: pause for manual review if confidence is low (< 0.9)
→ HTTP callback with retry + idempotency
→ PostgreSQL (result persisted)

GET /jobs/:id → return status and cleaned data
GET /jobs/:id/progress → SSE (Server-Sent Events) live streaming progress

## Stack

| Layer         | Technology                                        |
| ------------- | ------------------------------------------------- |
| Gateway       | Bun · NestJS · Fastify                            |
| Queue         | BullMQ · Redis                                    |
| AI Worker     | Python · LangGraph                                |
| LLM Providers | Gemini · OpenAI · Claude · Groq · Custom endpoint |
| Database      | PostgreSQL · Prisma 7                             |
| Container     | Docker · Docker Compose                           |

## LLM Provider Fallback

Supports multiple providers with configurable fallback chain.
If the primary provider fails (rate limit, timeout, API error), automatically falls back to the next available provider.

Configure via environment:

```env
LLM_PROVIDER_ORDER=gemini,groq,openai,claude,custom
```

Custom OpenAI-compatible endpoints (Ollama, OpenRouter, vLLM) supported via:

```env
CUSTOM_LLM_BASE_URL=http://localhost:11434/v1
CUSTOM_LLM_MODEL=llama3.2
```

## Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/awaluddin-dev/auraflow-ai
cd auraflow-ai
cp .env.example .env
# Edit .env — set at least one LLM provider API key

# 2. Start all services
docker compose up --build

# 3. Run database migration (first time only)
docker compose exec gateway bunx prisma migrate deploy

# 4. Submit a job
curl -X POST http://localhost:3000/jobs \
  -H "Content-Type: application/json" \
  -d '{"rawData": "john doe, 50000, 2024-01-15"}'

# 5. Check result
curl http://localhost:3000/jobs/{jobId}
```

## API

### POST /jobs

Submit raw data for processing.

**Request:**

```json
{ "rawData": "string — any format, malformed data accepted" }
```

**Response (202):**

```json
{ "jobId": "cuid", "status": "queued", "message": "..." }
```

### GET /jobs/:id

Get job status and result.

**Response:**

```json
{
  "id": "cuid",
  "status": "queued | pending_review | completed | failed",
  "rawData": "original input",
  "cleanedData": "{\"name\": \"John Doe\", \"salary\": 50000, \"date\": \"2024-01-15\"}",
  "isValid": true,
  "attempts": 1,
  "validationReason": "OK",
  "createdAt": "ISO8601",
  "completedAt": "ISO8601"
}
```

### GET /jobs/:id/progress

Stream real-time job execution progress using SSE (Server-Sent Events).
The stream will automatically close when the job reaches a terminal state (`completed`, `failed`, or `pending_review`).

### GET /jobs/pending-review

List all jobs that require manual Human-in-the-Loop (HITL) review due to low confidence or business rule triggers.

### POST /jobs/:id/review

Submit a manual review decision for a job in `pending_review` state.

**Request:**
```json
{
  "decision": "approve | reject | edit",
  "editedData": "{...}", // required if decision is "edit"
  "note": "Optional review notes"
}
```

## Reliability

- **LLM fallback chain** — automatic failover across providers
- **Parse retry loop** — validator feeds reason back to parser, up to 3 attempts
- **Human-in-the-Loop (HITL)** — pauses execution for manual review if AI confidence is low or business rules are triggered
- **Callback retry** — exponential backoff (1s → 2s → 4s → 8s → 16s), max 5 attempts
- **Idempotency** — duplicate callbacks rejected with 409, not double-written
- **BullMQ retry** — if all callback attempts fail, BullMQ retries the full job

## Local Development (without Docker)

```bash
# Dependencies
cd gateway && bun install
cd .. && uv sync

# Infrastructure
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:16-alpine
docker run -d -p 6379:6379 redis:7-alpine

# Migrate
cd gateway && bunx prisma migrate dev

# Run
bun run dev          # terminal 1 — gateway
uv run python -m worker.main  # terminal 2 — worker
```

## Jalankan Dengan Docker

```bash
# Build dan start semua
docker compose up --build

# First time — migrate database
docker compose exec gateway bunx prisma migrate deploy

# Test
curl -X POST http://localhost:3000/jobs \
  -H "Content-Type: application/json" \
  -d '{"rawData": "BUDI SANTOSO | gaji: Rp 8.500.000 | tgl masuk: 15 Januari 2024"}'
```
