"""Read one private snapshot without changing prices, dates, or decimal strings."""
import json
import urllib.error
import urllib.request

API_URL = "https://assets.stock-frankhong.com/v1/valuation"
MAX_BYTES = 2_000_000


class SnapshotError(RuntimeError):
    """An error safe to return to the authenticated client."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the provider credential to a redirect destination.
        raise urllib.error.HTTPError(req.full_url, code, "Redirect rejected", headers, fp)


def fetch_snapshot(api_key: str) -> dict:
    request = urllib.request.Request(API_URL, method="GET", headers={
        "Accept": "application/json",
        "Authorization": "Bearer " + api_key,
        "User-Agent": "frank-ashare-mcp/0.2.0",
    })
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise SnapshotError("Valuation response exceeds the 2 MB limit.")
            if not response.headers.get("Content-Type", "").lower().startswith("application/json"):
                raise SnapshotError("Provider did not return JSON.")
    except urllib.error.HTTPError as exc:
        messages = {
            401: "HTTP 401: Provider API key required or rejected.",
            429: "HTTP 429: Provider rate limit reached.",
            503: "HTTP 503: No valid valuation snapshot available.",
        }
        raise SnapshotError(messages.get(exc.code, f"Provider HTTP {exc.code}; no valuation returned.")) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SnapshotError("Private A-share API connection failed; no valuation returned.") from None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise SnapshotError("Provider returned invalid JSON.") from None
    if not isinstance(data, dict):
        raise SnapshotError("Provider JSON response is not an object.")
    for field in ("valuation_date", "freshness", "usable_for_current_report", "positions", "totals", "coverage"):
        if field not in data:
            raise SnapshotError(f"Provider snapshot missing required report field: {field}.")
    return data
