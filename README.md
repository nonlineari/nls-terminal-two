# Terminal Two

Local research pipeline for NLS Records. It estimates where a promotional budget might go across Korea, Japan, Indonesia, Vietnam, Thailand, China, and Hong Kong, using public data only.

This repository is the whole project (`nls-terminal-two`). It does not read or call any other NLS system. Nothing here is a quote for media buying, and nothing here is NLS campaign profit and loss.

The training label is a formula. Public campaign ROI for these markets is not available as a table, so the pipeline does not pretend to have one. The formula, the feature list, and the holes are documented below and in code.

Released under the [MIT License](LICENSE).

## What it does

```text
public APIs  →  data/raw  →  feature matrix  →  XGBoost  →  budget split
```

1. **Ingest.** World Bank development indicators, Frankfurter exchange rates, Wikidata sitelinks, Wikimedia pageviews, and Apple Music most-played charts. Sync rate cards, territory CPM/CPC, platform MAU, and IFPI territory revenue are requested or probed and, when they do not come back as territorial numbers, left null.
2. **Features.** One row per market × channel (`streaming_dsp`, `short_video`, `social_influencer`). An indie accessibility score is a documented heuristic. It is reported and not fed to the model.
3. **Model.** A small XGBoost ensemble predicts the proxy label. Evaluation is leave-one-market-out, compared with a train-fold mean. The saved artifact is `models/promo_return_xgb.joblib`.
4. **Recommend.** The CLI loads that artifact, ranks market × channel rows by the out-of-fold proxy index, and prints a percentage split of the budget you pass in.

Channels with no public series (`sync_licensing`, `paid_social`) are listed and receive no invented rate.

## Proxy label

Full text lives in `src/features/proxy_target.py` (`FORMULA_TEXT`). Short version:

```text
proxy_return = opportunity × (0.35 + 0.65 × channel_attention_share)

opportunity =
    0.40 × minmax(log internet users)
  + 0.25 × minmax(internet-user CAGR)
  + 0.20 × minmax(population share ages 0–14)
  + 0.15 × (1 − minmax(log GDP per capita))
```

Internet users are population times the World Bank internet-user rate, on years where both exist. Ages 0–14 are used because the World Bank API rejects indicator id `SP.POP.1524.TO.ZS` (ages 15–24). That is not the 15–24 music audience.

`channel_attention_share` is the mix of local-Wikipedia pageviews across the three channels over the last 12 complete months. It is attention, not ROI. If a component is missing for any eligible market, it is dropped and the remaining weights are renormalized. A missing attention share leaves the row unlabeled. The pipeline does not fill it.

The model is not shown the opportunity inputs (population, internet rate, internet-user CAGR, age share, GDP, the indie score, exchange rates). It may use mobile subscriptions, broadband, urbanization, inflation, secure-server density, the Apple chart snapshot, pageview growth, the attention share, and channel indicators. Attention share is the one formula input that is also a feature: it is the only observed channel-level signal. Mobile and broadband still move with income and connectivity, so some fit is mechanical. Leave-one-market-out is there so that fact is visible.

## Why XGBoost

The table is a few dozen rows. XGBoost is fit with depth-wise trees (`max_depth` 2), a learning rate of 0.05, and L2 regularization (`reg_lambda` 8), in an ensemble of five seeds starting at 42. LightGBM's leaf-wise default will isolate single markets on a sample this small. Either library would be underpowered. XGBoost is the more constrained default and installs as one wheel. A good score means the public features track the formula out of sample. It does not mean the formula is real promo ROI.

## Indie accessibility score

`src/features/indie.py`. Relative to the seven markets, higher means more structural room for a non-local or independent release: internet access, mobile access (capped at 150 subscriptions per 100 people, so Hong Kong's multi-SIM figure does not dominate), broadband, the 0–14 age share, lower GDP per capita, and a less concentrated set of streaming articles on the local Wikipedia (`1 − HHI`). Platform diversity is already on 0–1 and is not min-maxed again. The score is not a published industry index and is not a model input.

## Setup

Python 3.11+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash scripts/run_pipeline.sh
```

Or step by step, from the repository root:

```bash
python -m src.ingestion.run
python -m src.features.build
python -m src.model.train
python -m src.cli report
python -m src.cli recommend --budget 100000
```

`make pipeline`, `make test`, and `make recommend` call the same entry points. Ingestion logs blocked or empty sources to `data/raw/_failed_sources.jsonl` and continues. It exits with an error only when the core World Bank series (population, internet users, GDP per capita) are missing for too many markets, because the proxy cannot be built without them. The unit tests do not need the network:

```bash
python -m unittest discover -s tests -v
```

## Layout

```text
data/raw/            cached pulls and the failure log
data/processed/      feature matrix, dictionary, proxy notes
data/sources.md      every public source, with links
src/ingestion/       fetchers
src/features/        transforms and the proxy label
src/model/           XGBoost training
src/output/          confidence and the budget split
models/              joblib artifact, metadata, LOOCV predictions
scripts/run_pipeline.sh
```

## Latest run

The figures in this section are written by the pipeline in this environment and should be read next to `models/metrics.json` and `data/raw/latest_run.json`. Re-run `bash scripts/run_pipeline.sh` to replace them.

_Results are filled in after the first end-to-end run._

## Limitations

- The label is a formula. Confidence is capped at 0.85 for that reason.
- Seven markets, held out one at a time, is a small test. One unusual market moves the metrics.
- Wikipedia pageviews are not streaming MAU. `zh.wikipedia` and `zh-yue.wikipedia` are not a census of China and Hong Kong.
- No public sync rate card or territory CPM/CPC series is in the model. Those columns are null on purpose.
- Ages 0–14 are not ages 15–24.
- Apple charts are one snapshot.
- The allocation is a split of the number you pass to `--budget`. It is not converted, and it is not a forecast of revenue.
- This is not media-buying advice.

## Next iteration

- Replace the proxy with internal campaign P&L if NLS can share it. Until then, do not tune the formula to make R² look better.
- Territory subscriber or MAU series from a primary disclosure, not a global IFPI sentence copied onto every market.
- A real 15–24 population series (UN World Population Prospects) in place of ages 0–14.
- Authorized ad-platform CPM/CPC by country, skipped cleanly when no credential is present.
- Sync quotes by placement type (film, TV, advertising, games) from a rate card that is actually public and machine-readable.
- A better Hong Kong attention panel than Cantonese Wikipedia alone.
- Recalibrate confidence only after the label is observed money.

## For contributors

See [CONTRIBUTING.md](CONTRIBUTING.md) and [data/sources.md](data/sources.md).
