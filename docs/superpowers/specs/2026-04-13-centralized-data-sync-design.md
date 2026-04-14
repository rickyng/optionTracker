---
name: centralized-data-sync
description: Centralize all external data fetching in Settings tab with 24h cache TTL and global sync status banner
---

# Centralized Data Sync Design

## Overview

Currently, external API calls are scattered across multiple dashboard tabs:
- Overview tab auto-triggers Yahoo Finance price refresh on load
- Settings tab triggers IBKR Flex sync manually
- Screener tab triggers Yahoo Finance options chain scan on-demand

This redesign centralizes all data fetching in the Settings tab. All external data (IBKR positions, stock prices, earnings dates, screener options chains) is cached in the database with a 24-hour TTL. Other tabs become pure DB reads for instant response.

## Goals

1. **Eliminate wait times** — Other tabs respond instantly from cache
2. **Single sync point** — All external data fetched in one coordinated operation
3. **Clear sync status** — Global banner shows sync progress/freshness across all tabs
4. **Screener as cache reader** — Screener tab filters cached results, no on-demand API calls

## Design Sections

### Section 1: Settings Tab — Sync UI

**Layout changes:**
- Replace "Sync All Accounts" button with a **"Sync All Data"** button
- `dcc.Interval` fires once on Settings tab load to check cache staleness
- If any cached data is >24h old, auto-trigger the sync pipeline
- Show last sync timestamp: "Last synced: 2 hours ago"
- Remove old per-account sync buttons (unified sync handles all enabled accounts)

**Sync pipeline sequence:**
1. IBKR Flex — download positions for all enabled accounts
2. Stock prices — fetch Yahoo prices for underlyings in positions + watchlist
3. Earnings dates — fetch Yahoo earnings for screener watchlist tickers only
4. Screener options chains — fetch options chains for screener watchlist

Each step runs only if its cached data is stale (>24h). Fresh steps are skipped.

**Sync status object (dcc.Store):**
```python
{
  "status": "syncing" | "retrying" | "complete" | "error",
  "current_step": 1,  # 1-4
  "step_name": "IBKR Flex",
  "retry_count": 0,
  "last_sync": "2026-04-13T10:30:00Z",
  "errors": []
}
```

### Section 2: Global Banner — Sync Status Across Tabs

**Placement:** Thin banner above tab bar, always visible.

**Three states:**

| State | Display |
|-------|---------|
| Idle | "Data synced 2h ago" + refresh icon (links to Settings) |
| Syncing | "Syncing stock prices... (2/4)" + spinner |
| Error | "Sync failed: IBKR timeout. Retry?" (links to Settings) |

**Implementation:**
- Shared `dcc.Store` holds sync status object
- Single callback renders banner based on status
- `dcc.Interval` polls `GET /api/sync/status` every 3s when `status == "syncing"`
- Interval disabled otherwise to avoid unnecessary updates

### Section 3: Backend — Sync Pipeline & Caching

**New API endpoint:** `POST /api/sync/all`

- Accepts `force` boolean to skip cache check
- Returns job ID immediately (async, non-blocking)
- Background job runs pipeline

**Sync pipeline pseudocode:**
```
sync_job(job_id):
  1. status: "syncing", step=1, "IBKR Flex"
  2. For each enabled account:
     - Flex SendRequest → poll GetStatement → parse CSV
     - Upsert positions to OpenOption
  3. status: step=2, "Stock prices"
  4. Collect underlyings: OpenOption.underlying + ScreenerWatchlist.symbol
  5. Batch fetch prices via yahoo_data_service → MarketPrice
  6. status: step=3, "Earnings dates"
  7. Collect underlyings: ScreenerWatchlist.symbol ONLY
  8. Fetch earnings → EarningsDate
  9. status: step=4, "Screener options chains"
  10. For each watchlist symbol:
     - Fetch options chain via yfinance
     - Store in ScreenerResult
  11. status: "complete", last_sync=now()
```

**Cache TTL tracking (Metadata table):**
- `sync_last_run`: ISO timestamp of last successful full sync
- `sync_ibkr_last_run`
- `sync_prices_last_run`
- `sync_earnings_last_run`
- `sync_screener_last_run`

Each step checks its timestamp. Skip if `now() - last_run < 24h` and `force=false`.

**Job storage:**
- In-memory dict (single-worker app)
- On restart, in-progress jobs are abandoned

### Section 4: Other Tabs — Pure Cache Reads

**Overview tab changes:**
- Remove auto-trigger price refresh on load
- Remove "Refresh Prices" button
- Read prices from MarketPrice directly
- Add "data age" badge: "Prices: 2h old"

**Positions, Risk, Expiration tabs:**
- No changes needed (already pure DB reads)

**Screener tab changes:**
- Remove on-demand "Scan" button
- Read results from ScreenerResult table
- Keep filter controls (client-side filters on cached data)
- Remove watchlist display (moved to Settings)
- Add "data age" badge: "Scan: 3h old" + link to Settings

**Stale data prompt:**
- If tab data >24h old: "Data is 1+ day old. Sync in Settings tab." (non-blocking)

### Section 5: Settings Tab — Screener Watchlist Management

**New section: "Screener Watchlist"**
- Text input + "Add" button for ticker symbols
- Tag-style display with "Remove" X button per tag
- Changes take effect on next sync (no immediate API calls)

**Settings tab layout (top to bottom):**
1. Sync All Data — button + timestamp + staleness indicators
2. Account Management — existing (unchanged)
3. Screener Watchlist — ticker management (moved from Screener)

**Screener tab (after move):**
- Watchlist tags removed
- Scan button removed
- Retains: results table, detail panel, filter controls
- All data from ScreenerResult, client-side filtered

### Section 6: Error Handling

**Retry policy:**

| Failure Type | Behavior |
|-------------|----------|
| Rate limit (429) | Wait 60s, auto-retry same step, max 3 retries |
| Timeout | Retry immediately once, then fail |
| Auth error (IBKR) | Fail immediately, no retry |
| Network error | Wait 30s, auto-retry, max 3 retries |

**Status during retry:**
```
"step_2_prices" → "retrying" (1/3) → "retrying" (2/3) → "step_3_earnings" (success)
```

**Retry exhausted:**
- Status: `"error"` with `failed_step` + `error_message`
- Banner: "Sync failed at Stock prices after 3 retries: rate limit. Retry?"
- Completed steps remain cached

**Partial data:**
- If step 4 fails, steps 1-3 still provide fresh positions/prices
- Other tabs work; screener shows stale or "No data"

## Out of Scope

- Multi-worker deployment (job storage is in-memory)
- Real-time price updates (cache TTL is 24h)
- Per-account granular sync (one unified sync for all enabled accounts)
- Background scheduled sync (only triggered on Settings tab load)

## Dependencies

- Existing: Metadata table, MarketPrice, EarningsDate, ScreenerResult tables
- Existing: flex_service, yahoo_data_service, screener_service
- New: sync_service.py to orchestrate pipeline
- New: GET /api/sync/status endpoint
- New: POST /api/sync/all endpoint

## Success Criteria

1. Sync All Data button triggers 4-step pipeline with progress feedback
2. Global banner shows sync status across all tabs
3. Overview tab loads instantly with cached prices (no API calls)
4. Screener tab filters cached results (no on-demand scan)
5. Settings tab manages screener watchlist
6. Auto-refresh triggers when Settings tab loads and detects stale cache
7. Automatic retry on rate limit/timeout/network errors