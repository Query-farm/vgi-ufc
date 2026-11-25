# Changelog

All notable changes to this project are documented here.

## [0.3.0] - 2026-11-25

- Speaks VGI protocol 3.4: require vgi-python `>=0.55.1,<0.56`; uv.lock re-locked. This release
  needs Haybarn 2.0.1 (or stock DuckDB 2.0 with `INSTALL vgi FROM query_farm`): Haybarn 2.0.0
  loads a 3.3 `vgi` extension that cannot attach it.
- SQL tests run on haybarn-unittest 2.0.1rc3 (CI and Makefile).
- `serve` extra includes `vgi-python[http,oauth]`; the Docker image installs it, so the image runs in
  Orchard hosted mode (`VGI_ORCHARD_HOSTED=1` with VGI_JWT_ISSUER, VGI_JWT_AUDIENCE,
  VGI_JWT_JWKS_URI and VGI_SIGNING_KEY). The Docker HEALTHCHECK uses `HEAD /health`, which
  stays anonymous in hosted mode.

## [Unreleased]

## 0.2.2 (2026-11-16)

- Bump vgi-python to 0.52.2.
- Requires Python 3.14 (CI, Docker image and tooling moved to 3.14).
- CI runs the SQL tests over stdio, launch and HTTP transports.

## [0.2.1]

- `current_rankings.ufc_athlete_url` is canonical again (`https://www.ufc.com/athlete/<slug>`). ufc.com
  now links most ranked athletes as `/index%2ephp/athlete/<slug>`, which broke the join to
  `card_fighters().ufc_athlete_url` for every card (the ranked-on-card example returned no rows,
  VGI902). The URL is rebuilt from the slug.
- The ranked-on-card example uses UFC 324 (feed event 1294), a completed card with more ranked
  fighters, so it survives weekly ranking changes; a live test pins the join.
- `vgi-lint.toml` waives VGI809 for `upcoming_events`/`current_season_events`: they share ESPN
  event ids but neither is a subset of the other, so no foreign key holds.

- Docs link to upstream sources (VGI183): the catalog documentation now links the data providers it reads.
- Docs give an overview, not a function list (VGI173): the catalog doc_llm now describes the data,
  its three sources and the two id systems instead of naming every table and function.

## [0.2.0]

- Speaks VGI protocol 3.3 (vgi-python 0.51); requires the current VGI DuckDB
  extension (3.2 extensions are incompatible).
- CI lints with vgi-lint-check 2.5.0.

## [0.1.0]

- Initial release on VGI protocol 3.2 (vgi-python 0.50, vgi-lint-check 2.2.0).
- Official UFC rankings from ufc.com as `current_rankings`.
- UFC, PFL, and Bellator event calendars and bout results from ESPN
  (`events`, `event_bouts`, `upcoming_events`, `current_season_events`).
- Official UFC cards, fighter details, results, judges' scorecards, and
  whole-fight and per-round statistics from UFC's live-data feed, with
  `feed_events` for event-id discovery.
- ESPN fighter profiles, fight histories, and per-fight career statistics.
- Honest User-Agent, retries with backoff, total query deadline, bounded
  concurrency, and an in-process TTL response cache.
