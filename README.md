# gavnest-agent

AI agent backend for [GavNest](https://gavnest.com) — a neutral home-buying journey companion that guides first-time buyers through every phase of the process.

Built with **FastAPI + LangGraph + OpenAI GPT-4o**. Deployed on **Google Cloud Run**.

---

## What it does

`gavnest-agent` powers **Gavvy** — the GavNest AI assistant. Gavvy answers home-buying questions using live public data, not training-data recall. Every response is structured, cited, and phase-aware.

### The 4 agents

| Phase | Agent | Data sources |
|---|---|---|
| 1 — Am I Ready? | `readiness_agent` | FRED PMMS (live 30yr rate) |
| 2 — Get Pre-Approved | `mortgage_agent` | FRED + FHFA NMDB (rate by credit tier) |
| 3 — Search & Evaluate | `property_agent` | FEMA NFHL (flood zone) + HOA PDF RAG |
| 4-5 — Offer & Contract | `contract_agent` | State closing cost calculator + PDF extract |

### Key design decisions

- **Structured LLM output** — every agent uses `llm.with_structured_output(Schema)` via OpenAI function calling. The LLM cannot return free text — it must populate a typed Pydantic model. Eliminates hallucination at the schema level.
- **Input validation** — each agent validates `user_profile` via a Pydantic input schema before calling the LLM. Bad data raises a clean error early.
- **Live data, not training recall** — FRED rates are fetched on every request. HMDA tier data and closing costs are pre-aggregated in Firestore and read at runtime. FEMA flood zones are queried via the official NFHL ArcGIS API.
- **SSE streaming** — responses stream token-by-token to the frontend via Server-Sent Events. Three stream modes: `thinking` events (progress), `token` events (LLM output), `sources` events (citations).
- **Durable checkpointing** — LangGraph state persists to Neon Serverless Postgres via `AsyncPostgresSaver`. Conversations resume after restarts. HITL (human-in-the-loop) interrupt/resume is supported.
- **Business event logging** — every agent start, completion, and error is written to Firestore for product analytics.

---

## Architecture

```
Next.js (gavnest-web)
    │
    │  POST /api/gavvy  Authorization: Bearer <Firebase ID token>
    ▼
FastAPI (Cloud Run)
    ├── CORS middleware
    ├── Firebase auth dependency  →  verify_id_token() → uid
    ├── slowapi rate limiter      →  20 req/min per uid
    └── Pydantic request validation

LangGraph StateGraph
    │
    ├── START → phase_router (conditional edge)
    │               │
    │    ┌──────────┼──────────────┬──────────────┐
    │    ▼          ▼              ▼               ▼
    │ readiness  mortgage       property       contract
    │  agent      agent          agent          agent
    │    │          │              │               │
    │    │     FRED+HMDA      FEMA+HOA       ClosingCosts
    │    │    (Firestore)    (ArcGIS+RAG)    (Firestore)
    │    └──────────┴──────────────┴───────────────┘
    │                      │
    │              AsyncPostgresSaver
    │              (Neon Serverless Postgres)
    │
    └── SSE stream → Next.js
         ├── {"type": "thinking", "message": "..."}
         ├── {"type": "token",    "content": "..."}
         ├── {"type": "sources",  "items":   [...]}
         └── {"type": "done"}

Firestore (Firebase)
    ├── hmda_rates/{year}/tiers/{tier}        ← rate spreads by credit tier
    ├── closing_costs/{year}/states/{state}   ← closing cost rates by state
    ├── events/{uid}/logs/{id}                ← business analytics events
    └── hoa_docs/{uid}/{property_id}/chunks/  ← HOA PDF embeddings
```

---

## Project structure

```
gavnest-agent/
├── app/
│   ├── main.py                  # FastAPI app, CORS, lifespan, routers
│   ├── config.py                # Pydantic Settings (all env vars)
│   ├── auth/
│   │   └── firebase.py          # Firebase ID token verification dependency
│   ├── middleware/
│   │   └── rate_limit.py        # slowapi rate limiter keyed by uid
│   ├── api/
│   │   ├── gavvy.py             # POST /api/gavvy → SSE StreamingResponse
│   │   ├── journey.py           # GET/POST /api/journey → Firestore phase state
│   │   └── health.py            # GET /health → 200
│   ├── graph/
│   │   ├── state.py             # GavvyState TypedDict (add_messages reducer)
│   │   ├── graph.py             # StateGraph builder + stream_gavvy()
│   │   ├── router.py            # phase_router conditional edge function
│   │   ├── llm.py               # ChatOpenAI factory (@lru_cache singleton)
│   │   ├── schemas.py           # Pydantic input/output schemas for all agents
│   │   └── nodes/
│   │       ├── readiness.py     # Phase 1 — affordability + FRED
│   │       ├── mortgage.py      # Phase 2 — rate education + HMDA
│   │       ├── property.py      # Phase 3 — flood + HOA analysis
│   │       └── contract.py      # Phases 4-5 — contract decode + closing costs
│   ├── tools/
│   │   ├── fred_rates.py        # FRED API → live 30yr mortgage rate
│   │   ├── hmda_rates.py        # Firestore → rate ranges by credit tier
│   │   ├── fema_flood.py        # FEMA NFHL → flood zone by address
│   │   ├── hoa_analyzer.py      # PDF → chunk → embed → RAG → findings
│   │   └── closing_costs.py     # Firestore → state closing cost calculator
│   ├── services/
│   │   └── event_logger.py      # Firestore business event logger
│   └── corpus/
│       ├── seed_hmda.py         # One-time: seed HMDA tier data to Firestore
│       └── seed_closing_costs.py # One-time: seed closing cost data to Firestore
├── static/
│   └── test.html                # Dev-only SSE test page (served at /test/)
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Local development

### Prerequisites

- Python 3.11+
- Docker (for local Postgres — or use Neon free tier)
- GCP project with Firebase + Firestore enabled
- OpenAI API key
- FRED API key (free at https://fredaccount.stlouisfed.org)

### Setup

```bash
git clone https://github.com/amitvermaknw/gavnest-agent
cd gavnest-agent

python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env — minimum required fields below
```

### Minimum `.env` for local dev

```dotenv
DEV_MODE=true                    # skips Firebase auth — uid = "dev-user"
GCP_PROJECT_ID=your-project-id
FIREBASE_PROJECT_ID=your-project-id
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
FRED_API_KEY=your_32_char_key    # https://fredaccount.stlouisfed.org
DATABASE_URL=postgresql+asyncpg://user:pass@ep-xxx.neon.tech/gavnest?sslmode=require
FRONTEND_URL=http://localhost:3000
```

### Seed Firestore (one time)

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

python -m app.corpus.seed_hmda
python -m app.corpus.seed_closing_costs
```

### Run

```bash
uvicorn app.main:app --reload --port 8000
```

### Test in browser

Open `http://localhost:8000/test/test.html` — interactive SSE test page for all 4 agents. No Postman needed.

### Test via curl

```bash
# Phase 1 — Readiness
curl -X POST http://localhost:8000/api/gavvy \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Am I ready to buy a home?",
    "phase_id": "readiness",
    "user_profile": {"budget": 400000, "creditRange": "Good", "downPct": 10, "location": "Phoenix AZ"}
  }' -N --no-buffer

# Phase 2 — Mortgage
curl -X POST http://localhost:8000/api/gavvy \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What rate can I expect with Good credit?",
    "phase_id": "mortgage",
    "user_profile": {"budget": 400000, "creditRange": "Good", "downPct": 10, "location": "Phoenix AZ"}
  }' -N --no-buffer

# Phase 3 — Property
curl -X POST http://localhost:8000/api/gavvy \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Is this property in a flood zone?",
    "phase_id": "property",
    "user_profile": {"budget": 400000, "property_address": "2 N Central Ave, Phoenix AZ 85004", "location": "Phoenix AZ"}
  }' -N --no-buffer

# Phase 4-5 — Contract
curl -X POST http://localhost:8000/api/gavvy \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What are my closing costs?",
    "phase_id": "contract",
    "user_profile": {"budget": 400000, "offerPrice": 385000, "location": "Phoenix AZ"}
  }' -N --no-buffer
```

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DEV_MODE` | No | `false` | Skip Firebase auth locally |
| `GCP_PROJECT_ID` | Yes | — | GCP project ID |
| `FIREBASE_PROJECT_ID` | Yes | — | Firebase project ID (usually same as GCP) |
| `OPENAI_API_KEY` | Yes | — | OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-4o` | OpenAI model ID |
| `FRED_API_KEY` | Yes | — | FRED API key (free) |
| `DATABASE_URL` | Yes | — | Neon Postgres connection string |
| `FRONTEND_URL` | Yes | `http://localhost:3000` | Allowed CORS origin(s), comma-separated |
| `LANGCHAIN_TRACING_V2` | No | `false` | Enable LangSmith tracing |
| `LANGCHAIN_API_KEY` | No | — | LangSmith API key |
| `LANGCHAIN_PROJECT` | No | `gavnest` | LangSmith project name |
| `RATE_LIMIT_PER_MINUTE` | No | `20` | Requests per minute per user |

---

## Firestore schema

```
hmda_rates/
  {year}/                          # e.g. "2023"
    tiers/
      Excellent/                   # avg_rate, rate_low, rate_high, score_range
      Good/
      Fair/
      Poor/

closing_costs/
  {year}/                          # e.g. "2025"
    states/
      AZ/                          # transfer_tax_pct, title_insurance_pct, recording_fees, total_pct
      CA/
      NY/  ...all 50 states + DC

events/
  {uid}/
    logs/
      {auto_id}/                   # event_type, phase_id, data, created_at

hoa_docs/
  {uid}/
    {property_id}/                 # MD5 of property address
      {chunk_index}/               # text, embedding, chunk_index
```

---

## Data sources

| Source | Used for | Auth | Cost |
|---|---|---|---|
| FRED API (MORTGAGE30US) | Live 30yr mortgage rate | Free API key | Free |
| FHFA National Mortgage Database | Rate spreads by credit tier | None (stored in Firestore) | Free |
| FEMA NFHL ArcGIS REST API | Flood zone by address | None | Free |
| US Census Geocoder | Address → lat/lng for FEMA | None | Free |
| CFPB HMDA Data Browser | Loan volume by type (seed only) | None | Free |
| LodeStar / state tax schedules | Closing costs by state | None (stored in Firestore) | Free |
| OpenAI Embeddings (text-embedding-3-small) | HOA document RAG | OpenAI API key | Paid |

---

## API reference

### `POST /api/gavvy`

Main Gavvy chat endpoint. Returns SSE stream.

**Headers**
```
Authorization: Bearer <Firebase ID token>   # not required in DEV_MODE
Content-Type: application/json
```

**Request body**
```json
{
  "message":      "Am I ready to buy a home?",
  "phase_id":     "readiness",
  "user_profile": {
    "budget":           400000,
    "creditRange":      "Good",
    "downPct":          10,
    "location":         "Phoenix AZ",
    "property_address": "2 N Central Ave, Phoenix AZ 85004",
    "offerPrice":       385000,
    "timeline":         "6 months",
    "grossMonthlyIncome": 8000
  }
}
```

**Phase IDs:** `readiness` | `mortgage` | `property` | `contract` | `closing`

**SSE event types**
```
data: {"type": "thinking", "message": "Fetching FRED rates..."}
data: {"type": "token",    "content": "Based on your profile..."}
data: {"type": "sources",  "items":   [{"source": "FRED", "url": "..."}]}
data: {"type": "done"}
data: {"type": "error",    "message": "..."}
```

### `GET /health`

Health check. Returns `{"status": "ok"}`. Used by Cloud Run.

### `GET /api/journey`

Returns user journey + phase state from Firestore.

### `POST /api/journey/phase`

Updates a phase status (`active` | `done`).

---

## Deployment (Cloud Run)

```bash
# Build and push
gcloud builds submit --tag gcr.io/YOUR_PROJECT/gavnest-agent

# Deploy
gcloud run deploy gavnest-agent \
  --image gcr.io/YOUR_PROJECT/gavnest-agent \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "GCP_PROJECT_ID=...,OPENAI_API_KEY=...,FRED_API_KEY=...,DATABASE_URL=...,FRONTEND_URL=https://gavnest.com"
```

Cloud Run service account needs:
- `roles/datastore.user` — Firestore read/write
- `roles/firebase.admin` — Firebase token verification

---

## Annual data updates

| Data | When | How |
|---|---|---|
| HMDA rate tiers | When FHFA publishes new NMDB data (~Q2 each year) | Edit `seed_hmda.py` TIERS → re-run `python -m app.corpus.seed_hmda` |
| Closing costs by state | When LodeStar publishes annual report (~Q1) | Edit `closing_costs.py` `_FALLBACK_STATES` → re-run `python -m app.corpus.seed_closing_costs` |

No code deploy needed for data updates — Firestore is the source of truth at runtime.

---

## LangSmith tracing

Set these in `.env` to enable full agent tracing (node inputs/outputs, LLM calls, token counts, latency per step):

```dotenv
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_key
LANGCHAIN_PROJECT=gavnest
```

Get a free key at https://smith.langchain.com

---

## Author

Amit Verma — [GitHub](https://github.com/amitvermaknw) · [LinkedIn](https://linkedin.com/in/amitvermaknw)

Built as part of the GavNest product suite. AI-powered home buying education — no transaction incentive, no licensing risk, all 50 states.