
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from curl_cffi import requests as curl_requests

PRODUCT = "MK254VC/A"
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
    "R515": "Markville",
    "R429": "Upper Canada Mall",
    "R447": "Mapleview Centre",
}

STATE_FILE = Path("stock-state.json")


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


def check_store(store_id):
    params = {
        "pl": "true",
        "mts.0": "regular",
        "parts.0": PRODUCT,
        "store": store_id,
    }

    url = (
        "https://www.apple.com/ca/shop/retail/pickup-message?"
        + urllib.parse.urlencode(params)
    )

    data = get_json(url)

    stores = data.get("body", {}).get("stores", [])

    for store in stores:
        if store.get("storeNumber") != store_id:
            continue

        part = store.get("partsAvailability", {}).get(PRODUCT)

        if not isinstance(part, dict):
            return "unknown"

        display = str(part.get("pickupDisplay", "")).lower()

        if display == "available":
            return "available"

        if display == "unavailable":
            return "unavailable"

    return "unknown"


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
        previous = json.loads(STATE_FILE.read_text())

    current = {}
    confirmed = []

    for store_id, name in STORES.items():
        try:
            status = check_store(store_id)
            print(f"{name}: {status}")
        except Exception as error:
            # Errors must never be interpreted as out of stock.
            print(f"{name}: unknown (check failed: {error})")
            status = "unknown"

        current[store_id] = status

        if status == "available":
            confirmed.append((store_id, name))

    for store_id, name in confirmed:
        if previous.get(store_id) == "available":
            continue

        send_telegram(
            "📱 Apple pickup availability reported\n\n"
            "iPhone Duo — 256GB Night Sky\n"
            f"Store: {name}\n"
            "Apple's pickup endpoint reports availability. "
            "Confirm at checkout before travelling.\n\n"
            f"{PRODUCT_URL}"
        )

    STATE_FILE.write_text(json.dumps(current, indent=2))


if __name__ == "__main__":
    main()
