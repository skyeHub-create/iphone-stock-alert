
import json
import os
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
    "https://www.apple.com/ca/shop/fulfillment-messages"
)


def get_json(url):
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


def check_stores():
    params = {
        "fae": "true",
        "pl": "true",
        "mts.0": "regular",
        "parts.0": PRODUCT,
        "location": POSTAL_CODE,
    }

    url = ENDPOINT + "?" + urllib.parse.urlencode(params)
    data = get_json(url)

    try:
        stores = data["body"]["content"]["pickupMessage"]["stores"]
    except (KeyError, TypeError):
        raise RuntimeError(
            "Apple's response did not contain the expected store data."
        )

    if not isinstance(stores, list) or not stores:
        raise RuntimeError("Apple returned no store records.")

    found = {}
    for store in stores:
        store_id = store.get("storeNumber")
        if store_id not in STORES:
            continue

        part = store.get("partsAvailability", {}).get(PRODUCT)
        if not isinstance(part, dict):
            continue

        display = str(part.get("pickupDisplay", "")).strip().lower()

        if display == "available":
            found[store_id] = "available"
        elif display == "unavailable":
            found[store_id] = "unavailable"
        else:
            found[store_id] = "unknown"

    # Missing stores remain unknown; never assume they're out of stock.
    for store_id in STORES:
        found.setdefault(store_id, "unknown")

    return found


def send_telegram(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

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
        raise RuntimeError("Telegram message failed")


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
