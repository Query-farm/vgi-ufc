<p align="center">
  <a href="https://query.farm/vgi/">
    <img src="https://raw.githubusercontent.com/Query-farm/vgi-kalshi/main/docs/vgi-logo.png" alt="Vector Gateway Interface logo" width="320">
  </a>
</p>

<h1 align="center">vgi-ufc</h1>

<p align="center">
  UFC rankings, fight cards, results, and round-by-round fight statistics as ordinary DuckDB tables.<br>
  A <strong>read-only</strong> <a href="https://query.farm/vgi/">VGI</a> worker, built by <a href="https://query.farm">🚜 Query.Farm</a>
</p>

<p align="center">
  <a href="https://github.com/Query-farm/vgi-ufc/actions/workflows/ci.yml"><img src="https://github.com/Query-farm/vgi-ufc/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/python-3.13%2B-3776AB.svg" alt="Python 3.13+">
  <a href="https://query.farm/vgi/"><img src="https://img.shields.io/badge/VGI-read--only-6f42c1.svg" alt="Read-only VGI worker"></a>
</p>

---

`vgi-ufc` fetches mixed martial arts data on demand and reformats it as typed
Arrow data for Haybarn SQL. It draws on UFC's official live-data feed for fight
cards, results, judges' scorecards, and per-round statistics, on ufc.com for the
official rankings, and on ESPN for event calendars (UFC, PFL, and Bellator) and
fighter careers. It requires no credentials and does not rehost or persist any
dataset.

## Quick start

The worker is not published to PyPI. `uvx` runs the tagged release straight from
GitHub and caches it after the first use:

```bash
uvx --from git+https://github.com/Query-farm/vgi-ufc@v0.2.0 vgi-ufc --help
```

Launch Haybarn with the catalog pre-attached:

```bash
uvx haybarn-cli \
  -cmd "INSTALL vgi FROM community; LOAD vgi; ATTACH 'ufc' (TYPE vgi, LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-ufc@v0.2.0 vgi-ufc');" \
  :memory:
```

Or attach it in an existing Haybarn session:

```sql
INSTALL vgi FROM community;
LOAD vgi;
ATTACH 'ufc' (
  TYPE vgi,
  LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-ufc@v0.2.0 vgi-ufc'
);
```

For source development, run `uv lock --check --no-sources`, then
`uv sync --no-sources` and `uv run --no-sources vgi-ufc`.
The lockfile resolves all dependencies from package registries and does not
require a sibling checkout.

## Catalog surface

The catalog exposes three argument-free current tables and twelve
parameterized table functions:

| Kind | Objects | Source |
| --- | --- | --- |
| Current | `current_rankings`, `upcoming_events`, `current_season_events` | ufc.com, ESPN |
| Events (UFC, PFL, Bellator) | `events()`, `event_bouts()` | ESPN |
| Official UFC cards and results | `feed_events()`, `fight_card()`, `card_fighters()`, `fight_results()`, `fight_scorecards()` | UFC live-data feed |
| Official UFC fight statistics | `fight_stats()`, `fight_round_stats()` | UFC live-data feed |
| Fighters | `fighter()`, `fighter_fight_history()`, `fighter_career_stats()` | ESPN |

### Two id systems

ESPN and UFC's live-data feed number things independently, and their ids never
join:

- **ESPN ids**: `event_id` from `events()`, `upcoming_events`, and
  `current_season_events`, and athlete ids (`fighter1_id`, `fighter2_id`,
  `winner_id`) from `event_bouts()`. Use them with `event_bouts()` and the
  `fighter*()` functions.
- **UFC feed ids**: sequential integers for events and fights. They cannot be
  searched by name, so `feed_events(first_id, last_id)` probes a range of up to
  100 ids and lists the events it finds. Some anchors: `1252` is UFC 315
  (2025-05-10), `1291` is the 2025-11-08 Fight Night, `1294` is UFC 324
  (2026-01-24), and `1343` is the 2026-11-07 Fight Night. Ids are roughly but
  not strictly chronological. `fight_card()` and `fight_results()` return the
  `fight_id` values used by `fight_stats()`, `fight_round_stats()`, and
  `fight_scorecards()`.

## Usage

### Rankings and schedule

`current_rankings` holds the official ufc.com rankings. Each weight class lists
its champion as rank `0` followed by contenders `1`-`15`; the pound-for-pound
lists have ranks `1`-`15` only. ufc.com publishes ties, so two fighters can
share a rank.

```sql
-- Every current champion
SELECT division, fighter_name, is_interim_champion
FROM ufc.main.current_rankings
WHERE is_champion
ORDER BY division_order;

-- The lightweight top 15 with movement since the last update
SELECT rank, fighter_name, rank_change, newly_ranked
FROM ufc.main.current_rankings
WHERE division = 'Lightweight'
ORDER BY rank;

-- What's next
SELECT event_name, start_time, venue, city, bout_count
FROM ufc.main.upcoming_events
ORDER BY start_time;
```

ESPN's own MMA rankings are stale (they still list long-departed champions), so
this worker never reads them.

### Events and bouts from ESPN

```sql
-- The 2025 UFC calendar
SELECT event_id, event_name, start_time, city, country, bout_count
FROM ufc.main.events(season := 2025)
ORDER BY start_time;

-- PFL in 2026 (Bellator events run through 2024)
SELECT event_id, event_name, start_time, event_state
FROM ufc.main.events(season := 2026, league := 'pfl')
ORDER BY start_time;

-- UFC 324 results, main event first
SELECT match_number, weight_class, fighter1_name, fighter2_name,
       winner_name, method, method_detail, ending_round, ending_time
FROM ufc.main.event_bouts(600057024)
ORDER BY match_number;
```

In `event_bouts()`, `judges_scores` lists each judge's total as
fighter1-fighter2 (not winner first), and `fighter1_record` and
`fighter2_record` are the fighters' current ESPN records, not their records on
fight night.

### Official UFC cards, results, and scorecards

```sql
-- Find feed ids: UFC 324 is in this window
SELECT event_id, event_name, start_time, status, main_event
FROM ufc.main.feed_events(1290, 1300)
ORDER BY start_time;

-- Results of the 2025-11-08 Fight Night, in card order
SELECT fight_order, winner_name, loser_name, method,
       ending_round, ending_time, judges_scores, performance_bonus_names
FROM ufc.main.fight_results(1291)
ORDER BY fight_order;

-- Who had the longest reach on that card?
SELECT fighter_name, reach_in, height_in, stance
FROM ufc.main.card_fighters(1291)
ORDER BY reach_in DESC
LIMIT 3;

-- Ranked fighters on that card (feed and ufc.com share ufc_athlete_url)
SELECT c.fighter_name, r.division, r.rank
FROM ufc.main.card_fighters(1343) AS c
JOIN ufc.main.current_rankings AS r USING (ufc_athlete_url)
ORDER BY r.rank;

-- Each judge's total for a decision
SELECT judge_name, sum(red_score) AS red, sum(blue_score) AS blue
FROM ufc.main.fight_scorecards(12000)
GROUP BY judge_name;
```

`judges_scores` in `fight_results()` lists each judge's total as winner-loser.
`fight_duration_seconds` assumes five-minute rounds.

### Fight statistics

```sql
-- Whole-fight totals for both fighters
SELECT fighter_name, knockdowns, sig_strikes_landed, sig_strikes_attempted,
       sig_strike_accuracy_pct, takedowns_landed, control_seconds
FROM ufc.main.fight_stats(12000);

-- Momentum round by round
SELECT round_number, fighter_name, sig_strikes_landed, sig_head_landed,
       sig_ground_landed, control_seconds
FROM ufc.main.fight_round_stats(12000)
ORDER BY round_number, corner DESC;
```

Significant strikes are broken down by target (head, body, leg) and position
(distance, clinch, ground). Accuracy columns are exact decimals from 0 to 100,
and positional times are integer seconds.

### Fighter careers from ESPN

```sql
SELECT fighter_name, record, ko_tko_wins, submission_wins, height_in, reach_in, stance
FROM ufc.main.fighter(3022677);

SELECT fight_number, event_time, event_name, opponent_name, result, method, ending_round
FROM ufc.main.fighter_fight_history(3022677)
ORDER BY fight_number;

-- Career totals over every ESPN-tracked fight
SELECT count(*) AS fights, sum(sig_strikes_landed) AS sig_landed,
       sum(knockdowns) AS knockdowns, sum(takedowns_landed) AS takedowns
FROM ufc.main.fighter_career_stats(3022677);
```

## Data sources, licensing, and affiliation

This worker is **not affiliated with, endorsed by, or sponsored by** the
Ultimate Fighting Championship, Zuffa, LLC, TKO Group Holdings, the PFL,
Bellator, ESPN, or The Walt Disney Company. All trademarks belong to their
owners, and the worker uses no league or broadcaster logos.

| Source | Used for | Status |
| --- | --- | --- |
| UFC live-data feed (`d29dxerjsp82wz.cloudfront.net/api/v3`) | Cards, results, scorecards, fight and round statistics | Official UFC backend for ufc.com; undocumented; no published licence |
| ufc.com/rankings | Current rankings | Official UFC web page, parsed from HTML |
| ESPN site and common APIs (`site.api.espn.com`, `site.web.api.espn.com`) | Calendars, bout results, fighter profiles, histories, career statistics | Unofficial, undocumented; subject to ESPN's and Disney's terms of use |

None of these sources publishes an open data licence. The data is factual
sports information. `vgi-ufc` fetches it only when a query asks for it, caches
responses briefly in process, identifies itself with an honest User-Agent, and
never rehosts, redistributes, or persists the upstream data.

ESPN's endpoints are undocumented, may change without notice, and are governed
by ESPN's terms of use, which restrict automated access. Excluded sources:
ufcstats.com (it serves a bot challenge) and ESPN's stale MMA rankings.

**You are responsible for making sure that your use of this worker and the data
it returns complies with the terms of every upstream source.** This applies in
particular to commercial use, redistribution, and publication.

## Production HTTP deployment

Stdio is the recommended transport when Haybarn can launch the worker locally.
Use HTTP when the worker must be shared across hosts. The production HTTP entry
point fails closed unless it has a stable signing key and either authentication
or an explicit anonymous-access decision:

```bash
export VGI_SIGNING_KEY='a-long-random-secret-shared-by-every-replica'
export VGI_BEARER_TOKENS='replace-with-a-random-token=haybarn'

uvx --from git+https://github.com/Query-farm/vgi-ufc@v0.2.0 vgi-ufc-http \
  --host 0.0.0.0 \
  --port 8000 \
  --cors-origins 'https://sql.example.com' \
  --log-format json
```

`vgi-ufc-http` disables the description pages and cross-origin access unless
they are explicitly configured. Terminate TLS at a trusted proxy or load
balancer. All replicas must receive the same `VGI_SIGNING_KEY`. Rotate it as a
coordinated deployment, because outstanding state tokens are signed with it.

Supported authentication options are:

- `VGI_BEARER_TOKENS`: comma-separated `token=principal` pairs.
- `VGI_JWT_ISSUER` and `VGI_JWT_AUDIENCE`: JWT/JWKS authentication.
- `VGI_PROXY_PROOF_MODE=require` with the corresponding VGI proxy-proof
  settings when a trusted proxy authenticates users.

A deployment that is intentionally public can set `VGI_ALLOW_ANONYMOUS=1`. It
should still sit behind gateway rate limits, because every query reaches the
upstream sources. The health probe is `GET /health`.

### Container

```bash
docker build -t vgi-ufc .
docker run --rm -p 8000:8000 \
  -e VGI_SIGNING_KEY='replace-with-a-stable-random-secret' \
  -e VGI_BEARER_TOKENS='replace-with-a-random-token=haybarn' \
  vgi-ufc
```

The image runs as an unprivileged user, emits JSON logs, disables interactive
description pages, and includes a health check.

## Reliability and operations

Every request identifies itself as
`vgi-ufc/<version> (+https://github.com/Query-farm/vgi-ufc)`. Upstream calls use
a 30-second request timeout, a 120-second total query deadline, at most four
attempts, and at most four simultaneous upstream requests per process.
Redirects are followed. HTTP 429 and transient 5xx responses are retried with
exponential backoff and jitter, and `Retry-After` is honored with a 30-second
per-retry cap. Gzip bodies that arrive without a `Content-Encoding` header (an
ESPN quirk) are decoded.

Responses are cached in process (LRU, 512 entries) and the lifetime is
forwarded to VGI clients as cache policy:

| Resource | Lifetime |
| --- | --- |
| UFC feed: final event or fight | 6 hours |
| UFC feed: upcoming or live | 60 seconds |
| ESPN scoreboards | origin `max-age`, clamped to 2-30 minutes |
| ESPN fightcenter and athletes | origin `max-age`, clamped to 2-60 minutes |
| ufc.com rankings | 1 hour (the origin's week-long `max-age` is capped) |

Unknown ids return empty results, not errors. If ufc.com changes the rankings
page structure, `current_rankings` fails with an explicit error instead of
returning partial rows. Success timings are logged at debug level, and retries
and transport failures are logged as warnings.

These environment variables point the worker at alternate roots for hermetic
tests. Do not set them from untrusted input:

| Variable | Default |
| --- | --- |
| `UFC_FEED_BASE_URL` | `https://d29dxerjsp82wz.cloudfront.net/api/v3` |
| `UFC_WEB_BASE_URL` | `https://www.ufc.com` |
| `ESPN_SITE_BASE_URL` | `https://site.api.espn.com/apis/site/v2/sports/mma` |
| `ESPN_COMMON_BASE_URL` | `https://site.web.api.espn.com/apis/common/v3/sports/mma` |

## Development and release checks

```bash
uv lock --check --no-sources
uv sync --no-sources
uv run --no-sources ruff check .
uv run --no-sources ruff format --check .
uv run --no-sources pytest
uv build
uvx twine check dist/*
uvx --no-sources --from vgi-lint-check==2.2.0 vgi-lint lint \
  'uv run --no-sources ufc_worker.py' \
  --no-execute --no-check-links --audit-waivers --fail-on warning
```

The offline suite includes a hermetic Haybarn end-to-end test. It serves
recorded upstream responses from `tests/fixtures/` on a local HTTP server and
queries every table and function. Live upstream smoke tests are opt-in with
`uv run pytest -m live`. They also run in a serialized scheduled workflow
alongside the executing vgi-lint pass, which runs every catalog example.
Publishing is driven by releases. Create a GitHub release named `vX.Y.Z` that
matches the version in `pyproject.toml`. CI then builds, validates and attests
the wheel and sdist, attaches them to the release, and publishes a
multi-platform container image to `ghcr.io/query-farm/vgi-ufc`. The package is
not published to PyPI; install it from the release tag as shown in the quick
start.

## Authorship & License

Written by [Query.Farm](https://query.farm) and released under the [MIT License](LICENSE).

Copyright 2026 Query Farm LLC - https://query.farm
