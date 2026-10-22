# Public data sources

Terminal Two only trains on numbers that a pull actually returned. This file is the catalog. The latest pull's successes and failures are in `data/raw/latest_run.json`. `data/raw/_failed_sources.jsonl` is the same run as JSON lines: it is cleared at the start of each ingestion so it does not mix a killed run with a finished one.

Re-fetch everything from the repository root:

```bash
python3 -m src.ingestion.run
```

Cached envelopes live in `data/raw/` with the run id in the filename. `data/raw/manifest.json` points at the files from the latest run.

## How to verify a pull

1. Open the `url` field inside the cached JSON and request it again with the same User-Agent the pipeline sends (`src/config.py`).
2. Diff the new body against the cached `body` or `indicators`. World Bank revises history, so small changes in older years are normal.
3. Confirm a column in `data/processed/feature_matrix.csv` is null when this catalog says the source did not yield that concept. A null is the correct result.

## How to extend a pull

See `CONTRIBUTING.md`. Short version: add a fetcher, cache the body, log the miss, document it here, and do not backfill.

## Sources that feed the matrix

### World Bank World Development Indicators

- Docs: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation
- Endpoint pattern: `https://api.worldbank.org/v2/country/KOR;JPN;IDN;VNM;THA;CHN;HKG/indicator/{INDICATOR}?format=json`
- Markets: Korea (KOR), Japan (JPN), Indonesia (IDN), Vietnam (VNM), Thailand (THA), China (CHN), Hong Kong (HKG).
- No API key.

| Indicator | What it is | Used as |
| --- | --- | --- |
| [SP.POP.TOTL](https://data.worldbank.org/indicator/SP.POP.TOTL) | Population | Level, and the denominator for internet users. History 2015–2025. |
| [IT.NET.USER.ZS](https://data.worldbank.org/indicator/IT.NET.USER.ZS) | Internet users, % of population | Level and, with population, internet-user CAGR. Not platform MAU. |
| [NY.GDP.PCAP.CD](https://data.worldbank.org/indicator/NY.GDP.PCAP.CD) | GDP per capita, current US$ | Cost-pressure input to the proxy label. Not a CPM. |
| [NY.GDP.PCAP.PP.CD](https://data.worldbank.org/indicator/NY.GDP.PCAP.PP.CD) | GDP per capita, PPP | Audit column only. |
| [NY.GDP.MKTP.CD](https://data.worldbank.org/indicator/NY.GDP.MKTP.CD) | GDP, current US$ | Audit column only. |
| [IT.CEL.SETS.P2](https://data.worldbank.org/indicator/IT.CEL.SETS.P2) | Mobile subscriptions per 100 people | Model feature. Indie score caps this input at 150. |
| [IT.NET.BBND.P2](https://data.worldbank.org/indicator/IT.NET.BBND.P2) | Fixed broadband per 100 people | Model feature. |
| [SP.URB.TOTL.IN.ZS](https://data.worldbank.org/indicator/SP.URB.TOTL.IN.ZS) | Urban population, % | Model feature. |
| [SP.POP.0014.TO.ZS](https://data.worldbank.org/indicator/SP.POP.0014.TO.ZS) | Population ages 0–14, % | Demographic term in the proxy. Not ages 15–24. |
| [SP.POP.1564.TO.ZS](https://data.worldbank.org/indicator/SP.POP.1564.TO.ZS) | Population ages 15–64, % | Audit column. Kept out of the model because it is a cousin of the age term. |
| [FP.CPI.TOTL.ZG](https://data.worldbank.org/indicator/FP.CPI.TOTL.ZG) | Inflation, annual % | Model feature. Can be negative. |
| [PA.NUS.FCRF](https://data.worldbank.org/indicator/PA.NUS.FCRF) | Official exchange rate, LCU per USD | Audit column, including VND. Not a model feature: the level identifies the currency, not the opportunity. |
| [IT.NET.SECR.P6](https://data.worldbank.org/indicator/IT.NET.SECR.P6) | Secure internet servers per million people | Model feature. Hong Kong is a data-center outlier. |

The pipeline also requests `SP.POP.1524.TO.ZS` (ages 15–24). The API rejects that id (`Invalid value`). The rejection is logged on every run. There is no substitute 15–24 series.

Years differ by indicator (a 2025 GDP next to a 2024 internet rate). The matrix keeps a `*_year` column for each value. Internet users are computed only on years where population and the internet rate both exist.

### Frankfurter (ECB reference rates)

- Docs: https://www.frankfurter.app/docs/
- Latest USD crosses: https://api.frankfurter.app/latest?from=USD&to=KRW,JPY,IDR,THB,CNY,HKD
- VND request (expected to 404): https://api.frankfurter.app/latest?from=USD&to=VND
- Covers a daily spot rate for the currencies ECB publishes. It does not cover the Vietnamese dong. The matrix leaves `fx_frankfurter_lcu_per_usd` null for Vietnam and keeps the World Bank official rate instead.
- Not a model feature.

### Wikidata and Wikimedia pageviews

- Wikidata API: https://www.wikidata.org/w/api.php
- Access notes: https://www.wikidata.org/wiki/Wikidata:Data_access
- Pageview API: `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/all-access/user/{title}/monthly/{start}/{end}`
- Docs: https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/

Pinned entities (the pipeline checks the English label and description before accepting them, so a same-name fruit or award cannot slip in):

| Key | QID | Channel |
| --- | --- | --- |
| Spotify | [Q689141](https://www.wikidata.org/wiki/Q689141) | streaming DSP |
| Apple Music | [Q20056642](https://www.wikidata.org/wiki/Q20056642) | streaming DSP |
| YouTube Music | [Q28404534](https://www.wikidata.org/wiki/Q28404534) | streaming DSP |
| Amazon Music | [Q4740860](https://www.wikidata.org/wiki/Q4740860) | streaming DSP |
| Melon | [Q12595115](https://www.wikidata.org/wiki/Q12595115) | streaming DSP |
| LINE MUSIC | [Q20856958](https://www.wikidata.org/wiki/Q20856958) | streaming DSP |
| JOOX | [Q28187024](https://www.wikidata.org/wiki/Q28187024) | streaming DSP |
| QQ Music | [Q10852229](https://www.wikidata.org/wiki/Q10852229) | streaming DSP |
| NetEase Cloud Music | [Q20063955](https://www.wikidata.org/wiki/Q20063955) | streaming DSP |
| KKBOX | [Q10851252](https://www.wikidata.org/wiki/Q10851252) | streaming DSP |
| TikTok | [Q48938223](https://www.wikidata.org/wiki/Q48938223) | short video |
| YouTube | [Q866](https://www.wikidata.org/wiki/Q866) | short video |
| Instagram | [Q209330](https://www.wikidata.org/wiki/Q209330) | social / influencer |

Optional searches (AWA, Genie Music as a service, Bugs) are accepted only when exactly one hit matches the description filter. A miss is logged. Nothing is imputed.

Language editions, which are not countries:

| Market | Project |
| --- | --- |
| Korea | `ko.wikipedia` |
| Japan | `ja.wikipedia` |
| Indonesia | `id.wikipedia` |
| Vietnam | `vi.wikipedia` |
| Thailand | `th.wikipedia` |
| China | `zh.wikipedia` |
| Hong Kong | `zh-yue.wikipedia` |

Hong Kong is Cantonese Wikipedia on purpose, so it is not a copy of the mainland Chinese series. Readers outside the territory still count. Articles with no sitelink are gaps, not zero-view platforms.

The feature step sums user pageviews for the last 12 complete months and the 12 months before that. A window with fewer than 8 monthly observations is null. Growth is null when the prior window has fewer than 50 views. Channel attention share is the within-market mix of those three channels. Raw pageview levels are not model features, because a large Wikipedia edition is not a large music market.

### Apple Marketing Tools RSS

- Example: https://rss.applemarketingtools.com/api/v2/kr/music/most-played/25/songs.json
- One request per storefront: `kr`, `jp`, `id`, `vn`, `th`, `cn`, `hk`.
- Snapshot of the most-played songs chart: artist diversity, genre concentration, and the share of tracks released within 90 days of the feed's `updated` time.
- It is not a MAU, a subscriber count, or a history. A failed storefront stays null. It is not coded as "Apple Music does not exist there."

## Sources that are requested and do not enter the model

These are attempted because sync rates, brand-deal prices, ad costs, and territory recorded-music revenue are part of the question. If they do not come back as territorial numbers, the matching columns stay null.

| Source | URL | What we hoped for | What the pipeline does with it |
| --- | --- | --- | --- |
| IFPI industry data | https://www.ifpi.org/our-industry/industry-data/ | Territory recorded-music revenue | HTML is fetched. Recognized sentences, if any, are global (growth, streaming share, paid accounts). They are stored in the attempted-source cache and are not copied onto markets. |
| IFPI GMR PDF (2024 path) | https://www.ifpi.org/wp-content/uploads/2024/03/GMR2024_state_of_the_industry.pdf | Global Music Report tables | Logged when the path 404s or when a PDF is not parsed. No territory rows are mined from a PDF. |
| IFPI GMR PDF (2025 path) | https://www.ifpi.org/wp-content/uploads/2025/03/GMR2025_SOTI.pdf | Same | Same. The path is a guess, not an official stable URL. |
| Statista digital music, Korea | https://www.statista.com/outlook/dmo/digital-media/digital-music/south-korea | Streaming revenue / users | Not an open dataset. Failure is logged. |
| Statista social CPM | https://www.statista.com/statistics/273418/average-cpm-rates-of-social-media-platforms/ | CPM | No CPM is copied, including from a page that happens to load. |
| RIAJ digital sales | https://www.riaj.or.jp/e/data/annual/dg_all.html | Japan recorded-music digital totals | Logged on HTTP failure. Not parsed into a Japan-only feature that the other markets lack. |
| ASCAP royalty help | https://www.ascap.com/help/royalties-and-payment/payment/royalties | Sync / placement rate card | No machine-readable rate card is extracted. Film, TV, advertising, and game sync columns stay null. |
| Deezer chart | https://api.deezer.com/chart/0/tracks?limit=1 | Territory charts | The public chart used here is global. Track titles are not stored and are not assigned to markets. |

## Columns that stay null until a real series exists

`streaming_mau_observed`, `streaming_mau_growth_observed`, `streaming_subscribers_observed`, `sync_rate_film_usd`, `sync_rate_tv_usd`, `sync_rate_advertising_usd`, `sync_rate_game_usd`, `brand_deal_count_observed`, `brand_deal_avg_usd_observed`, `ad_cpm_usd_observed`, `ad_cpc_usd_observed`.

The stand-ins that do exist are named as proxies: `internet_user_cagr`, `channel_pageview_growth`, `channel_attention_share`, `social_pageview_growth`. Definitions are in `data/processed/feature_dictionary.json` after a feature build, and in `src/features/dictionary.py`.
