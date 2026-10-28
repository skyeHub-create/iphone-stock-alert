
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from curl_cffi import requests as curl_requests

PRODUCT = "MK254VC/A"
POSTAL_CODE = "M5V0X3"

PRODUCT_URL = (
    "https://www.apple.com/ca/shop/buy-iphone/"
    "iphone-duo/7.6-inch-display-256gb-night-sky"
)

STORES = {
    "R120": "Yorkdale",
    "R121": "Eaton Centre",
    "R208": "Sherway Gardens",
    "R333": "Fairview",
    "R350": "Square One",
    "R515": "Markville Shopping Centre",
    "R429": "Upper Canada Mall",
    "R447": "Mapleview Centre",
}

STATE_FILE = Path("stock-state.json")

ENDPOINT = (
    "https://www.apple.com/ca/shop/retail/pickup-message"
)


def get_json(url):
    # Retry request errors (including HTTP 541) instead of failing on the
    # first response. A failed Apple request must never be treated as stock data.
    delays = (2, 5, 10)
    last_error = None

    for attempt in range(len(delays) + 1):
        try:
            response = curl_requests.get(
                url,
                impersonate="chrome",
                headers={
                    "Referer": PRODUCT_URL,
                    "Accept": "application/json",
                },
                timeout=25,
            )
            response.raise_for_status()
            return response.json()

        except (curl_requests.exceptions.RequestException, ValueError) as exc:
            last_error = exc
            if attempt >= len(delays):
                break
            delay = delays[attempt]
            print(
                f"Apple inventory request failed ({exc}); "
                f"retrying in {delay}s "
                f"({attempt + 1}/{len(delays)} retries).",
                flush=True,
            )
            time.sleep(delay)

    raise RuntimeError(
        f"Apple inventory request failed after {len(delays) + 1} attempts: "
        f"{last_error}"
    )


def check_stores():
    # Query each requested store directly so farther GTA locations aren't
    # omitted from Apple's limited list of nearby stores.
    found = {}

    for store_id in STORES:
        params = {
            "pl": "true",
            "parts.0": PRODUCT,
            "store": store_id,
        }
        url = ENDPOINT + "?" + urllib.parse.urlencode(params)
        data = get_json(url)

        try:
            stores = data["body"]["stores"]
        except (KeyError, TypeError):
            raise RuntimeError(
                f"Apple's response did not contain store data for {store_id}."
            )

        if not isinstance(stores, list) or not stores:
            raise RuntimeError(f"Apple returned no store record for {store_id}.")

        matched = False
        for store in stores:
            if store.get("storeNumber") != store_id:
                continue

            part = store.get("partsAvailability", {}).get(PRODUCT)
            if not isinstance(part, dict):
                break

            display = str(part.get("pickupDisplay", "")).strip().lower()
            if display == "available":
                found[store_id] = "available"
            elif display == "unavailable":
                found[store_id] = "unavailable"
            else:
                found[store_id] = "unknown"
            matched = True
            break

        # Never assume a missing or malformed record means unavailable.
        if not matched:
            found[store_id] = "unknown"

    return found


def send_telegram(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_ids = [os.environ["TELEGRAM_CHAT_ID"]]
    second_chat_id = os.environ.get("TELEGRAM_CHAT_ID_2", "").strip()
    if second_chat_id and second_chat_id not in chat_ids:
        chat_ids.append(second_chat_id)

    for chat_id in chat_ids:
        payload = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message,
        }).encode()

        request = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))

        if not result.get("ok"):
            raise RuntimeError(f"Telegram message failed for chat {chat_id}")


def main():
    previous = {}

    if STATE_FILE.exists():
        try:
            previous = json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            print("Previous state file is unreadable; treating state as new.")

    # If Apple's request fails, stop without overwriting previous state.
    # This prevents a blocked request from corrupting alert history.
    current = check_stores()

    for store_id, name in STORES.items():
        print(f"{name}: {current[store_id]}")

    alerts = []
    for store_id, name in STORES.items():
        if current[store_id] != "available":
            continue

        if previous.get(store_id) != "available":
            alerts.append((store_id, name))

    for store_id, name in alerts:
        send_telegram(
            "📱 Apple pickup availability reported\n\n"
            "iPhone Duo — 256GB Night Sky\n"
            f"Store: {name}\n"
            "Apple's pickup endpoint reports availability. "
            "Confirm on Apple's website before travelling.\n\n"
            f"{PRODUCT_URL}"
        )

    # Save only after the request and any notifications succeed.
    STATE_FILE.write_text(json.dumps(current, indent=2))

if __name__ == "__main__":
    main()
