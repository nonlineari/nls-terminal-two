"""Sources we try because the brief asks for them, and do not turn into rows.

Global sentences from IFPI are stored as context. They are not copied onto
Korea, Japan, Indonesia, Vietnam, Thailand, China, or Hong Kong.
"""

from __future__ import annotations

import json
import logging
import re

from src.config import iso_now
from src.ingestion.failures import record_failure
from src.ingestion.http_util import fetch, fetch_limited

logger = logging.getLogger(__name__)

GLOBAL_PATTERNS = (
    re.compile(r"In \d{4}, global recorded music revenues grew by [0-9]+(?:\.[0-9]+)?%\."),
    re.compile(r"accounting for [0-9]+(?:\.[0-9]+)?% of global recorded music revenues"),
    re.compile(r"increasing by [0-9]+(?:\.[0-9]+)?% in \d{4}"),
    re.compile(r"there were [0-9,]+ million users of paid subscription accounts globally"),
)
TERRITORY_NAMES = ("Korea", "Japan", "Indonesia", "Vietnam", "Thailand", "Hong Kong", "China")


def _strip_html(raw: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _ifpi_html(run_id: str, url: str) -> dict:
    result = fetch_limited(url, max_bytes=250_000, timeout=30)
    if not result.ok or result.body is None:
        record_failure(
            run_id,
            source="ifpi_industry_data",
            url=url,
            reason=result.error,
            theme="recorded_music_revenue",
        )
        return {"source": "ifpi_industry_data", "url": url, "ok": False, "error": result.error}
    html = result.body.decode("utf-8", "replace")
    text = _strip_html(html)
    statements = []
    for pattern in GLOBAL_PATTERNS:
        statements.extend(pattern.findall(text))
    names_present = [name for name in TERRITORY_NAMES if name in text]
    record_failure(
        run_id,
        source="ifpi_industry_data",
        url=url,
        reason="no per-market revenue table extracted",
        theme="recorded_music_revenue",
        note=(
            "The HTML was fetched. Any recognized sentences are global, not territorial, "
            "and are not written into market rows. "
            f"Territory names in visible text: {names_present or 'none'}."
        ),
    )
    return {
        "source": "ifpi_industry_data",
        "url": result.url,
        "ok": True,
        "http_status": result.status,
        "used_in_model": False,
        "territory_rows": [],
        "global_statements_verbatim": statements,
        "territory_names_in_text": names_present,
        "html_chars": len(html),
    }


def _probe(run_id: str, source: str, url: str, theme: str, note: str) -> dict:
    logger.info("Probe %s", source)
    result = fetch_limited(url, max_bytes=80_000, timeout=30)
    content_type = result.content_type or ""
    is_pdf = "pdf" in content_type.lower() or url.lower().endswith(".pdf")
    if not result.ok:
        record_failure(run_id, source=source, url=url, reason=result.error, theme=theme, note=note)
        return {"source": source, "url": url, "ok": False, "error": result.error, "used_in_model": False}
    if is_pdf:
        record_failure(
            run_id,
            source=source,
            url=url,
            reason="PDF response was not parsed into territory rows",
            theme=theme,
            note=note,
        )
        return {
            "source": source,
            "url": result.url,
            "ok": False,
            "http_status": result.status,
            "used_in_model": False,
            "error": "unparsed PDF",
        }
    record_failure(
        run_id,
        source=source,
        url=result.url,
        reason="no machine-readable territory series extracted",
        theme=theme,
        note=note,
    )
    return {
        "source": source,
        "url": result.url,
        "ok": True,
        "http_status": result.status,
        "used_in_model": False,
        "territory_rows": [],
        "bytes": len(result.body or b""),
    }


def _deezer(run_id: str) -> dict:
    url = "https://api.deezer.com/chart/0/tracks?limit=1"
    result = fetch(url, timeout=30, max_attempts=2)
    if not result.ok or result.body is None:
        record_failure(run_id, source="deezer_chart", url=url, reason=result.error, theme="streaming_chart")
        return {"source": "deezer_chart", "url": url, "ok": False, "error": result.error, "used_in_model": False}
    try:
        payload = json.loads(result.body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        record_failure(run_id, source="deezer_chart", url=url, reason=str(exc), theme="streaming_chart")
        return {"source": "deezer_chart", "url": url, "ok": False, "error": str(exc), "used_in_model": False}
    record_failure(
        run_id,
        source="deezer_chart",
        url=url,
        reason="public chart endpoint is global, not a territory series",
        theme="streaming_chart",
        note="Track titles were not stored and were not assigned to markets.",
    )
    data = payload.get("data") or []
    return {
        "source": "deezer_chart",
        "url": url,
        "ok": True,
        "used_in_model": False,
        "shape": "global_chart",
        "tracks_returned": len(data) if isinstance(data, list) else None,
    }


def fetch_attempted(run_id: str) -> dict:
    attempts = [
        _ifpi_html(run_id, "https://www.ifpi.org/our-industry/industry-data/"),
        _probe(
            run_id,
            "ifpi_gmr2024_pdf",
            "https://www.ifpi.org/wp-content/uploads/2024/03/GMR2024_state_of_the_industry.pdf",
            "recorded_music_revenue",
            "A guessed Global Music Report path. A miss is logged, not backfilled.",
        ),
        _probe(
            run_id,
            "ifpi_gmr2025_pdf",
            "https://www.ifpi.org/wp-content/uploads/2025/03/GMR2025_SOTI.pdf",
            "recorded_music_revenue",
            "A guessed Global Music Report path. A miss is logged, not backfilled.",
        ),
        _probe(
            run_id,
            "statista_digital_music",
            "https://www.statista.com/outlook/dmo/digital-media/digital-music/south-korea",
            "streaming_market",
            "Statista outlook pages are not an open dataset.",
        ),
        _probe(
            run_id,
            "statista_social_cpm",
            "https://www.statista.com/statistics/273418/average-cpm-rates-of-social-media-platforms/",
            "ad_cost",
            "No CPM/CPC figures were copied from this page.",
        ),
        _probe(
            run_id,
            "riaj_digital",
            "https://www.riaj.or.jp/e/data/annual/dg_all.html",
            "recorded_music_revenue",
            "Recording Industry Association of Japan digital statistics page.",
        ),
        _probe(
            run_id,
            "ascap_royalty_help",
            "https://www.ascap.com/help/royalties-and-payment/payment/royalties",
            "sync_licensing",
            "Checked for a machine-readable placement rate card. None was extracted.",
        ),
        _deezer(run_id),
    ]
    return {
        "source": "attempted_reports",
        "pulled_at": iso_now(),
        "run_id": run_id,
        "used_in_model": False,
        "attempts": attempts,
    }
