# Designs Service

AI poster studio: a customer's prompt becomes a poster image, the poster becomes
a print-on-demand catalog product, and the customer's prompts and purchases
become a style profile that personalises later generations.

## Purpose

- Accept a prompt and generate a poster image **asynchronously**: `POST /generations`
  queues a row and answers 202; a background worker calls the image provider and
  stores the PNG; the shop polls until the row is `ready` or `failed`
- Serve the generated images itself (`GET /images/{key}`) so the storage backend
  (local volume or a private S3 bucket) is never exposed
- "Print this": turn a ready design into an **unlisted** catalog family
  (`AI-{id}`, variants `AI-{id}-A4..A1`) plus virtual stock, so it rides the
  existing cart → order → pay → production → notifications pipeline unchanged
- Keep a per-customer memory in three tiers: generation history, saved prompts,
  and a style profile (a 1–2 sentence summary of prompts + purchased posters)
  that is prepended to the prompt when the customer ticks "Personalise"
- Subscribe to `ORDER_PAID` from the orders outbox to stamp `purchased_at` on
  bought designs and to feed the style profile

## Tech Stack

- FastAPI
- SQLAlchemy 2 + Alembic — owns `designs_schema` (`generations`, `saved_prompts`,
  `style_profiles`, `purchases`, `processed_events`)
- httpx — the OpenAI / Replicate HTTP calls and the catalog / inventory clients
- Pillow — the fake provider's placeholder poster
- boto3 — S3 storage backend (credentials from IRSA, never stored)
- prometheus-client — generation, latency, queue and circuit-breaker metrics

## API Endpoints

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | /generations | Queue a generation; 202 + the `queued` row; 429 + `Retry-After` over the daily quota | Bearer |
| GET | /generations | The caller's generations, newest first (`?limit=` 1..200, default 50) | Bearer |
| GET | /generations/{id} | One generation (someone else's id is a 404) | Bearer |
| POST | /generations/{id}/print | Create the catalog family + stock; 201 created / 200 already printed / 409 not ready / 502 downstream refusal / 503 outage or open breaker | Bearer |
| GET, HEAD | /images/{key} | The generated PNG; `key` is 32 hex + `.png`; immutable for a year | - (the key is the capability) |
| GET | /saved-prompts | The caller's saved prompts, newest first | Bearer |
| POST | /saved-prompts | Save `{title, prompt}` → 201 | Bearer |
| DELETE | /saved-prompts/{id} | Delete one → 204 (404 for another customer's row) | Bearer |
| GET | /me/quota | `{limit, used, remaining, resets_at, exempt}` for today (UTC) | Bearer |
| GET | /me/style-profile | The stored style summary + counts + `stale` | Bearer |
| POST | /me/style-profile/refresh | Rebuild the summary now from prompts + purchases | Bearer |
| POST | /events/order-paid | ORDER_PAID from the orders outbox | Service token or owner |
| GET | /healthz | Liveness probe | - |
| GET | /readyz | Readiness probe (checks DB connectivity) | - |
| GET | /metrics | Prometheus metrics | - |

`/events/order-paid` is called by the orders outbox worker over cluster-internal DNS.
In Kubernetes the whole service sits behind the frontend ingress at `/api/designs`
(`ROOT_PATH=/api/designs`); the image route is deliberately unauthenticated because
`<img>` tags cannot send a bearer — the unguessable key is the capability.

### Response Contract

`GET /generations/{id}` (and every element of `GET /generations`) is a `GenerationOut`:

| Field | Meaning |
|-------|---------|
| `id`, `prompt`, `personalise`, `provider`, `created_at` | As submitted; `provider` is the name active when the row was queued (`fake` / `openai` / `replicate`) |
| `effective_prompt` | What was actually sent to the provider — the prompt plus `\n\nStyle notes: …` when personalised |
| `status` | `queued` → `generating` → `ready` \| `failed` |
| `failure_reason` | Set on `failed`: the provider's refusal text, or a generic outage / configuration message |
| `image_url` | `/api/designs/images/{key}` — only once `ready` (`DESIGNS_PUBLIC_URL_PREFIX`) |
| `started_at`, `finished_at` | The last attempt's window; `finished_at` is stamped after the provider call returns |
| `purchased_at` | Set by the ORDER_PAID consumer when one of this design's variants was bought |
| `catalog_product_sku`, `product_url` | `AI-{id}` and `/shop/product/AI-{id}` once printed |

`POST /generations/{id}/print` answers `{sku, product_url, created}`; the status code
carries the idempotency (201 created now, 200 already existed).

`POST /events/order-paid` answers 200 for every business case — `{"status":
"processed", "own_designs": n, "purchases": m}`, `already_processed` for a re-delivered
`event_id`, `skipped` without a `customer_email` — so a non-2xx can only mean an
infrastructure fault; the outbox retries the whole event (to production and
notifications too) on any non-2xx.

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| DATABASE_URL | `designs_svc` connection string with `search_path=designs_schema` | required |
| JWT_SECRET | Shared HS256 secret (bearer + service tokens) | required |
| ROOT_PATH | Path prefix behind the ingress (`/api/designs` in Kubernetes) | `` |
| CORS_ORIGINS | Comma-separated allowed origins | `http://localhost:3000` |
| IMAGE_PROVIDER | `fake` (Pillow placeholder, no key) \| `openai` \| `replicate`; a real provider without its key falls back to `fake` with a warning | `fake` |
| OPENAI_API_KEY | Used by the Images API provider and the chat summariser | `` |
| OPENAI_IMAGE_MODEL | Images API model | `gpt-image-1.5` |
| OPENAI_IMAGE_QUALITY | Images API quality (`low` \| `medium` \| `high`) | `medium` |
| OPENAI_CHAT_MODEL | Chat model for the style summary | `gpt-4o-mini` |
| OPENAI_BASE_URL | Images + chat base URL | `https://api.openai.com/v1` |
| REPLICATE_API_TOKEN | Replicate token | `` |
| REPLICATE_MODEL | Replicate model (`/models/{model}/predictions`) | `black-forest-labs/flux-schnell` |
| REPLICATE_BASE_URL | Replicate base URL | `https://api.replicate.com/v1` |
| STORAGE_BACKEND | `local` \| `s3` | `local` |
| DESIGNS_STORAGE_DIR | Directory for `local` (the compose `designs-data` volume) | `/data/images` |
| DESIGNS_S3_BUCKET | Bucket for `s3` | `` |
| DESIGNS_S3_REGION | Bucket region (falls back to `AWS_REGION`) | `eu-north-1` |
| DESIGNS_PUBLIC_URL_PREFIX | Prefix of `image_url` as the shop sees it | `/api/designs/images` |
| CATALOG_SERVICE_URL | Catalog base URL for `POST /internal/products` | `http://catalog:8000` |
| INVENTORY_SERVICE_URL | Inventory base URL for `POST /internal/stock` | `http://inventory:8000` |
| AI_DAILY_QUOTA | Generations per customer per UTC day; `0` = unlimited; the owner role is exempt | `10` |
| AI_POSTER_BASE_PRICE | A3 price of a printed design; A4/A2/A1 are −5 / +10 / +25 | `29.99` |
| AI_POSTER_STOCK | Virtual stock created per variant at print time | `1000` |
| DESIGNS_WORKER_POLL_INTERVAL | Seconds between worker polls when the queue is empty | `1.0` |
| DESIGNS_MAX_ATTEMPTS | Provider attempts before a generation is `failed` | `3` |
| CB_FAILURE_THRESHOLD | Circuit-breaker failures before it opens (provider, catalog, inventory) | `5` |
| CB_RECOVERY_TIMEOUT | Seconds an open breaker waits before a trial call | `30` |
| SERVICE_NAME | Service name used in logs and metrics labels | `designs` |
| LOG_LEVEL | Logging level | `INFO` |

## Local Development

```bash
cd services/designs
pip install -r requirements.txt
uvicorn main:app --reload --port 8010
```

Under docker-compose the service is `designs` on host port **8010**, migrated by the
`designs-migrate` sidecar (`alembic upgrade head`, a separate image — rebuild both
when the service changes) and writing images to the `designs-data` volume. The
frontend proxies `/api/designs/` to it (nginx in the image, vite in dev), and the
compose default `IMAGE_PROVIDER=fake` needs no key.

The fake provider has three prompt hooks so every path is demoable without a key:

| Prompt contains | Behaviour |
|-----------------|-----------|
| `[reject]` | `PromptRejected` → the generation ends `failed` with "The provider's safety filter rejected this prompt" |
| `[fail]` | `ProviderError` on every attempt → re-queued with backoff, `failed` after `DESIGNS_MAX_ATTEMPTS` |
| `[slow]` | The render takes 3 s (watch the `generating` state) |

To generate with OpenAI, put `IMAGE_PROVIDER=openai` and your `OPENAI_API_KEY` in the
gitignored `.env` (optionally `OPENAI_IMAGE_QUALITY=low`), then
`docker compose up -d --no-deps designs`; the startup log names the active provider,
its parameters and the summariser. Remove the line and recreate the container to go
back to `fake`. Verified live in this repo: one `gpt-image-1.5` / `low` poster was
715 output tokens (≈ $0.02) and took 12.1 s; one `gpt-4o-mini` style summary was
93 tokens.

```bash
TOKEN=$(curl -s -X POST localhost:8001/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@postershop.com","password":"admin1234"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s -X POST localhost:8010/generations -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"prompt":"a minimalist lighthouse at dusk"}'
# 202 {"id":1,"status":"queued",...}  -> poll GET /generations/1 until "ready"
curl -s -X POST localhost:8010/generations/1/print -H "Authorization: Bearer $TOKEN"
# 201 {"sku":"AI-1","product_url":"/shop/product/AI-1","created":true}
```

## Image Providers

The provider is selected at startup by `IMAGE_PROVIDER` (`providers.py`,
`get_image_provider()`); every provider implements the `ImageProvider` ABC
(`generate(prompt, user_ref) -> PNG bytes`, `name`, `params()`). All produce a
portrait 2:3 PNG — `1024x1536` on OpenAI and fake, the `2:3` / `1 MP` preset on
Replicate (D-17). There is no aspect picker and no upscaling: the print uses the
model's native output.

Every provider raises one of three exceptions, and the worker maps them the same way:

| Exception | Meaning | Worker outcome |
|-----------|---------|----------------|
| `PromptRejected` | Content-policy refusal | `failed` with the provider's reason shown to the customer (D-15); does not trip the breaker |
| `ProviderConfigError` | Wrong key / model / request (4xx other than rate limits) | `failed` with a generic reason (the detail stays in the log); does not trip the breaker |
| `ProviderError` | 429, 5xx, network, timeout | Re-queued with backoff; counts towards the breaker |

### FakeProvider (default)

Paints a deterministic poster with Pillow — the prompt on a colour derived from its
hash — in ~60 ms. Requires no key, which makes it the right choice for
docker-compose, the integration tests and demos; the `[reject]` / `[fail]` / `[slow]`
hooks above live here.

### OpenAIImagesProvider

`POST {OPENAI_BASE_URL}/images/generations` with `{model, prompt, n: 1,
size: "1024x1536", quality, output_format: "png", moderation: "auto", user}`, 180 s
timeout, the PNG decoded from `data[0].b64_json`. Errors are classified by
`error.code` / `error.type` first — `moderation_blocked`, `content_policy_violation`
and `image_generation_user_error` are `PromptRejected` — then by status class (429
and 5xx are `ProviderError`, other 4xx `ProviderConfigError`), so a wrong model
never reads as a refusal and never trips the breaker.

### ReplicateProvider

`POST /models/{model}/predictions` with `Prefer: wait=60`, then polls every 2 s to a
180 s deadline and downloads `output[0]`; an `NSFW` failure is `PromptRejected`. Built
and unit-tested against `httpx.MockTransport` only — no Replicate token exists in this
project (D-10) — and kept behind the same seam so the provider comparison stays honest.

## Worker

One asyncio task per replica, started in `lifespan` (`worker.py`):

1. Claim the oldest due row atomically — `UPDATE … WHERE id = (SELECT … WHERE
   status = 'queued' AND (retry_after IS NULL OR retry_after <= now()) ORDER BY
   created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING …` — flipping it to
   `generating` and consuming an attempt in the same statement, then commit
2. If the row is personalised, fetch (or lazily rebuild) the style summary and
   compose `effective_prompt`
3. Call the provider through the `image_provider` circuit breaker with **no DB
   session held**
4. Store the PNG, then persist the outcome in a fresh session

Retries: `DESIGNS_MAX_ATTEMPTS` (3) attempts, waiting 5 s / 30 s / 120 s after
attempts 1 / 2 / 3. An **open circuit** hands the attempt back (`attempts − 1`) and
re-queues the row at `now + CB_RECOVERY_TIMEOUT`, so an outage can never burn a
generation's last attempt into a failure; `POST /generations` keeps accepting — the
queue is the buffer (D-04). The breaker is `services/orders/circuit_breaker.py` copied
with `PromptRejected`, `ProviderConfigError`, `CatalogRejectedError` and
`InventoryRejectedError` whitelisted as business errors.

## Storage

Images live behind the `Storage` ABC (`storage.py`, `get_storage()`), keyed by
`new_image_key()` — 32 hex characters + `.png`, validated by `KEY_RE` on both put and
get so a malformed key can never reach the filesystem or S3:

- **LocalStorage** (`STORAGE_BACKEND=local`) — files under `DESIGNS_STORAGE_DIR`; in
  compose that is the `designs-data` named volume. In Kubernetes the chart mounts an
  `emptyDir` there, so images are lost on pod restart until S3 is configured
- **S3Storage** (`STORAGE_BACKEND=s3`) — `DESIGNS_S3_BUCKET` / `DESIGNS_S3_REGION`,
  objects written with `Cache-Control: public, max-age=31536000, immutable`, credentials
  from IRSA (the chart's `serviceAccount`; `deploy/designs-setup.sh` creates the private
  bucket, the least-privilege policy and the ServiceAccount). The bucket stays fully
  private because the service proxies every image through `GET /images/{key}`

Keys never change, so `GET /images/{key}` answers with the same immutable
`Cache-Control` plus an `ETag`. Resolution is whatever the provider returned
(`1024x1536` on OpenAI and fake, ~832x1216 on flux-schnell) — upscaling for large
print formats is documented future work.

## Print This

`POST /generations/{id}/print` (`printing.py`) creates, through service-token calls,
one catalog family and its stock:

| What | Where | Value |
|------|-------|-------|
| Motif SKU | catalog `POST /internal/products` | `AI-{id}`, `category: "Custom"`, `listed: false`, `image_url` = the design's `image_url`, name `Custom: <prompt, 60 chars>` |
| Variants | same call | `AI-{id}-A4` / `-A3` / `-A2` / `-A1` priced `AI_POSTER_BASE_PRICE` −5 / 0 / +10 / +25 (the catalog seed ladder: 24.99 / 29.99 / 39.99 / 54.99 by default) |
| Virtual stock | inventory `POST /internal/stock` | `AI_POSTER_STOCK` (1000) units per variant, so orders' unconditional reservation succeeds |
| Own row | `generations.catalog_product_sku` | `AI-{id}` — written last |

The family is **unlisted** (D-13): `GET /products` and `GET /categories` hide it, while
`GET /products/{sku}`, the cart and `/internal/resolve-prices` work as for any poster,
so the shop's product page, size picker, checkout (Stripe or escrow), production and
notifications need no change. The orchestration order catalog → inventory → own row and
the idempotency of both internal endpoints mean a 503 half-way leaves
`catalog_product_sku` NULL and the customer's retry completes only the missing half.
The variant SKU is recognisable from an ORDER_PAID item alone (`generation_id_from_sku`).

## Memory

Three tiers, all per customer e-mail (the JWT `sub`):

1. **History** — every generation, newest first (`GET /generations`), with
   `purchased_at` and `product_url` once bought / printed
2. **Saved prompts** — `saved_prompts` CRUD, reused from the studio page
3. **Style profile** (`style_profile.py`, `summarizer.py`, D-16) — a 1–2 sentence
   summary of the customer's last 20 non-failed prompts and the names of their last 20
   purchases (deduplicated). With `IMAGE_PROVIDER=openai` and a key it comes from
   `OPENAI_CHAT_MODEL` (`max_completion_tokens: 120`); in fake mode or without a key
   it is the deterministic top-6 keyword summary ("You lean towards: …"), so compose
   needs no key. The profile is refreshed **lazily**: ORDER_PAID marks it `stale`, and
   the next personalised generation (in the worker) or `POST /me/style-profile/refresh`
   rebuilds it; a summariser outage keeps the previous summary and leaves `stale: true`
   for the next attempt, and can never fail a generation. With "Personalise" ticked the
   worker sends `prompt + "\n\nStyle notes: " + summary` and records it as
   `effective_prompt`.

## Events Consumed

| Event | Emitted by | Effect |
|-------|-----------|--------|
| ORDER_PAID | Orders — payment confirmed (Stripe webhook, escrow verify, owner `/pay`) | For each item: an own `AI-{id}-{size}` SKU stamps `purchased_at` on that generation (once); every item — own or ordinary poster — becomes a `purchases` row; the style profile is marked stale; the `event_id` is recorded |

`ORDER_PAID` fans out to production, notifications **and** this service
(`EVENT_SUBSCRIBERS` in `services/orders/outbox.py`); the other three event types are
not subscribed. The handler is DB-only and answers within the outbox's 10 s budget —
it never calls a provider. See [docs/EVENT_CATALOG.md](../../docs/EVENT_CATALOG.md).

## Idempotency

- **Events** — durable, keyed by the outbox envelope's `event_id` in
  `designs_schema.processed_events` (`INSERT … ON CONFLICT DO NOTHING`, committed with
  the purchases); a re-delivery answers `already_processed` and touches nothing. If the
  commit hits an `IntegrityError` (purchases left by a crashed earlier delivery) the
  handler rolls back and records the event alone so the outbox stops retrying
- **Print** — a second `POST /generations/{id}/print` answers 200 with the same
  payload; catalog `POST /internal/products` answers 200 for an existing SKU and
  inventory `POST /internal/stock` skips existing SKUs, so a partial failure is retryable
- **Worker** — the `FOR UPDATE SKIP LOCKED` claim means two replicas never generate
  the same row twice

## Metrics

| Metric | Labels | Description |
|--------|--------|-------------|
| designs_generations_total | provider, status | Generations finished, by provider and final status (`ready` / `failed`) |
| designs_provider_latency_seconds | provider | Image provider call latency (buckets 1 s … 180 s) |
| designs_queue_depth | - | Rows in status `queued` (refreshed when a poll finds nothing to claim) |
| circuit_breaker_state_transitions_total | service, from_state, to_state | Breaker transitions for `image_provider`, `catalog`, `inventory` — same name and labels as orders' counter, so the existing Grafana panel picks them up |

Plus the standard `http_requests_total` / `http_request_duration_seconds`. Scraped via
the ServiceMonitor in `deploy/monitoring/servicemonitors.yaml`.

## Dependencies

- **Catalog Service**: `POST /internal/products` creates the unlisted family (service token)
- **Inventory Service**: `POST /internal/stock` creates the virtual stock rows (service token)
- **Orders Service**: event producer — its outbox worker calls `/events/order-paid`
- **OpenAI** (`IMAGE_PROVIDER=openai`): Images API for posters, Chat Completions for the style summary
- **Replicate** (`IMAGE_PROVIDER=replicate`): predictions API — unit-tested only
- **AWS S3** (`STORAGE_BACKEND=s3`): image storage via IRSA in Kubernetes
