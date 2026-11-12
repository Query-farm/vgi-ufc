# Changelog

All notable changes to this project are documented here.

## [Unreleased]

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
