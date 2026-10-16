# README brief — exec-assistant

**Purpose of this file:** an accurate fact sheet to hand to an AI (or a person) to write the project's public `README.md`.
Everything below reflects decisions actually taken and code actually written as of **2026-10-16**.
Detailed reasoning lives in `docs/DECISIONS.md`; function-level behaviour in `docs/FUNCTIONS.md`.

---

## 0. Rules for whoever writes the README

1. **Never present planned work as done.** Each component below is marked **✅ built**, **🚧 in progress**, or **🗓 planned**. Keep those labels (or an equivalent "Status" column / roadmap) in the README.
2. **Don't invent** badges (CI, coverage, PyPI), a license, benchmarks, screenshots, a demo URL, or user counts. None exist yet. License: **not decided** — leave a placeholder.
3. **Numbers must come from this file.** They were measured on the author's own mailbox.
4. **Privacy tone:** this is a local-first tool. Don't suggest hosting it or sending mail data anywhere other than Google (source) and Anthropic (the model, from v1 phase 3 on).
5. The project is the author's **portfolio and learning project**: the author writes the code; design decisions and their evidence are a feature of the repo (`docs/DECISIONS.md`) and worth linking prominently.

---

## 1. One-line description

A **local-first personal executive assistant for Gmail**: it indexes your mailbox into a local hybrid-search index (semantic + keyword), and (v1, in progress) runs an **agent built from scratch** — its own tool-use loop, tools, harness, guardrails and evals — that answers questions about your email with **citations**, searches the web, and **drafts or sends replies only after your approval**. Claude (via the Anthropic API) is used only as the agent's language model; everything around it is this project's code.

**Wording note for the README writer:** don't call it "a Claude agent" or imply it's built on an agent framework. The agent loop, tools, approval flow, guardrails and evals are hand-written; the model is a component the agent calls.

## 2. Who it's for and the philosophy

- **Audience:** developers, and the author's own use. Not a consumer product.
- **Local-first:** ingestion, the vector index (Qdrant), and embeddings run **on your machine**. Email content is never sent to a server the author runs. (From phase 3, the question plus a few relevant email snippets go to Anthropic's API to generate answers.)
- **Bring your own keys, $0 to the author:** each user creates **their own** Google Cloud OAuth client (`credentials.json`) and uses **their own** Anthropic API key. No servers, no Google app verification, no hosting costs.
- **Why BYO Google client:** Gmail read access is a Google *restricted* scope; a single public app would need Google verification plus a paid annual third-party security assessment (CASA). Per-user clients count as personal use. Trade-off: ~10–15 minutes of Google Cloud setup per user, so the audience is technical users.
- **Built to learn and to show the engineering:** harness, guardrails and evals are treated as the core of the project, not extras.

## 3. Current status (2026-10-16)

**Phase 1 complete, Phase 2 in progress** — Gmail ingestion and the hybrid index work end to end; hybrid search is being built.

Measured on the author's mailbox (last 30 days):
- **809 / 809** emails indexed, **1,658** chunks (avg 2.05 per email)
- **0** duplicate chunks; every email's chunks complete; no empty chunks
- Re-runs skip already-indexed emails without re-downloading or re-embedding them
- Full ingestion runs with **zero Gmail rate-limit errors** at ~96 emails/minute

**Phase 2 (in progress):** `hybrid_search` in `assistant/search.py` — dense + sparse prefetch with Qdrant's built-in RRF fusion, dynamic payload filters (sender, label, date range) via a `FilterBuilder` class, sender/name resolution.

**Not yet built:** agent and its tools, approvals, guardrails, evals, any UI.

## 4. v1 scope (target release: **2026-11-10**)

### What v1 does (user-facing jobs)
1. **"Find that email about X"** — hybrid search with citations
2. **"What did <person> say about <topic>?"** — search filtered by sender/participant
3. **"What needs my attention this week?"** — from recent email (Gmail only in v1)
4. **Draft replies** (saved to your Gmail Drafts, threaded correctly) **and send them only after explicit user approval**
5. **Web search** when the answer isn't in your mail

### v1 tools for the agent
`search_gmail`, `get_thread`, `search_web`, `create_draft`, `send_email` (all 🗓 planned)

### v1 is Gmail only
Calendar and Drive are deliberately deferred to after v1 to make room for the harness, guardrails and evals.

### Non-negotiable in v1 (the portfolio core)
- **Harness:** agent loop with stop conditions and a labelled turn ceiling; token budget and compaction; JSONL event log; checkpoints; **pause for approval → resume**
- **Guardrails:** permission gate (sending always requires approval), PII check on outgoing text, grounding check on answers
- **Evals:** ~20 hand-labelled questions with expected source emails, a citation grader (Jaccard similarity, pass > 0.7), plus guardrail test cases

### Interface
Terminal chat (`python -m assistant.main`, 🗓 planned) and a minimal trace viewer for the event log.

## 5. Architecture

```
Gmail API ──► ingestion (fetch → clean → Document) ──► index (chunk → hash → embed → Qdrant)        ✅ built
                                                              │
question ──► agent loop (Claude) ──► tools ──► search (dense + BM25, RRF, filters) ──► cited answer   🗓 planned
                       │                └─► web search · get_thread · draft/send (approval gate)      🗓 planned
                       └─► event log · checkpoints · guardrails · evals                               🗓 planned
```

### Modules

| Path | Role | Status |
|---|---|---|
| `assistant/config.py` | single loader for `.env`; typed values; fails loudly on missing/invalid settings; derives the collection name from the embedding model | ✅ |
| `assistant/auth.py` | Google OAuth (desktop flow, PKCE), service builder, `execute()` with **Gmail token-bucket rate limiter** + retry with exponential backoff | ✅ |
| `assistant/ingest/gmail_ingest.py` | list recent IDs → skip already-indexed → fetch → parse → upsert | ✅ |
| `assistant/ingest/gmail_parse.py` | pure functions: MIME walk, HTML→text, quote stripping, forward handling, `message_fields()` | ✅ |
| `assistant/ingest/chunking.py` | overlapping word-based chunks, content hashing | ✅ |
| `assistant/ingest/embeddings.py` | fastembed dense + sparse embeddings; `embed_documents` (ingestion) and `embed_query` (search-time query embedding) | ✅ |
| `assistant/ingest/index.py` | Qdrant collection, `upsert_document` (change detection, delete-by-filter, deterministic IDs), `existing_hashes_ids` (batched, paged lookup) | ✅ |
| `assistant/search.py` | `hybrid_search`: dense + sparse prefetch, Qdrant RRF fusion, dynamic `FilterBuilder` (sender, label, date range), result formatting | 🚧 phase 2 |
| `assistant/model.py`, `loop.py`, `main.py` | Claude client, tool-use loop, terminal chat | 🗓 phase 3 |
| `assistant/tools/{gmail,web,registry}.py` | agent tools and their schemas | 🗓 phase 3–4 |
| `assistant/store.py`, `context.py` | event log, checkpoints, approval suspend/resume; token budget/compaction | 🗓 phase 4 |
| `assistant/guardrails.py` | permission gate, PII check, grounding check | 🗓 phase 5 |
| `assistant/tools/{calendar,drive}.py`, `recipients.py` | after v1 | 🗓 later |
| `docs/DECISIONS.md` | every design decision: why, rejected alternatives, measured evidence | ✅ |
| `docs/FUNCTIONS.md` | step-by-step behaviour and contracts of each function | ✅ |
| `scratch/` (gitignored) | offline Gmail sample messages + a walkthrough script showing each parsing stage | ✅ (local only) |

## 6. Tech stack (and why)

| Piece | Choice | Why |
|---|---|---|
| Language | Python (developed on 3.14) | — |
| Vector DB | **Qdrant, local mode** (`QdrantClient(path=…)`) — the *only* database | payload filters + scroll replace a separate metadata DB; no server to run in v1 |
| Dense embeddings | **`BAAI/bge-small-en-v1.5`** (384-d) via **fastembed** | reads 512 tokens; replaced `all-MiniLM-L6-v2`, which fastembed truncates at **256** tokens (≈40% of each chunk was ignored) |
| Sparse embeddings | **`Qdrant/bm25`** via fastembed, with Qdrant's `Modifier.IDF` | exact keyword matching for codes, IDs, names; 10 MB, explainable |
| Fusion | **Reciprocal Rank Fusion (RRF)** | merges dense and keyword rankings without tuning weights (🗓 phase 2) |
| Embedding runtime | fastembed (ONNX) | no PyTorch dependency — small install for a local-first tool |
| Google APIs | `google-api-python-client`, `google-auth-oauthlib` | official clients |
| HTML cleaning | BeautifulSoup + lxml | |
| Retries | tenacity | exponential backoff with jitter |
| LLM | Anthropic Claude (`ANTHROPIC_MODEL=claude-sonnet-5`) | 🗓 phase 3 |
| Planned/unused yet | `pypdf`, `python-docx`, `apscheduler` are in `requirements.txt` for Drive extraction and scheduling after v1 | |

## 7. Key design decisions (summary — full detail in `docs/DECISIONS.md`)

1. **Hybrid search, because each method fails where the other succeeds** (measured):

   | Query | Dense | BM25 |
   |---|---|---|
   | "was my meeting rescheduled?" (email says "move tomorrow's 1:1 to 3pm") | ✅ | ❌ no match |
   | "did the agreement get signed off?" (email: "legal approved the vendor contract") | ✅ | ❌ no match |
   | "invoice INV-20931" among 5 near-identical invoices | ❌ returned INV-20917 | ✅ |

2. **Metadata filters, vectors rank.** Hard constraints (sender, date range, source, thread) are Qdrant payload filters; relevance comes from vectors. BM25 can't replace filters: it boosts but never excludes, and the sender lives in headers, not in the chunk text.
3. **Chunking:** ~400 tokens with 50 overlap, measured in words with a 0.75 words-per-token safety ratio (300/37 words). Measured token counts for 300 words: plain text 313, normal work email 378, link-heavy email 1,902 — hence the margin. Short emails stay one chunk.
4. **Cleaning removes junk, not words.** No stopword removal: "budget was approved" vs "budget was **not** approved" stay distinguishable (similarity 0.826) but become identical (1.000) once "not" is removed as a stopword. Quoted reply chains are stripped so a thread doesn't store old messages repeatedly; **forwarded content is kept**.
5. **Each message is indexed separately**, not just the last message of a thread (keeps correct sender/date per chunk and accurate citations; avoids re-embedding whole threads on every reply). The full conversation is read live via `get_thread` (🗓).
6. **Deterministic point IDs:** `uuid5(namespace, "source:external_id:chunk_index")` — re-runs overwrite instead of duplicating.
7. **Two-level de-duplication:** (a) skip already-indexed message IDs before fetching (saves API quota); (b) compare content-hash sets before embedding (saves compute; needed for changing sources like Calendar and for re-cleaning after parser fixes). A changed item has all old chunks **deleted by filter** after the new version is embedded, so shorter versions leave no stale chunks.
8. **The embedding model is part of the collection name** (`exec_assistant_v1__bge-small-en-v1.5`), derived in config, so changing the model can never silently mix incompatible vectors.
9. **No raw email is stored.** Only cleaned chunk text, metadata and vectors. Rebuilding the index means re-fetching from Gmail.
10. **Gmail rate limiting, measured not assumed.** Google's documented limit (6,000 units/min/user, confirmed in Cloud Console) was right, but the documented cost of `messages.get` (20 units) was not: tests showed refusal at 124 gets/min and none at 97 gets/min, i.e. a real cost of ~49–62 units. The limiter counts `get` as 50 (other costs: documented × 2.5, marked "estimated") with a burst capacity equal to the most expensive single call. Retries with backoff remain the safety net and are paced too.

## 8. What's stored per chunk (Qdrant payload)

`source`, `external_id` (Gmail message ID — the identity), `thread_id`, `title` (subject), `sender`, `participants` (From/To/Cc addresses), `date` (ISO 8601), `chunk_index`, `total_chunks`, `chunk_text`, `content_hash`. Vectors: named `dense` (384) and `sparse` (BM25).

## 9. Setup (current, v1 phase 1)

1. Python 3.14 (developed on it), create a venv, `pip install -r requirements.txt`.
2. **Google Cloud (your own project):** enable the Gmail API (Calendar/Drive APIs for later); configure the OAuth consent screen in **Testing** mode and add your account as a **test user**; create an **OAuth client ID of type "Desktop app"**; download it as `credentials.json` into the project root.
3. Copy/create `.env` (see §10). Set `ANTHROPIC_API_KEY` (needed from phase 3).
4. Sign in: `python -m assistant.auth` → browser consent → `token.json` is written.
5. Ingest: `python -m assistant.ingest.gmail_ingest` (options: `--days N`, `--max N` for a small test run).

Notes:
- Always run modules from the project root with `python -m …`.
- In Google's Testing mode, refresh tokens expire after ~7 days; the app falls back to the browser consent automatically.
- First run downloads the embedding models (~67 MB dense + BM25).
- Requested scopes today: `gmail.messages.readonly`, `gmail.compose` (drafts + send), `gmail.labels`, `calendar.events.owned`, `drive.file`.
- `.env`, `credentials.json`, `token.json`, `data/`, `venv/`, `scratch/` are gitignored.

## 10. Configuration (`.env`)

**Used today:** `GOOGLE_CREDENTIALS_PATH`, `GOOGLE_TOKEN_PATH`, `GMAIL_SCOPES`, `CALENDAR_SCOPES`, `DRIVE_SCOPES`, `GMAIL_UNITS_PER_MINUTE` (4800), `QDRANT_LOCAL_PATH` (`data/qdrant`), `QDRANT_COLLECTION_NAME` (base name; the model is appended automatically), `EMBEDDING_PROVIDER` (must be `fastembed`), `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `SPARSE_EMBEDDING_MODEL`, `CHUNK_SIZE_TOKENS` (400), `CHUNK_OVERLAP_TOKENS` (50), `INGEST_LOOKBACK_DAYS` (30).

**Reserved for planned features (read by config, not used yet):** `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL`, `TURN_CEILING` (18), `HYBRID_FUSION_METHOD` (rrf), `QDRANT_MODE` (index currently always uses local mode), `INGEST_INTERVAL_MINUTES`, `CONTEXT_TOKEN_BUDGET`, `CONTEXT_COMPACT_THRESHOLD`, `EVENT_LOG_PATH`, `MEMORY_FILE_PATH`, `PRESIDIO_ENABLED`, `GROUNDING_CHECK_ENABLED`, `DRIVE_MAX_TEXT_EXTRACT_MB`, `DRIVE_SKIP_MIME_TYPES`, `INDEX_MAX_SIZE_GB`, `INDEX_RETENTION_DAYS`, `APP_ENV`, `USE_TEST_ACCOUNT`.

## 11. Roadmap

### v1 (target 2026-11-10)

| Phase | Dates | Content | Status |
|---|---|---|---|
| 1 | Oct 2–10 | ingestion, chunking, embeddings, index, de-duplication, rate limiter | ✅ done (Oct 9) |
| 2 | Oct 11–18 | hybrid search: `embed_query`, dense + BM25 prefetch merged with RRF, sender/date filters via `FilterBuilder`, name→address resolution, 5–10 labelled test questions (dense vs sparse vs hybrid comparison) | 🚧 in progress |
| 3 | Oct 19–26 | Claude client, tool-use loop with stop conditions and labelled turn ceiling, **read tools** `search_gmail`, `get_thread`, `search_web` **and compose** `create_draft` (new emails and threaded replies; drafts stay in the user's Drafts folder), terminal chat, system prompt (date/timezone, cite-every-claim) | 🗓 |
| 4 | Oct 27–Nov 2 | event log, checkpoints, approval pause/resume, `send_email` (and sending drafts) behind the approval gate, context budget/compaction | 🗓 |
| 5 | Nov 3–8 | PII + grounding guardrails, ~20-question eval set, citation grader, guardrail tests, trace viewer, fixes | 🗓 |
| — | Nov 9–10 | buffer, README, setup guide, release | 🗓 |

### After v1 / v2

- **Own MCP servers (decided):** expose Gmail, Calendar and Drive tools as the project's **own local MCP servers** wrapping the tested v1 code — not third-party/hosted Google MCP servers (those would bring back keyword-only search, lose the measured quota handling, and route mail through a third party). Layering: MCP server → tool (thin wrapper) → shared `search.py` → index.
- **Local Qdrant server (decided):** v2 runs a Qdrant **server** on the user's own machine (e.g. Docker) so several MCP servers can use the index at once; `index.py` will honour `QDRANT_MODE`/`QDRANT_URL`.
- **Constraints carried into v2:** one process owns each Google quota (one token bucket); sending needs approval in the harness **and** an approval token in the server; bulk ingestion stays outside MCP.
- **More sources:** Calendar (loops over all events every run, since events change; handles cancellations and recurring events), then Drive (needs a broader read scope than today's `drive.file`; text extracted in memory only, with size/MIME limits; native Docs exported, PDFs/.docx parsed).
- **Ingestion upgrades:** 5-minute scheduler, attachment filenames → PDF text as separate documents, Gmail history API for cheaper incremental runs, keep quoted text when you were added to a thread late, re-clean mode after parser fixes, Gmail labels (staleness to solve).
- **Retrieval upgrades:** chunk by real token counts (split oversize chunks), SPLADE vs BM25 experiment with evals.
- **Product:** setup guide/wizard for other developers, a proper UI, packaging, system-keychain token storage. Agent Skills for longer procedures (e.g. "draft in my style").

## 12. Known limitations (be upfront in the README)

- Gmail only for now; search and the agent are not built yet.
- Testing-mode Google tokens expire about weekly (re-consent opens automatically).
- Quoted text is stripped even when you were added to a thread later and the quote is your only copy (planned fix).
- `drive.file` scope can't see existing Drive files (Drive deferred).
- Chunk sizes use a words-per-token estimate; very link-heavy text can still exceed the model's 512-token window.
- Gmail quota costs other than `messages.get` are estimates.
- Local Qdrant allows one process at a time.

## 13. Privacy & security notes

- Secrets and data (`.env`, `credentials.json`, `token.json`, `data/`) are gitignored.
- Email is stored locally as cleaned chunks + vectors only; no raw messages or attachments are saved.
- Sending email will always require explicit user approval (planned guardrail, v1 phase 4).

## 14. Suggested README structure

1. Title + one-liner + status line ("v1 in progress — phase 1 of 5 complete")
2. Why it exists / philosophy (local-first, BYO keys, learning/portfolio)
3. What works today vs what's coming (status table)
4. Architecture diagram + module table
5. How hybrid search works (with the evidence table)
6. Setup & first run
7. Configuration
8. Design decisions highlights → link `docs/DECISIONS.md`
9. Roadmap (v1 phases, v2)
10. Known limitations
11. Privacy & security
12. License (placeholder — not decided)
