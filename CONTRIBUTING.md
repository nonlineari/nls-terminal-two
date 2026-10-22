# Contributing

Terminal Two is a local research pipeline. Pull requests should keep it reproducible, and they should not fill missing music-business numbers with guesses.

## Setup

Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run commands from the repository root so `python3 -m src...` can import the package. If `python` on your machine is Python 3, that works too. The shell script picks `python` when it exists and `python3` otherwise.

```bash
bash scripts/run_pipeline.sh
```

That pulls public sources, builds the feature matrix, trains the model, prints a sample allocation of 100000, and runs the unit tests. `make test` runs the tests without the network.

## Adding a data source

1. Add a fetcher under `src/ingestion/` that uses `src.ingestion.http_util.fetch`.
2. Save the response with `src.jsonutil.write_json` under `data/raw/`, including the URL, the UTC timestamp, and the run id in the file or in the envelope.
3. On HTTP errors, paywalls, empty tables, or global figures that are not territorial, call `record_failure` and continue. Do not invent a row so the matrix looks complete.
4. Register the fetcher in `src/ingestion/run.py` and point `data/raw/manifest.json` at the new file.
5. Map only values that are actually in the payload into `src/features/`. If the concept is still missing (a sync rate, a CPM, a MAU), add a column with role `unavailable` in `src/features/dictionary.py` and leave it null.
6. Document the source in `data/sources.md`: link, what it covers, what it does not cover, and how someone else can re-fetch it.
7. If the new column is allowed into the model, keep it out of `LEAKAGE_COLUMNS` in `src/model/spec.py` unless you are also changing the proxy formula. The unit tests fail when a formula input silently becomes a feature. `channel_attention_share` is the one deliberate exception.

Heuristics belong in their own function with the weights and the reason written next to the code (`src/features/indie.py`, `src/features/proxy_target.py`). Do not describe a heuristic as a measurement.

## Coding style

- Python 3.11+, PEP 8, type hints on public functions.
- Seed the model with `src.config.SEED` (42). Do not add a second hidden seed.
- Prefer the standard library plus the packages already in `requirements.txt`.
- Keep fetchers separate from feature math so the math can be tested without the network.
- Comments should explain a formula, a cap, or a source quirk. Do not narrate the control flow.

## Pull requests

Keep the change small enough that a reviewer can see which source or which formula moved. In the description, say:

- which public URL or API you added
- whether any new column is observed, a proxy, a heuristic, or deliberately null
- that you did not require an API key (optional keys must be skipped when they are absent)
- how you ran tests, or which network pull you could not complete

If the work tracks an issue, mention it in the description. A formula change needs a unit test and an update to the formula text in `src/features/proxy_target.py` and the README.
