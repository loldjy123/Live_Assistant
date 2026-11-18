# Live book inventory and pricing

This version inventories **books only**: book counts, sourced replacement/used prices and calculated totals. Shelving, furniture, art and other non-book detections are discarded by the backend. Measurement features and tools have been removed. This intentionally narrows the original assignment's scope.

## Publish the live app

The source repository is [loldjy123/Live_Assistant](https://github.com/loldjy123/Live_Assistant).

GitHub Pages serves HTML/JavaScript but cannot run Python. The Live API, background research and report generation need a Python web service. This repo includes a Render Blueprint for that backend and can also serve the entire website from the same service.

### Recommended: host the whole app on Render

[Deploy to Render](https://render.com/deploy?repo=https://github.com/loldjy123/Live_Assistant)

1. Open the deploy link and connect this GitHub repository to your Render account.
2. Enter `GOOGLE_API_KEY` in Render's secret environment-variable field. Do not put it in GitHub or `site-config.js`.
3. Create the service described by `render.yaml`. It installs the Python requirements and runs `python main.py` on Render's `PORT`.
4. Open the HTTPS URL Render provides. Both the page and `/ws` use that domain; the app works without running a server on your laptop.

The Blueprint requests a free instance, not a paid disk. Provider eligibility/account requirements may apply. Free instances can sleep; recordings/reports in `/tmp/library-claims` are temporary and can disappear on restart or redeploy. Download your report promptly. For durable storage, choose an appropriate storage service and set `CLAIMS_DIR` to a persistent writable location. This prototype does not include per-user sign-in; monitor provider quotas before sharing an open API-backed demo widely.

### Optional: use GitHub Pages for the frontend

After the Python service is running:

1. In GitHub Settings → Pages, choose **GitHub Actions** as the source.
2. In Settings → Secrets and variables → Actions → Variables, set **`BACKEND_URL`** to the Render HTTPS URL (this URL is not a secret). Never add the Google key to the frontend configuration.
3. Run **Publish frontend to GitHub Pages** from the Actions tab, or push a new commit.

The workflow packages only `index.html`, `app.js`, `processor.js` and `site-config.js`. It is skipped while `BACKEND_URL` is empty. Once deployed, the Pages URL is `https://loldjy123.github.io/Live_Assistant/`. Its live traffic and report downloads go to the configured Python host. A Pages frontend without a backend shows that the live service is not connected; it cannot perform a sweep by itself.

`site-config.js` is the editable browser configuration. Leave its backend URL empty for a Python host serving its own frontend; the app automatically uses the current domain and `wss://` under HTTPS. For a separate static host, provide the deployed backend HTTPS URL. The Pages build injects `BACKEND_URL` into this file without putting secrets in the browser.

The server accepts its own origin plus explicitly configured `ALLOWED_ORIGINS` (the provided value includes `https://loldjy123.github.io`). Other frontend domains must be added explicitly. HTTP, health checks, downloads and WebSockets share a single port. `HOST`, `PORT`, `PUBLIC_URL` and `CLAIMS_DIR` are configurable environment variables.

## Run locally (optional)

## Open the app (macOS)

Double-click **`Open Library.command`** in this folder. It starts the Python server in the background, waits until HTTP and WebSocket handling is ready, and opens http://localhost:8080. If this project's server is already running, it reuses it instead of starting a duplicate. You do not need to run `main.py` yourself.

Double-click **`Stop Library.command`** to stop this project's server. Server startup/error logs are saved in the ignored `.server.log`. The launcher does not install a login/background service or change macOS file associations. If an older manually started server occupies the ports, stop it once in PyCharm before using the launcher.

Opening an HTML file directly in a browser cannot execute Python. The file-open page therefore points to the launcher; use the launcher as the app's entry point. The camera/API features run from the HTTP page it opens.

## First-time setup / manual run

Use Python 3.11+ (tested with 3.14).

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

If `.env` does not already exist, copy `.env.example` to `.env` and set `GOOGLE_API_KEY`. Keep existing `.env` values; never commit the file.

```bash
.venv/bin/python main.py
```

Open the HTTP address printed by the local server, enter country and ISO currency (e.g. United States / USD), then Start sweep. Stop any older server before restarting. PyCharm's local HTML preview can also find the default app server on port 8080; the server must be running. Direct file opening still shows launcher instructions.

Allow camera and microphone access. Speak naturally while sweeping the books. The browser sends audio about every 100 ms and a high-resolution JPEG every three seconds. Click **Finish sweep** to stop capture and prepare the JSON and HTML report; keep the page open until links appear. A spoken finish request asks for button confirmation. Voice interruptions clear queued speaker audio.

The server listens on `HOST` and `PORT` (defaults: `0.0.0.0:8080`), suitable for a Python web host. Camera/audio/images and research queries are sent to Google's APIs; API access and quota are required. Actual camera resolution depends on the device. Use an HTTPS host for public camera/microphone access.

## Code and prompts

- `main.py`: single-port HTTP/WebSocket server, Live session and tools.
- `prompts.py`: `SYSTEM_INSTRUCTION`, book identification, search and report prompts.
- `claim.py`: saved book inventory, evidence, corrections, counts and Decimal-based totals.
- `pipeline.py`: background image identification, grounded price search/extraction and finalization.
- `claim.py` also contains `build_output_packet()`, the mapping to the final output JSON.
- `launcher.py`: starts/reuses the local server, checks readiness, opens the browser and supports `--stop`.
- `app.js` / `index.html`: camera, books-only table, count and replacement/used totals.

Each observation represents one physical book. Equal titles are not automatically merged. Confirmed/possible duplicates and user-excluded books are omitted from the count; appraisal-only books remain in the count but are excluded from price totals. The model's physical tracking and count accuracy still require independent validation.

Use voice corrections to update a book's title, author, publisher, edition, description, shelf, exclusion or duplicate target. The Live agent finds the stable book ID through `get_inventory` and passes `book_id` to `record_correction`; ambiguous targets require clarification. Corrections invalidate stale in-flight research and retain the user's statement in the event history.

## Customize the output JSON

**`output_schema.json`** is the editable JSON Schema for this structure. The app reads it and validates every finished JSON before publishing report links. The only top-level keys are `sweep`, `books` and `totals`. The public report and JSON contain no review queue, and the books list omits unidentified titles. There are no item totals, non-book inventory or internal processing flags. The screenshot's `spine_height_cm`, `spine_thickness_cm` and `shelf_run_m` fields remain `null` because measurement features are disabled; they are not zero estimates.

Edit descriptions, constraints and optional-field rules in the schema as needed. If you rename fields or require new ones, also update the mapping in **`claim.py`** to supply them. The schema validates output; it does not automatically rename fields or generate data. Internal review details remain in `inventory.json` for debugging and capture guidance. New model-extracted fields also require matching changes to `BookObservation`/`BookIdentification` in `claim.py` and the identification prompt. Python, not an LLM, computes the monetary totals. Schema validation failures appear as a report error rather than publishing malformed output.

Example totals:

```json
{
  "book_count": 3,
  "books_identified": 2,
  "books_unidentified": 1,
  "shelf_run_m": null,
  "books_replacement_cost": 19.99,
  "books_used_value": 8.50,
  "excluded_from_totals": 2
}
```

Each monetary total includes only books with that supported valuation. Price amounts use the currency from `sweep.currency`. Replacement entries expose amount/source/URL/retrieval date/converted; used entries expose amount/source/URL/retrieval date/condition. Internal quotes and matching diagnostics remain in saved research rather than the public JSON. Unknown prices are `null`, never zero estimates. `excluded_from_totals` counts books excluded from the replacement total; used-price eligibility is separate. All public amounts use `sweep.currency`; raw internal records also retain the price currency.

## Pricing and saved files

Research uses Google Search grounding followed by structured price extraction. Acceptance requires a source-linked text segment, a matching exact quote containing the amount, an explicit ISO currency code and matching extracted locale. It does not independently verify retailer stock, edition or condition. Ambiguous currency symbols, ranges, unsupported conversions and missing evidence stay unpriced. The first accepted listing per valuation is retained; it is not an average of market listings.

Rare/signed/first-edition/antiquarian books and listings above `APPRAISAL_THRESHOLD` (default 500 in the sweep currency) require appraisal. Totals exclude appraisal, excluded, duplicate and unpriced valuations. Source URLs, retrieval dates and conditions are saved with prices.

Each sweep writes `claims/<sweep-id>/`:

- `frames/`: JPEG evidence; timestamps/hashes are in `inventory.json`.
- `inventory.json`: internal books, processing state, corrections and usage metrics.
- `events.jsonl`: user transcript fragments and recorded operations.
- `research/`: identification outputs and search text with linked evidence.
- `claim_packet.json`: validated public output matching `output_schema.json`.
- `report.html`: human-readable book report built from the same output.

Existing saved sweeps are not migrated. Start a new sweep for the books-only format. The internal inventory retains diagnostics; the public JSON exposes only the documented schema.

## Limits and checks

Identification is model-based; completeness, count accuracy, title/edition matching and price accuracy are unverified on a real-room ground-truth dataset. Fast capture can outrun the bounded image queue; skipped frames remain saved and flagged. Background processing has a 210-second deadline, followed by a report request with a 55-second timeout. Unknowns and unfinished work enter the review queue.

There is no resumed-sweep UI, multi-user database or production queue. Disconnecting before Finish saves a partial inventory; explicitly requested finalization continues after browser disconnection. Exact provider cost remains unknown; token usage and stage latency are retained internally.

```bash
.venv/bin/python -m unittest discover -s tests -v
node tests/test_audio.js
node --check app.js
```

Tests cover non-book rejection, evidence persistence, corrections, duplicate counts, decimal totals, missing prices, source checks, stale research, schema enforcement, final artifacts, HTTP isolation, WebSocket origins and audio interruptions. No live API call is needed for these tests. Launcher tests cover reuse, readiness, project identity and the no-browser option. A local launch/reuse/stop smoke check can run without starting a Gemini session using `.venv/bin/python launcher.py --no-browser`, then `--stop`.

## Improving book coverage

The live list and report show only books with readable titles. `book_count` still counts all tracked physical detections, `books_identified` counts the named ones, and `books_unidentified` counts unreadable detections omitted from the list. The UI labels identified versus detected counts so filtering does not imply complete identification. Unknown-title detections never contribute to price totals.

For capture, move shelf by shelf, keep the camera facing the spines, use even lighting, overlap neighboring views and pause until identification updates. Ask for a closer view while still at an unreadable section. Independently count the physical books on each shelf and compare that count and the visible titles with the app. Matching counts alone do not prove that the same physical books were found.

This prototype cannot guarantee every book is detected. It samples one frame every three seconds and may skip processing saved frames if the bounded queue fills. A dedicated spine detector, stronger cross-frame tracking and processing every saved view would improve coverage; these are not currently implemented. Hiding unidentified titles is a display filter, not an accuracy improvement.
