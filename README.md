# Terminal Two

Local research pipeline for NLS Records. It estimates where a promotional budget might go across Korea, Japan, Indonesia, Vietnam, Thailand, China, and Hong Kong, using public data only.

This repository is the whole project (`nls-terminal-two`). It does not read or call any other NLS system. Nothing here is a quote for media buying, and nothing here is NLS campaign profit and loss.

The training label is a formula. Public campaign ROI for these markets is not available as a table, so the pipeline does not pretend to have one. The formula, the feature list, and the holes are documented below and in code.

Released under the [MIT License](LICENSE).

## What it does

```text
public APIs  →  data/raw  →  feature matrix  →  XGBoost  →  budget split
```

1. **Ingest.** World Bank development indicators, Frankfurter exchange rates, Wikidata sitelinks, Wikimedia pageviews, and Apple Music most-played charts. Sync rate cards, platform MAU, and IFPI territory revenue are requested or probed and, when they do not come back as territorial numbers, left null. Territory CPM/CPC may also come from an optional local rate-card JSON (`src/rates/`); without it they stay null.
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

Or step by step, from the repository root. Use `python` when that command is Python 3; the commands below use `python3`.

```bash
python3 -m src.ingestion.run
python3 -m src.features.build
python3 -m src.model.train
python3 -m src.cli report
python3 -m src.cli recommend --budget 100000
```

`make pipeline`, `make test`, and `make recommend` call the same entry points. Ingestion logs blocked or empty sources to `data/raw/_failed_sources.jsonl` and continues. It exits with an error only when the core World Bank series (population, internet users, GDP per capita) are missing for too many markets, because the proxy cannot be built without them. The unit tests do not need the network:

```bash
python3 -m unittest discover -s tests -v
```

### Optional CPM/CPC rate card

Territory CPM/CPC stay null unless you supply an enabled rate-card JSON. Nothing is invented.

1. Copy `config/rate_card.example.json` to `config/rate_card.json` (or any path).
2. Replace the EXAMPLE numbers with authorized rates. Set `"enabled": true`.
3. Optionally set `NLS_RATE_CARD_PATH` to that file. If unset, `config/rate_card.json` is used when present.
4. Rebuild features (and re-run recommend): `python3 -m src.features.build`.

Expected shape is documented in `src/rates/rate_card.py` and the example file: a list of `{market_code, channel, cpm_usd?, cpc_usd?}` for scored channels only (`streaming_dsp`, `short_video`, `social_influencer`). Sync and paid social stay unscored.

`NLS_AD_PLATFORM_API_KEY` / `NLS_AD_PLATFORM_API_SECRET` are credential stubs for a future ad-platform pull. They do not fetch or fabricate rates today.

When rates are present, `recommend` multiplies each row's allocation weight by a cost-efficiency factor (`median(cost) / cost` on CPM, else CPC). Rows without a rate keep factor 1.0. With no rate card, the split matches the previous behavior.

## Layout

```text
data/raw/            cached pulls and the failure log
data/processed/      feature matrix, dictionary, proxy notes
data/sources.md      every public source, with links
config/              rate_card.example.json (copy to rate_card.json to enable)
src/ingestion/       fetchers
src/features/        transforms and the proxy label
src/rates/           optional CPM/CPC rate-card load + cost-aware reweight
src/model/           XGBoost training
src/output/          confidence and the budget split
models/              joblib artifact, metadata, LOOCV predictions
scripts/run_pipeline.sh
```

## Latest run

Pulled `20261022T054656Z`. Read `data/raw/latest_run.json` and `models/metrics.json` beside this section. Re-run `bash scripts/run_pipeline.sh` to replace both.

### What came back

| Source | Result |
| --- | --- |
| World Bank (population, internet, GDP per capita, mobile, broadband, urban, ages 0–14 and 15–64, inflation, official FX, secure servers) | Pulled for all seven markets. Internet-user counts use 2024 except China, which uses 2025 because that is the latest year both series exist. |
| World Bank ages 15–24 (`SP.POP.1524.TO.ZS`) | API error 120, invalid indicator id. Logged. Not replaced with a made-up series. |
| Frankfurter USD rates | KRW, JPY, IDR, THB, CNY, HKD on 2026-10-21. VND 404. Vietnam keeps the World Bank official rate only. |
| Wikidata + Wikimedia pageviews | 13 platforms accepted (Spotify, Apple Music, YouTube Music, Amazon Music, Melon, LINE MUSIC, JOOX, QQ Music, NetEase Cloud Music, KKBOX, TikTok, YouTube, Instagram). 75 article series returned, 16 had no sitelink on that language edition. Window: Oct 2024–Sep 2026. |
| Optional platforms AWA, Genie Music, Bugs | No unambiguous Wikidata item. Logged. No views invented. |
| Apple most-played songs | All seven storefronts returned 25 tracks. |
| IFPI industry page | Fetched. Visible text had no territory names. Global sentences kept in the raw cache and not copied onto markets: 2024 global recorded-music revenue +4.8%; streaming 69.0% of global revenue; streaming +9.5%; 752 million paid subscription accounts worldwide. |
| IFPI Global Music Report PDF paths (2024 and 2025 guesses) | HTTP 404. |
| Statista digital-music outlook and social CPM | No territorial table extracted. No CPM copied. |
| RIAJ digital page | HTTP 503. |
| ASCAP royalty help | HTTP 403. No sync rate card. |
| Deezer chart | Global chart only. Not assigned to markets. |

Null on every row, on purpose: streaming MAU, subscribers, film/TV/advertising/game sync rates, brand-deal counts and prices, CPM, CPC.

### Proxy label, before the model

The formula ran with all four components (weights 0.40 / 0.25 / 0.20 / 0.15). It is a unitless index.

| Market | Internet-user CAGR | Opportunity | Indie score | Short-video attention |
| --- | --- | --- | --- | --- |
| Indonesia | 15.2% | 0.86 | 0.41 | 0.84 |
| China | 6.4% | 0.68 | 0.64 | 0.63 |
| Vietnam | 8.2% | 0.66 | 0.59 | 0.89 |
| Thailand | 9.9% | 0.52 | 0.66 | 0.75 |
| Japan | −1.0% | 0.25 | 0.55 | 0.50 |
| Korea | 1.1% | 0.21 | 0.69 | 0.65 |
| Hong Kong | 1.7% | 0.04 | 0.62 | 0.74 |

Indonesia ranks high on the formula because internet-user growth, the 0–14 age share, and low GDP per capita all point the same way, on top of a large online population. Hong Kong ranks low because the online population is small, GDP per capita is high, and growth is slow. Short-video articles (YouTube and TikTok) take most of the Wikipedia attention in every market. That is a fact about those language editions, not a measured return.

The indie score is a different heuristic (connectivity, capped mobile, age, inverse GDP, streaming-article diversity). Korea is highest (0.69) and Indonesia lowest (0.41). It is not a model input.

### Model

Leave-one-market-out, 21 rows, XGBoost ensemble of 5, depth 2, seed 42.

| | MAE | RMSE | R² |
| --- | --- | --- | --- |
| LOOCV model | 0.163 | 0.204 | −0.126 |
| LOOCV train-fold mean | 0.172 | 0.214 | −0.236 |
| In-sample fit (optimistic) | 0.122 | | 0.269 |

The model is slightly closer in absolute error than guessing the training mean, and it does not beat a flat line on R². Separation of predictions versus labels is 0.11. Labels run from 0.02 to 0.77. Out-of-fold predictions all sit between 0.23 and 0.30. The model pulls Indonesia's short-video label (0.77) down to 0.24 and Hong Kong's streaming label (0.02) up to 0.29. It cannot see population, internet CAGR, age, or GDP, and the structural features it can see do not recover that formula.

Mean gain share:

| Feature | Share |
| --- | --- |
| urban_pct | 30.2% |
| mobile_per_100 | 26.6% |
| secure_servers_per_million | 15.2% |
| channel_pageview_growth | 10.6% |
| channel_attention_share | 9.2% |
| inflation_pct | 3.6% |
| channel_is_streaming_dsp | 2.2% |
| apple_share_new_90d | 1.2% |
| channel_is_short_video | 1.2% |
| broadband_per_100, Apple genre HHI, Apple artist diversity, social channel flag | 0% |

Confidence on the allocated rows is about 0.34 to 0.53, under the 0.85 cap.

### Budget split of 100,000

`python3 -m src.cli recommend --budget 100000` ranks by the out-of-fold prediction. Because those predictions barely differ, the split is nearly even: about 3.1% to 5.9% per market × channel. The largest pieces are Thailand social (5.88%), Vietnam streaming (5.63%), and Vietnam social (5.49%). That is not a finding that those channels return more money. It is what a low-separation model does when multiplied by confidence. Sync and paid social get nothing, because there is no public rate to score.

If you rank the proxy formula instead of the model, the top rows are Indonesia short video (0.77), Vietnam short video (0.61), and China short video (0.51). That ranking is also not observed campaign ROI. The CLI prints both when R² is negative.

## Limitations

- The label is a formula. Confidence is capped at 0.85 for that reason.
- Seven markets, held out one at a time, is a small test. One unusual market moves the metrics.
- Wikipedia pageviews are not streaming MAU. `zh.wikipedia` and `zh-yue.wikipedia` are not a census of China and Hong Kong.
- No public sync rate card is in the model. Territory CPM/CPC columns are null unless an enabled local rate card supplies them; they are not model features.
- Ages 0–14 are not ages 15–24.
- Apple charts are one snapshot.
- The allocation is a split of the number you pass to `--budget`. It is not converted, and it is not a forecast of revenue.
- This is not media-buying advice.

## Next iteration

- Replace the proxy with internal campaign P&L if NLS can share it. Until then, do not tune the formula to make R² look better.
- Territory subscriber or MAU series from a primary disclosure, not a global IFPI sentence copied onto every market.
- A real 15–24 population series (UN World Population Prospects) in place of ages 0–14.
- Authorized ad-platform CPM/CPC by country: local rate-card hooks are in `src/rates/` (skipped cleanly when no file/credential). Wire a real platform API when credentials exist.
- Sync quotes by placement type (film, TV, advertising, games) from a rate card that is actually public and machine-readable.
- A better Hong Kong attention panel than Cantonese Wikipedia alone.
- Recalibrate confidence only after the label is observed money.

## For contributors

See [CONTRIBUTING.md](CONTRIBUTING.md) and [data/sources.md](data/sources.md).
