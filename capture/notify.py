"""End-of-run signals: a heartbeat ping, and a Telegram message when sources failed.

Both are best-effort: a failed ping or message is printed and never raises, so
an alerting problem cannot turn a good capture run into a crash. Errors print
only the exception type, because the Telegram URL contains the bot token.
"""

import httpx

TIMEOUT_SECONDS = 10


def ping_heartbeat(url, failed, post=httpx.post):
    """Ping the healthcheck URL; append /fail when any source failed."""
    target = url.rstrip("/") + "/fail" if failed else url
    try:
        post(target, timeout=TIMEOUT_SECONDS).raise_for_status()
    except httpx.HTTPError as exc:
        print(f"heartbeat ping failed: {type(exc).__name__}")


def send_telegram(token, chat_id, failed, post=httpx.post):
    """One message listing the failed sources. Sends nothing when none failed."""
    if not failed:
        return
    text = f"kenya-macro-vintages: {len(failed)} source(s) failed: " + ", ".join(
        str(source_id) for source_id in failed
    )
    try:
        post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=TIMEOUT_SECONDS,
        ).raise_for_status()
    except httpx.HTTPError as exc:
        print(f"telegram alert failed: {type(exc).__name__}")
