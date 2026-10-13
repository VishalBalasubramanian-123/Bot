# Design decisions — exec-assistant

A running log of what was decided, why, and what was rejected. Source material for the blog post.
Each entry: **Decision · Why · Rejected alternatives · Evidence** (where we measured something).
Status markers: ✅ decided · 🟡 open · ⏸ deferred.

Last updated: 2026-10-05

---

## 1. Product and scope

### 1.1 ✅ Local-first, bring-your-own-keys, $0 to run
- **Decision:** Everything runs on the user's laptop (ingestion, Qdrant, embeddings, agent loop). Each user brings their own Google OAuth client and their own Anthropic API key. Audience: developers. Open source.
- **Why:** An email assistant holds the most private data a person has. "Your email never leaves your laptop" is a stronger promise than "we store it securely". It also costs the author nothing: no servers, no per-user storage, no Google verification.
- **Rejected — cloud backend:** Gives always-on ingestion, multi-device, and simpler billing, but the author would hold everyone's email and tokens (breach risk, trust), pay per-user storage/compute, and bring server infrastructure into Google's security-assessment scope.
- **Rejected — one verified public app:** Gmail read access is a *restricted* scope. Public release needs Google verification plus an annual third-party security assessment (CASA), which is paid. Without it the app is capped at 100 hand-added test users.
- **Trade-off accepted:** users must create their own Google Cloud project (~10–15 min), which limits the audience to technical users. Mitigation later: a setup guide/wizard.

### 1.2 ✅ v1 = Gmail only, with web search, drafting and sending
- **Decision:** v1 covers Gmail ingestion; tools `search_gmail`, `get_thread`, `search_web`, `create_draft`, `send_email`. Calendar and Drive come after v1.
- **Why:** The harness, guardrails and evals are the point of the project, and they're source-independent. Dropping a second ingestion pipeline was the cheapest way to make room for them.
- **Non-negotiable:** harness (loop, stop conditions, context budget, event log, approval suspend/resume), guardrails (permission gate, PII check, grounding check), evals. Cutting these would turn the project into a chatbot demo.
- **Target:** 2026-11-10. Learning goal over speed: every line is written by the author, so every design question can be answered.

### 1.3 ✅ One database: Qdrant in local mode
- **Decision:** Qdrant only, `QdrantClient(path=...)`, no server. No SQLite, no metadata DB, no raw-content backup.
- **Why:** Structured lookups (sender, date, thread) are done with payload filters and the scroll API. One store means no sync problems between two databases. Switching to a Qdrant server later is a config change (`QDRANT_URL`).

---

## 2. Auth and configuration

### 2.1 ✅ OAuth desktop flow with PKCE; scopes kept as originally granted
- **Decision:** `InstalledAppFlow.run_local_server`, token saved to `token.json`. Scopes: `gmail.messages.readonly`, `gmail.compose`, `gmail.labels`, `calendar.events.owned`, `drive.file`. `.env` lists the same scopes as the token.
- **Why:** The desktop "client secret" is not truly secret by Google's own model; security comes from PKCE (`code_challenge` in the auth URL) and the user's consent. `gmail.compose` already covers drafting **and** sending, so no re-consent was needed for v1 actions.
- **Known limits:** `drive.file` only sees files the app created/opened — Drive ingestion would index almost nothing (one reason Drive is deferred). In Testing mode, refresh tokens expire after ~7 days.
- **Bug found:** the first `auth.py` exited silently with code 0 — it defined `get_credentials()` but never called it, and used CWD-relative paths. Fixed with a `__main__` block, logging, and paths anchored to the project root.

### 2.2 ✅ One `config.py` reads `.env`; settings are typed and fail loudly
- **Decision:** All settings are read in one place, converted to the right type (`_int`, `_float`, `_bool`, `_list`, `_path`), and a missing required value stops the program at startup.
- **Why:** `.env` values are strings — `bool("false")` is `True` in Python. Failing at startup beats a confusing error twenty minutes into a run. Paths resolve from the project root, not the current directory.

### 2.3 ✅ System settings never mix with content
- **Decision:** The embedding model name is recorded in the collection name (derived in `config.py`), not in each point's payload.
- **Implementation:** `.env` holds only the base name (`QDRANT_COLLECTION_NAME=exec_assistant_v1`). `config.py` computes the collection actually used as `base + "__" + EMBEDDING_MODEL.split("/")[-1]` → `exec_assistant_v1__bge-small-en-v1.5`. Changing `EMBEDDING_MODEL` automatically switches to a fresh collection; the model name exists in exactly one place.
- **Rejected — typing the model into the collection name in `.env`:** two copies of one fact; changing the model but not the name would put new-model vectors into the old-model collection.
- **Why:** The payload is user content (what was said, by whom, when). Model names are system configuration. Keeping them apart also means tool results only ever contain content fields.
- **Rejected — `embedding_model` per chunk:** robust and allows gradual migration, but mixes system metadata into content.
- **Why record the model at all:** bge-small and MiniLM both produce 384-d vectors. Qdrant would silently accept a mix, and search quality would quietly degrade. Changing model must mean a new collection.

---

## 3. Ingestion (Gmail)

### 3.1 ✅ Pipeline shape
```
list IDs → skip IDs already indexed → fetch new messages → clean → Document
   → index.upsert_document: chunk → hash → (compare) → embed → points → upsert
```
- **Fetch and parse are separate modules** (`gmail_ingest.py` / `gmail_parse.py`). Parsing is pure functions, testable offline on sample JSON; only the fetch module talks to the API and to `index.py`. Same pattern for future Calendar/Drive pipelines.

### 3.2 ✅ List first, fetch only what's new; lookback window instead of a cursor
- **Decision:** `messages.list(q="newer_than:30d -in:drafts -in:chats")` returns IDs only; IDs already in Qdrant are skipped before any download.
- **Why:** Listing is one call per 500 IDs; fetching is one call per message. A lookback window keeps runs stateless — no "last run" cursor to store (the single-DB rule), and a crashed run is repaired by the next one.
- **Deferred:** Gmail's history API (`historyId`) returns only changes since a checkpoint. Cheaper, but needs a stored cursor. Not worth it for a personal mailbox in v1.

### 3.3 ✅ Dedup: `external_id` for Gmail; `content_hash` kept for changing content
- **Decision:** Gmail messages are immutable, so "is this `external_id` already stored?" is enough day to day. Every chunk still stores a `content_hash`, and `upsert_document` keeps the hash comparison.
- **Why keep the hash:** Calendar events and Drive files change under the same ID; and after a parser fix, old Gmail chunks are stale — the hash detects which emails' cleaned text actually changed so only those are re-embedded.
- **Why hashes, not vectors:** the hash is computed from text *before* embedding (so it can skip the expensive step), it's 64 characters instead of 384 floats, and exact float equality is fragile across machines.
- **Note:** Gmail never exercises the comparison path, so it needs its own test (same doc twice → 0 written; changed → replaced; shorter → no stray chunks).
- **Two checks, one lookup:** `existing_hashes_ids(source, ids)` returns `{external_id: {content_hash, ...}}` for stored items, in batches of 500 IDs with full paging (offset reset per batch). It returns a plain `dict`, not the internal `defaultdict`, so reading a missing key raises instead of silently marking it "stored".
- ✅ **`known_hashes` is a required argument — every pipeline does the lookup itself.** Gmail loops over new IDs only and passes `set()` ("I looked: nothing stored"). Calendar (later) loops over all events and passes `seen.get(event_id, set())`. `upsert_document` never queries Qdrant for hashes itself.
  - **Why:** one batched lookup per run instead of one per item; one less case in `upsert_document`; forgetting the argument is an immediate `TypeError` instead of a silent bug.
  - **Rejected — `known_hashes=None` meaning "look it up yourself":** it served no real caller (both pipelines batch their own lookup), and it was repeatedly misread as "new" or "skip", turning into silent bugs (new items never stored; changed items never updated).
- **How `upsert_document` decides:** empty set → write as new; equal set → return 0 (before embedding); different set → embed, then delete all old points of that `external_id` by filter, then write. Embedding before deleting means a failure never leaves the item with no points.

### 3.4 ✅ Body selection: plain text over HTML, attachments skipped
- **Decision:** Walk the MIME tree with an explicit stack; take the first `text/plain`, else `text/html`; skip any part with a filename or no inline data.
- **Why:** Most emails carry both versions; plain text is already clean. Attachments only have an `attachmentId` (a separate API call).
- **Known quirk:** `stack.pop()` visits parts in reverse order, so "first plain part found" is actually the *last* in the email. Harmless with one plain part; matters if a client splits the body.

### 3.5 ✅ Cleaning removes junk, not words
- **Decision:** Strip HTML tags/styles, quoted reply chains and extra whitespace. Do **not** remove stopwords or do other classic NLP preprocessing.
- **Evidence:** "The budget was approved" vs "The budget was **not** approved": bge-small similarity 0.826 (distinguishable). After stopword removal both become "budget approved": similarity **1.000** ("not" is a stopword). Vowel removal breaks the tokenizer into fragments.
- **Why:** Dense models were trained on natural sentences. BM25 does its own stopword removal and stemming internally.

### 3.6 ✅ Quote stripping, and forwards are kept
- **Decision:** Cut at `On … wrote:`, `-----Original Message-----`, or an Outlook `From:`/`Sent:` block; drop `>` lines. A forward is split at its marker: the forwarder's words are stripped as usual, the forwarded part is kept untouched (with its From/Date/Subject), only the marker line is dropped.
- **Why:** Without stripping, message 10 of a thread re-stores messages 1–9, and search fills with duplicates of the oldest email. But a forward's content *is* the message.
- **Bugs found by review:** (1) forwards were cut entirely; (2) even after removing the forward rule, the Outlook `From:`+`Date:` rule still matched the forward's header block; (3) HTML forwards were deleted as `div.gmail_quote`; (4) `get_text("\n")` split inline tags onto separate lines ("The / Atlas / launch moved to / October 14"); (5) text before a nested `<div>` was glued to it.
- 🟡 **Open:** a reply where you were added later (To/Cc) — the quote is your only copy and is currently stripped. Planned rule: keep the quote only for the earliest message you have in that thread (needs `threads.get`).

### 3.7 ✅ Index each message, not "just the last message of the thread"
- **Rejected idea:** index only the latest reply, since it quotes the whole conversation.
- **Why rejected:** (1) quoted text inherits the last email's `sender`/`date`, so "what did Priya say on Sep 29" filters fail and citations point to the wrong email; (2) every new reply forces re-embedding the whole thread — new text at the top shifts every chunk boundary and changes every hash; (3) branches, trimmed quotes and inline replies mean the last email doesn't always contain everything.
- **Instead:** the index finds the right message; the `get_thread` tool reads the full conversation live from Gmail when the model needs it.

### 3.8 ⏸ Attachments
- **v1:** skipped. **Next:** record attachment filenames on the Document (no extra API call). **Later:** extract PDF text as its *own* Document (title = filename, same `thread_id`, own `external_id`), reusing Drive's extraction and its size/MIME limits. Scanned PDFs need OCR — out of scope.

### 3.9 ✅ The Document is transient; nothing raw is stored
- **Decision:** `Document` is the hand-off format between "getting an email" and "storing it". It lives in memory only. Raw JSON, base64 and HTML are discarded after parsing.
- **Why:** The spec forbids a raw-content backup — Gmail already stores the original, and rebuilding means re-fetching. Nothing is deleted from Gmail (the app can't).


### 3.10 ✅ Pace Gmail calls with a token bucket, using *measured* costs; keep backoff as the safety net
- **Problem:** the full 30-day run (810 emails) hit `403 rateLimitExceeded` — "Units per minute per user" — after ~100 emails.
- **Decision:** `auth.execute()` paces every Gmail call with a shared **token bucket**: budget `GMAIL_UNITS_PER_MINUTE=4800` (80% of 6,000), capacity = the most expensive single call (250). The cost of each call is looked up from `request.methodId`, so callers just write `execute(req)`.
- **Why a units budget, not a fixed gap:** calls cost different amounts; a fixed gap over-paces cheap calls and under-paces expensive ones.
- **Why keep the retry:** pacing prevents *our* overspend, but Google 5xx errors and other usage on the same account still happen. Pacing sits *inside* the retried body, so retries are paced too.
- **Rejected — a pause in `index.py`:** the quota counts Gmail API calls only; indexing costs Google nothing.
- **Rejected — caller passes the cost (`execute(req, cost=20)`):** costs scattered across call sites, easy to get wrong.

**The first version was wrong — and only measurement showed it.** It used the documented `messages.get` cost (20) and a tank of a tenth of the budget (480). It still got refused. Measurements (paced `messages.get?format=full`, no retries, 65 s gap between tests):

| Test | Pace | Result |
|---|---|---|
| tank 480, get = 20 | ~285 gets/min | 403 after 110 gets, 23 s — only 2,200 documented units in the minute |
| tank 100, get = 20 | 246 gets/min | 403 after 163 gets, 40 s |
| budget 2,400, get = 20 | 124 gets/min | 403 after 122 gets, 59 s |
| tank 100, **get = 50** | **97 gets/min** | **no 403 in 150 s (242 gets)** |

- **Conclusion:** Cloud Console confirms the limit is the documented **6,000 units/min/user** — so the *cost* is what's wrong. 124/min refused → cost > ~48; 97/min accepted → cost ≤ ~62. A full `messages.get` costs **~49–62 units, not 20**. Counted as 50 → 96 gets/min, safe even at 62 (5,952).
- **Other costs:** not measured (measuring `send` means sending real email). Set to documented × 2.5 as a cautious estimate and marked "estimated" in code. Sends are rare and human-approved, so over-estimating them costs nothing.
- **Tank size:** a large tank was actively harmful — at natural speed (~5 gets/s) a 480-unit tank drained so slowly (refill during each call) that pacing never started before Google refused. Capacity is now the **largest single cost** (250): every call fits (no under-counting via `min(cost, capacity)`), and pacing starts within ~5 calls.
- **Earlier wrong advice, corrected:** "any capacity between 100 and 1,200 is safe" assumed Google counts over a whole minute; it effectively enforces over shorter windows. A 700-unit tank would have been refused sooner.
- **Lesson:** the documented *limit* was right; the documented *cost* wasn't. Verify quotas by measuring, with the Console's usage graph as a cross-check.

---

## 4. Chunking

### 4.1 ✅ Chunk, don't embed whole emails
- **Why:** (1) the model reads at most 512 tokens and silently drops the rest; (2) one vector for a long document blurs many topics, so specific searches match poorly. Short emails stay as one chunk.

### 4.2 ✅ ~400 tokens, 50 overlap, measured in words with a 0.75 ratio
- **Decision:** `chunk_text` converts tokens to words (400 × 0.75 = 300 words, 50 × 0.75 = 37) and calls `chunk_words`. Stop when `start + size >= len(words)`.
- **Why tokens in config, words in code:** model limits are in tokens; `.split()` gives words. The ratio is a safety margin, because one word often becomes several tokens.
- **Evidence (bge-small tokenizer, 300 words):** plain story 313 tokens · normal work email 378 · link-heavy email **1,902** (1,390 dropped). A 400-word link-heavy chunk measured 1,042 tokens and the final line "the budget is approved" never reached the vector. Examples: `unbelievably` → 5 tokens; a Google Docs URL → 21.
- **Rejected — 1 word = 1 token:** fine for plain prose, but a normal email at 400 words lands at ~500 tokens, right at the limit.
- ⏸ **Upgrade:** count real tokens with the model's tokenizer and split any over-limit chunk into ≤512-token pieces (each its own chunk). The model has no memory between calls, so overflow can't be "queued" into the same vector — it must become a new chunk. Averaging vectors was rejected: it blurs meaning.

### 4.3 ✅ `chunk_words` vs `chunk_text`
- `chunk_words(text, size, overlap)` is the algorithm, in words, testable with hand-worked examples. `chunk_text(text)` is what the rest of the system calls: it applies `.env` defaults and the token→word conversion. Changing chunking later touches one file.

### 4.4 ✅ Chunking happens in `index.py`, not in each pipeline
- **Why:** one place, same rules for every source (unified schema); chunking, hashing, `chunk_index`/`total_chunks` and the dedup comparison depend on each other.
- **When to revisit:** sources with natural sections (PDF pages, sheet rows, slides). Then a Document could optionally carry pre-split sections.

---

## 5. Embeddings

### 5.1 ✅ fastembed, not sentence-transformers
- **Why:** ONNX runtime, no torch dependency, small install — important for a local-first app.

### 5.2 ✅ Dense model: `BAAI/bge-small-en-v1.5` (384-d), replacing MiniLM
- **Evidence:** in fastembed, `all-MiniLM-L6-v2` truncates at **256** tokens, so ~40% of each 400-token chunk never reached the vector. bge-small reads **512**, same 384 dimensions. Switch required a full re-index.
- **Bug found by review:** `TextEmbedding(model=...)` silently ignores the unknown keyword and loads the default model (which happened to be bge-small). Correct keyword: `model_name=`. Lesson: test that code does what you asked, not just that it runs.

### 5.3 ✅ Hybrid search: dense + sparse (BM25), merged with RRF
- **Why:** they fail in opposite ways.
- **Evidence (same collection, top result):**

| Query | Dense | Sparse (BM25) |
|---|---|---|
| "was my meeting rescheduled?" → email says "move tomorrow's 1:1 to 3pm" | ✅ | ❌ no match at all |
| "did the agreement get signed off?" → "legal approved the vendor contract" | ✅ | ❌ no match at all |
| "invoice INV-20931" among 5 near-identical invoices | ❌ returned INV-20917 | ✅ |

- Dense = semantic (meaning, paraphrases). Sparse = keyword (exact codes, IDs, rare names). RRF promotes anything ranked high by either.

### 5.4 ✅ Sparse model: `Qdrant/bm25`
- **What it is:** not a neural model — tokenize, lowercase, drop stopwords, stem, weight term frequency with saturation and length normalization. IDF ("rare words matter more") depends on the whole collection, so Qdrant applies it at query time — **requires `modifier=Modifier.IDF`** on the sparse vector config.
- **Rejected for v1:** SPLADE++ (0.53 GB, neural expansion — overlaps dense's job), BM42 (experimental), miniCOIL (newer, less proven). BM25 is 0.01 GB, fast, and explainable word by word.
- ⏸ **Experiment for later:** swap in SPLADE, re-run evals, report dense-only / sparse-only / hybrid scores.

### 5.5 ✅ `embeddings.py` does one job: text in, vectors out
- **Decision:** returns `[(dense, sparse), ...]` — one tuple per input text, same order. No Qdrant import, no metadata, no knowledge of vector names.
- **Why:** search must embed *questions*, which have no metadata. Vectors and metadata are joined in `index.py` when building points. Importing Qdrant names into `embeddings.py` created a circular import (index → embeddings → index).
- **Plain lists vs numpy:** `list(model.embed(...))` (as in Qdrant's docs) returns `List[np.ndarray]`, which Qdrant accepts — but `a == b` raises "truth value … is ambiguous" and arrays aren't JSON-serializable. Chosen: plain lists via `.tolist()`. Sparse needs per-item `(indices, values)` either way.
- **Load models once:** loading takes seconds; embedding is fast. Module-level loading or a `@lru_cache` factory both work; `lru_cache` defers the cost to first use instead of import time.
- **Bugs found by review:** `np.array(generator)` wraps the generator object instead of consuming it (shape `()`, dtype object); `.indices.values` chained two separate attributes.
- **Verified:** 384-d dense, sparse indices/values same length, deterministic (same text → identical vectors), order preserved, empty list → empty list. "the budget meeting is on thursday" (6 words) → 3 sparse entries (stopwords dropped).
- **Determinism vs dedup:** the pipeline never compares vectors (hashes decide *whether* to embed); determinism is tested because re-indexing and eval comparisons assume it.

---

## 6. The index (Qdrant)

### 6.1 ✅ A point = deterministic ID + named vectors + flat payload
- **ID:** `uuid5(namespace, f"{source}:{external_id}:{chunk_index}")` — same input, same UUID, so re-ingesting overwrites instead of duplicating. Qdrant accepts only unsigned ints or UUIDs, so `"msgid:0"` can't be used directly. Rejected `uuid4` (random → duplicates every run).
- **Vectors:** `{"dense": [...384], "sparse": SparseVector(indices, values)}`.
- **Payload:** a flat dict (not a nested Document object), so filters use `sender`, not `document.sender`.

### 6.2 ✅ `external_id` is identity; `thread_id` is grouping
- Gmail message IDs are unique across the mailbox, and each message belongs to one thread — so `external_id` alone identifies a chunk's email. It keys the point ID, dedup, deletion, citations, and reply lookup. Deleting by `thread_id` would wipe a whole conversation.
- `thread_id` is stored for `get_thread`, for putting replies in the right conversation, and for grouping search results.

### 6.3 ✅ Every chunk carries a copy of its email's metadata
- **Why:** search returns chunks, not emails. With one database and no joins, each chunk must answer "who sent this, when?" and pass filters on its own. Small storage cost, simple and fast lookups.

### 6.4 ✅ Metadata filters, vectors rank
- **Decision:** hard conditions (who, when, which source/thread) are payload filters; relevance is vector ranking. A filter excludes; a vector score only orders.
- **Why sparse can't replace filters:** (1) BM25 boosts but never excludes — after RRF, a strong match from the wrong sender can still rank first; (2) the sender is in the header, not the chunk text; (3) an email *mentioning* Priya isn't *from* Priya; (4) "last week" is a date range, not a word.
- **Query flow example:** "What did Priya say about the rescheduling?" → model calls `search_gmail(query="rescheduling", sender="priya…")` → Qdrant applies the sender filter during a dense + sparse search, RRF merges → top chunks with payload → cited answer. In the test, sparse found nothing ("rescheduling" vs "move"); dense found it.
- **Needs:** resolving "Priya" to an exact address (contact resolution), and tool descriptions that keep topic (`query`) and constraints (`sender`, dates) separate — evals should check the model does this.

### 6.5 Payload fields (each must have a reader)
| Field | Used by |
|---|---|
| `source` | filters, dedup |
| `external_id` | identity, dedup, citations, evals, reply lookup |
| `thread_id` | `get_thread`, replies, grouping |
| `title` | citations, display |
| `sender` | "what did X say" filter |
| `participants` | "emails involving X" filter |
| `date` (ISO 8601) | date-range filters, sorting |
| `chunk_index`, `total_chunks` | citations ("part 2 of 3"), reassembly |
| `chunk_text` | display, citations, grounding check |
| `content_hash` | change detection |

Not stored: raw JSON/HTML/base64, the full body as one field, tokens or keys, the model name (see 2.3).

### 6.6 🟡 Open payload decisions
- **Gmail labels:** useful for "needs attention" (exclude promotions), but labels like `UNREAD` change and known emails are never re-fetched, so stored labels go stale.
- **`sender` format:** `"Priya Raman <priya.raman@example.com>"` won't exact-match a filter on the address. Address only, or name + address as two fields.
- **Embedding input:** `chunk_text` alone, or `title + chunk_text` (helps later chunks of long emails). Must decide before indexing; changing it means re-indexing.
- **`chunk_index`** base 0 or 1. **`mime_type`, `metadata_only`, `ingested_at`:** include only if something reads them (`mime_type`/`metadata_only` are for Drive's metadata-only files).

---

## 7. Actions (Phase B in v1)

### 7.1 ✅ Replying is keyed on `external_id`
- **Decision:** fetch the original by `external_id` at reply time to read `Message-ID`, `Subject`, `From`, `To`, `Cc`. Set `threadId` on the draft; set `In-Reply-To` and `References` to the original's `Message-ID`; subject `Re: …`.
- **Why:** Gmail's `threadId` groups the reply in Gmail; the RFC `Message-ID` headers thread it in *other* clients. These headers aren't stored in Qdrant — fetched live, keeping the payload small. Every email has a `threadId` (a single email is a one-message thread).
- Sending always passes the approval gate (guardrails).


### 7.2 ✅ (v2) Expose Gmail / Calendar / Drive as our own MCP servers — decided 2026-10-09
- **Idea:** package the agent's tools as MCP servers so any MCP client (the agent, Claude Desktop, Claude Code) can use them.
- **Decision (option B):** wrap *our own* tested code (hybrid search, `auth.execute` with limiter + retries, cleaning, citations) as local MCP servers — not third-party/hosted Google MCP servers, which would bring back keyword-only search, lose our measured quota handling, and (if hosted) route users' email through a third party.
- **Constraints learned in v1:**
  - **One process owns each quota.** The token bucket only works if every Gmail call shares one tank; splitting Gmail calls across processes gives each its own tank and can exceed 6,000/min together. One Gmail server owns all Gmail calls (including ingestion's, or ingestion shares its limiter).
  - **Defence in depth for sending:** the approval gate lives in the harness *and* `send_email` refuses without an approval token, so a client without our harness can't send unasked.
  - **Ingestion stays outside MCP:** MCP suits one-call-at-a-time agent use, not bulk fetching.
  - **One process owns local Qdrant too.** Local mode lets only one process open `data/qdrant`, so separate Gmail/Calendar/Drive MCP server processes would conflict.
  - ✅ **Decided (2026-10-10): v2 runs a Qdrant server** so multiple MCP servers can use the index at the same time. It still runs on the user's own machine (e.g. the Qdrant Docker image or binary), so the local-first promise holds. Config already has `QDRANT_MODE` / `QDRANT_URL` / `QDRANT_API_KEY`; `index.py` must be updated to honour `QDRANT_MODE` (it currently always opens `path=`). Rejected: one MCP server process exposing every tool — simpler, but couples all sources into one process. Note: the Gmail quota still needs a single owner (one token bucket) even when Qdrant is shared.
  - **Layering:** MCP server → tool (`search_gmail`, thin wrapper) → `search.py` (shared hybrid search) → `index.py` (Qdrant). MCP servers never query Qdrant directly.
- **Note:** MCP doesn't add reliability by itself — reliability comes from the limiter, retries, guardrails and evals behind the tools.
- **v1 implications (build MCP-ready now):** each tool is a plain function with a typed schema and JSON-serializable inputs/outputs; errors are returned as short messages the model can act on (not stack traces); all Gmail calls go through `auth.execute`; `send_email` is designed to require an approval token from day one.

---

## 8. Observability and evals

### 8.1 ✅ Own JSONL event log, local viewer
- **Decision:** append one JSON line per model call and tool call (tokens in/out, tool name and args, result summary, citations). View traces locally.
- **Why:** traces contain email content, so hosted tracing services (LangSmith, Langfuse cloud) would send users' mail to a third party. The grader reads citations from this log. Arize Phoenix (local) was considered as a viewer; bundling it into a desktop app is heavy.

### 8.2 ✅ Hand-labelled evals with a citation grader
- **Decision:** ~20 real questions per the v1 jobs, each with `expected_sources` (message IDs). Grader: Jaccard similarity between cited and expected sources, pass at > 0.7. Plus guardrail tests (unapproved send blocked, ungrounded answer caught).
- **Why:** turns "I think chunk size 250 is better" into a measured result, and pairs with the trace viewer: the grader says *how often* it fails, the trace says *why*.

---

## 9. Process notes (for the blog)
- **Write first, then compare to open source.** Reading reference code first makes copying too easy.
- **Most real bugs were found by running code against concrete cases**, not by reading it: silent `auth.py`, MiniLM truncation, forward stripping, HTML line breaks, `model=` silently ignored, `np.array(generator)`.
- **Sample fixtures** (`scratch/gmail_samples/`) made every cleaning step visible and testable offline, without touching real mail.
