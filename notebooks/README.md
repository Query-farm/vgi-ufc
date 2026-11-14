# UFC SQL notebook

[01 · Strike counts and scorecards](01_strikes_and_scorecards.ipynb) compares one historical fight's significant strikes with each judge's awarded points. It reconciles all round rows with whole-fight totals and tests how a retrospective prefix changes the descriptive comparison. The source is actual recorded public data, not synthetic fight statistics.

From this directory alone, with [uv](https://docs.astral.sh/uv/) and Git installed:

```sh
uv sync --locked
uv run --locked python execute.py
uv run --locked python execute.py --parameters '{"LAST_ROUND":1}' --output-dir validation/round-1
uv run --locked python execute.py --parameters '{"DATA_MODE":"live"}' --output-dir validation/live
```

For an interactive notebook, register this environment and select it in Jupyter:

```sh
uv run --locked python -m ipykernel install --user --name vgi-ufc-notebooks --display-name 'Python (vgi-ufc notebooks)'
```

Open the notebook with your existing Jupyter installation, select that kernel and Restart Kernel → Run All. The runner creates an ephemeral kernel without a global registration, runs with this directory as cwd and only replaces a notebook after successful execution. Parameter overrides require a separate destination; experiment copies include the relative branding, documentation and runtime companions. `artifacts/` and `validation/` are ignored.

## Portable worker

The visible SQL installs/loads VGI and launches `uvx --python 3.13 --from git+https://github.com/Query-farm/vgi-ufc.git@v0.2.0 --constraints worker-constraints.txt vgi-ufc`. The verified remote tag resolves to `37a19b751434843df4690bef4e746296c3de7237`. The worker is not on PyPI; uv fetches the public Git revision and published dependencies, caching them after first use. No parent source directory or local worker binary is used. Notebook Haybarn is pinned to `2.0.0rc11`; SDK `0.51.0`, RPC `0.53.1`, PyArrow `25.0.1` and httpx `0.28.1` are pinned separately for the worker. Upgrade only after executing the complete default and experiment with the new pin.

The Haybarn connection uses a fresh temporary secret directory, disables persistent secrets and verifies an empty credential inventory before ATTACH. The companion overrides all four supported upstream roots; only the exact fight path is permitted. Environment values are restored and the server, connection and temporary directory are closed at cleanup. No credentials are needed.

## Provenance and bounded requests

`recordings/fight-12000.json` is the exact 18,769-byte response from [UFC's live-data feed](https://d29dxerjsp82wz.cloudfront.net/api/v3/fight/live/12000.json), received **2026-11-14T10:54:33.970000+00:00**, SHA256 `d09315ffc4997001d70a754e941cc882f30f2cf76eda79945ca8b9c4e43fc23a`. `recordings/manifest.json` records its URL, status, timestamp and size. The document concerns Navajo Stirling versus Ivan Erslan at UFC 315, feed event 1252, whose event start is labeled `2025-05-10T22:30Z`. That is not an asserted exact bout start.

The bounded companion admits one GET of `/fight/live/12000.json`; unknown paths and repeated requests fail. The three worker functions share the unchanged worker's final-fight response cache, then SQL materializes all data before analysis. `LAST_ROUND` filters locally; neither it nor SQL LIMIT bounds a remote request. Live mode fetches the same fixed historical document, with a 30-second timeout and a four-megabyte body ceiling, records its actual receipt/hash/bytes and never falls back to replay. The notebook fails if expected round coverage or reconciliation breaks. A source revision may legitimately change returned values; all claims are derived from current results.

UFC's feed is undocumented and has no published open-data licence. This repository's MIT code licence does not grant an upstream data licence. This small factual example and its saved outputs are unaffiliated with UFC; no league logos are included. It is not a full dataset, scoring model, assessment of judging accuracy, prediction or estimate of population-wide agreement. Counts lack the full context of the actions. The example was deliberately selected to show differing measurements.

## Validation

Default and `LAST_ROUND=1` are executed separately, with the experiment launched from a copy containing only `notebooks/`. Live mode is checked separately. Saved audits contain complete-source fingerprints, returned populations, ledger checks and the exact request receipt. The experiment must preserve the whole-source fingerprint and final result, retain identical round-one measurements, and still perform only one read. Both charts are visually inspected. Source validation follows the repository CI (lint, format, coverage, package checks and structural metadata). Docker smoke testing is unavailable on this host because Docker Desktop reports it cannot start; no existing container is restarted.

See [STANDARD.md](STANDARD.md) for the presentation and execution conventions.
