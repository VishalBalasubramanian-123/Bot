# Function reference — ingestion core

What each function does, step by step, and the contract callers rely on.
The code keeps only one-line docstrings; the detail lives here.
For *why* a design was chosen, see [DECISIONS.md](DECISIONS.md).

Last updated: 2026-10-08

---

## `assistant/ingest/index.py`

The one Qdrant collection: client, collection setup, payload schema, change detection and upsert.
Every source (Gmail now; Calendar and Drive later) stores data through `upsert_document()`, so every point carries the same payload fields.

### Constants

| Name | Value | Purpose |
|---|---|---|
| `DENSE`, `SPARSE` | `"dense"`, `"sparse"` | names of the two vectors on every point; must match `create_collection` |
| `SOURCES` | `("gmail", "calendar", "drive")` | allowed values for `source` |
| `_ID_NAMESPACE` | fixed UUID | namespace for `uuid5` point IDs. **Never change it** — every existing point ID depends on it; changing it turns re-runs into duplicates |
| `_ID_BATCH_SIZE` | `500` | how many IDs go into one `MatchAny` filter in `existing_hashes_ids` |

### Module setup (runs on import)

1. Opens a local Qdrant client at `config.QDRANT_LOCAL_PATH`.
2. If `config.QDRANT_COLLECTION_NAME` doesn't exist, creates it with:
   - dense vector `DENSE`: size `config.EMBEDDING_DIM` (384), cosine distance
   - sparse vector `SPARSE`: `Modifier.IDF` (required for BM25's "rare words count more")

Note: local Qdrant allows one client per folder. Planned change: move this into a `get_client()` function so importing the module has no side effects.

---

### `Document` (dataclass)

One email / event / file **before chunking**. It is a hand-off format between a source pipeline and `upsert_document`; it is never stored itself.

| Field | Type | Meaning |
|---|---|---|
| `source` | `str` | `"gmail"`, `"calendar"` or `"drive"` |
| `external_id` | `str` | the item's ID in its source (Gmail message ID, event ID, file ID). **Identity** of the item |
| `title` | `str` | subject / event title / file name |
| `text` | `str` | the cleaned text to chunk and embed |
| `date` | `str \| None` | ISO 8601 |
| `sender` | `str \| None` | who sent / organised / owns it |
| `participants` | `list[str]` | addresses involved (From + To + Cc for Gmail) |
| `thread_id` | `str \| None` | Gmail only — groups messages into a conversation |
| `mime_type` | `str \| None` | Drive only — file type, for storage-bounding rules |
| `metadata_only` | `bool` | Drive only — `True` when the file's contents were deliberately not read |

Gmail builds it with `Document(**message_fields(msg))`.

---

### `upsert_document(document, known_hashes) -> int`

Stores **one** Document in Qdrant. The caller loops over items; this function loops over that item's chunks.

**Arguments**
- `document` — a `Document`.
- `known_hashes` — **required.** The set of `content_hash` values currently stored for this `external_id`:
  - `set()` → nothing is stored (new item)
  - `{"a3f…", …}` → these are stored
  The caller always does this lookup itself (batched, via `existing_hashes_ids`). There is no "look it up for me" mode.

**Returns** the number of points written. `0` means nothing was written (empty text, or unchanged).

**Steps**
1. **Chunk:** `chunks = chunk_text(document.text)`. No chunks (empty text) → return `0` without embedding or touching Qdrant.
2. **Hash:** `content_hash` of every chunk, kept in order. `total_chunks = len(chunks)` — the same value on every chunk.
3. **Compare (before embedding — embedding is the expensive step):**

   | `known_hashes` | vs new hashes | Action |
   |---|---|---|
   | empty | — | new → continue |
   | non-empty | equal (as sets) | unchanged → return `0` |
   | non-empty | different | changed → continue; old points deleted in step 5 |

   The decision is about the **whole item**, made only after every chunk is hashed. Set comparison ignores order.
4. **Embed** all chunks in one call: `embed_documents([f"{title}\n\n{chunk}", …])`. The title is prefixed so every chunk (not just the first) is findable by subject. The payload's `chunk_text` stays the plain chunk.
5. **Delete old points** — only if something was stored (changed item). Deletes by **filter** (`source` AND `external_id`), so every old chunk goes, however many there were. Happens **after** embedding, so a crash while embedding leaves the old version intact.
6. **Build one point per chunk** (`chunk_index` from `enumerate`, starting at 0):
   - `id = uuid5(_ID_NAMESPACE, f"{source}:{external_id}:{chunk_index}")` — deterministic: re-running overwrites instead of duplicating.
   - `vector = {DENSE: [...384], SPARSE: SparseVector(indices, values)}`
   - `payload` = flat dict: `source, external_id, thread_id, title, sender, participants, date, chunk_index, total_chunks, chunk_text, content_hash`
7. **Upsert** all points in one `client.upsert` call.
8. **Return** `len(points)`.

**Callers**

| Pipeline | Loops over | Passes |
|---|---|---|
| Gmail | new IDs only (emails never change) | `set()` |
| Calendar (later) | all events in the window (events change) | `seen.get(event_id, set())` |

**Verified behaviour:** new → written · same again → `0` · changed → replaced · 4 chunks shrinking to 1 → no leftovers · empty text → `0` · missing `known_hashes` → `TypeError`.

---

### `existing_hashes_ids(source, ids) -> dict[str, set[str]]`

Finds which of `ids` are already stored for `source`, and their chunk hashes — in one batched lookup.

**Returns** `{external_id: {content_hash, …}}` for **stored** items only. IDs that aren't stored are simply absent. Returns a plain `dict` (not a `defaultdict`), so reading a missing key raises `KeyError` instead of silently adding it — use `in` or `.get(id, set())`.

**Steps**
1. Empty `ids` → return `{}` without querying Qdrant.
2. Split `ids` into batches of `_ID_BATCH_SIZE` (500).
3. For each batch, start a **fresh** scroll (`offset = None`) with filter `external_id ∈ batch` AND `source == source`, fetching only `external_id` and `content_hash` (no vectors).
4. Page through with `limit=100`, following `next_page_offset` until it is `None`. Points arrive in point-ID order, so one item's chunks are scattered across pages — hashes are accumulated into a set per `external_id` across all pages.
5. Return `dict(stored)`.

**Used by**
- Gmail: `seen = existing_hashes_ids("gmail", ids)` → `new_ids = [i for i in ids if i not in seen]`
- Calendar (later): `known_hashes=seen.get(event_id, set())`

**Verified behaviour:** 1,200 stored items across 3 batches all found · every item has all its hashes · missing IDs absent · other sources not mixed in · 500 / 501 batch boundary · empty list → `{}`.

**Pitfalls this function avoids**
- Ignoring `next_page_offset` → only the first page (10 points by default) is seen.
- Not resetting `offset` per batch → about half the stored items are missed (630 of 1,200 in a test).
- Returning the `defaultdict` → `seen[x]` on a new ID silently marks it as stored.

---

## `assistant/ingest/chunking.py`

### `chunk_words(text, size_words, overlap_words) -> list[str]`
Splits text into chunks of `size_words` words, each overlapping the previous by `overlap_words`.
- Words come from `text.split()`; each chunk is the words re-joined with spaces.
- `step = size_words - overlap_words`; next chunk starts at `start + step`.
- **Stops after the chunk that reaches the last word** (`start + size >= len(words)`), so there is never a trailing chunk made only of overlap.
- No words (empty or whitespace-only) → `[]`. Text shorter than one chunk → one chunk.

### `chunk_text(text, size_tokens=None, overlap_tokens=None) -> list[str]`
What the rest of the system calls. Fills in `config.CHUNK_SIZE_TOKENS` / `CHUNK_OVERLAP_TOKENS`, converts tokens → words with `WORDS_PER_TOKEN = 0.75` (400 → 300 words, 50 → 37), then calls `chunk_words`. The ratio is a safety margin: one word is often more than one token, and the model reads at most 512 tokens.

### `content_hash(text) -> str`
SHA-256 of the UTF-8 text, as 64 hex characters. Same text → same hash; any change → a different hash.

---

## `assistant/ingest/embeddings.py`

Text in, vectors out. No Qdrant, no metadata, no vector names.

### Models
`TextEmbedding(model_name=config.EMBEDDING_MODEL)` (bge-small-en-v1.5, 384-d) and `SparseTextEmbedding(model_name=config.SPARSE_EMBEDDING_MODEL)` (BM25), each loaded **once** (loading takes seconds; embedding is fast).

### `embed_documents(texts) -> list[tuple[list[float], tuple[list[int], list[float]]]]`
Returns one `(dense, (indices, values))` pair per input text, in input order.
- Dense: a plain list of 384 floats (`.tolist()` per result).
- Sparse: `(indices, values)` as plain lists — the caller wraps them in `models.SparseVector`.
- Both model outputs are generators; each result is converted individually.
- Empty list → `[]`.

**Verified behaviour:** two texts → two pairs · dense length 384 · deterministic · order preserved · `"the budget meeting is on thursday"` → 3 sparse entries (stopwords dropped).

### `embed_query(text)` — planned (phase 2)
Same as above for a single search question, using `query_embed` (BM25 weights queries differently from documents).

---

## `assistant/auth.py` — Google API calls

### `execute(request)`
Every Google API call in the project goes through this. Two layers, in this order:
1. **Pace (prevent):** works out the call's Gmail quota cost from `request.methodId` and waits on the shared token bucket until the budget allows it. Non-Gmail requests (Calendar, Drive) cost 0 here — they have different quota systems.
2. **Retry (recover):** `@retry` re-runs the whole body on 429, on 403 with `rateLimitExceeded` / `userRateLimitExceeded` / `quotaExceeded`, and on 5xx — exponential backoff with jitter (1 s → max 60 s, 6 attempts). Because the pacing is inside the retried body, **every retry is paced too**.

### `_gmail_unit_cost(request) -> int`
Looks up `request.methodId` in `_GMAIL_UNIT_COSTS`. Non-Gmail → 0. Unknown Gmail method → the most expensive known cost (250), with a warning — never under-count.
Costs are what Google **actually** charges, not the documented ones: `messages.get` = 50 (**measured**; documented 20). The rest are documented × 2.5 (**estimated**): `messages.list` 13, `drafts.create` 25, `threads.get` 100, `messages.send` / `drafts.send` 250. See DECISIONS 3.10.

### `_TokenBucket(units_per_minute, capacity)` / `.acquire(cost)`
- Refills at `units_per_minute / 60` units per second, up to `capacity`.
- `acquire(cost)`: top up by elapsed time; if enough units, take them and return; otherwise sleep until enough have refilled.
- Uses `time.monotonic()` (never jumps) and a `threading.Lock` (safe if ingestion and chat share it).
- A cost above `capacity` is clamped to `capacity` — so capacity must be at least the largest cost.
- One shared instance, `_gmail_bucket`: budget `config.GMAIL_UNITS_PER_MINUTE` (4,800 → 80 units/s), capacity = the largest cost (250). Steady state for ingestion: 80 ÷ 50 = 1.6 gets/s ≈ **96 gets/min**; burst after a pause: 250 ÷ 50 = 5 gets.

**Verified behaviour:** offline — costs looked up correctly; a send waits 250/80 ≈ 3.1 s from an empty tank (not clamped); 15 gets = 5 instant + 10 × 0.625 s; a retried call is paced on each attempt; two threads don't overspend. Live — 242 gets over 150 s at 97/min with no 403.
