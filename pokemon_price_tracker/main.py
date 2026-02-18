import os
import datetime
import numpy as np
import importlib
import pkgutil

from pokemon_price_tracker.google_sheet import connect_google_sheet
from pokemon_price_tracker.push_notification import send_push


def load_shops():
    shops = []
    package_path = os.path.join(os.path.dirname(__file__), "Shops")
    package_name = "pokemon_price_tracker.Shops"

    for _, module_name, _ in pkgutil.iter_modules([package_path]):
        module = importlib.import_module(f"{package_name}.{module_name}")
        if hasattr(module, "get_products"):
            shop_label = getattr(module, "SHOP_NAME", module_name)
            shops.append((shop_label, module))
    return shops


def ensure_headers(ws, today_str):
    """
    Sørger for at header row har:
    A1 = Product
    B1 = Median
    og dagens 2 kolonner: "<date> Price" og "<date> Shop"
    Returnerer (today_price_col, today_shop_col)
    """
    header = ws.row_values(1)

    # Sikrer minimum A/B headers
    if len(header) < 1 or header[0] != "Product":
        ws.update_cell(1, 1, "Product")
    if len(header) < 2 or header[1] != "Median":
        ws.update_cell(1, 2, "Median")

    header = ws.row_values(1)

    price_header = f"{today_str} Price"
    shop_header = f"{today_str} Shop"

    # Find eksisterende
    if price_header in header:
        price_col = header.index(price_header) + 1
        shop_col = price_col + 1
        # Hvis shop kolonnen mangler/ikke matcher, fix den
        if len(header) < shop_col or header[shop_col - 1] != shop_header:
            ws.update_cell(1, shop_col, shop_header)
        return price_col, shop_col

    # Ellers tilføj til sidst
    price_col = len(header) + 1
    shop_col = price_col + 1
    ws.update_cell(1, price_col, price_header)
    ws.update_cell(1, shop_col, shop_header)
    return price_col, shop_col


def get_product_row_map(ws):
    """
    Læser kolonne A og returnerer dict: product_name -> row_index
    """
    col = ws.col_values(1)
    mapping = {}
    for idx, name in enumerate(col[1:], start=2):  # skip header
        if name:
            mapping[name] = idx
    return mapping


def parse_float(x):
    try:
        return float(x)
    except Exception:
        return None


def main():
    SHEET_NAME = os.getenv("SHEET_NAME", "PokemonPrices")
    PUSH_USER_KEY = os.getenv("PUSH_USER_KEY", "")
    PUSH_APP_TOKEN = os.getenv("PUSH_APP_TOKEN", "")

    ws = connect_google_sheet(SHEET_NAME)

    today_str = datetime.datetime.now().strftime("%d-%m-%Y")
    today_price_col, today_shop_col = ensure_headers(ws, today_str)

    shops = load_shops()
    print("Shops loaded:", [s[0] for s in shops])

    # Saml alle tilbud fra shops
    # all_offers[name] = list of (price, shop_label, available)
    all_offers = {}

    for shop_label, shop_module in shops:
        try:
            products = shop_module.get_products()
        except Exception as e:
            print(f"Fejl i shop {shop_label}: {e}")
            continue

        for p in products:
            name = (p.get("name") or "").strip()
            if not name:
                continue
            price = parse_float(p.get("price"))
            if price is None:
                continue
            available = bool(p.get("available", True))

            all_offers.setdefault(name, []).append((price, shop_label, available))

    # Vælg billigste pr. produkt (kun available=True hvis muligt)
    cheapest_today = {}
    for name, offers in all_offers.items():
        avail_offers = [o for o in offers if o[2] is True]
        use = avail_offers if avail_offers else offers
        cheapest = min(use, key=lambda t: t[0])
        cheapest_today[name] = cheapest  # (price, shop, available)

    # Find eksisterende rækker i sheet
    row_map = get_product_row_map(ws)

    # Tilføj nye produkter (append i bunden)
    if cheapest_today:
        last_row = len(ws.col_values(1)) + 1
        new_rows = []
        for name in cheapest_today.keys():
            if name not in row_map:
                new_rows.append([name])  # kun kol A
        if new_rows:
            ws.update(f"A{last_row}:A{last_row + len(new_rows) - 1}", new_rows)
            # rebuild map
            row_map = get_product_row_map(ws)

    # For median: pris-kolonner starter ved col=3 og ligger hver 2. kolonne (price, shop, price, shop, ...)
    header = ws.row_values(1)
    price_cols = []
    for c in range(3, len(header) + 1, 2):
        if header[c - 1].endswith(" Price"):
            price_cols.append(c)

    # Opdater dagens data + median
    updates = []
    push_messages = []

    for name, (price, shop_label, _available) in cheapest_today.items():
        r = row_map.get(name)
        if not r:
            continue

        # skriv dagens pris + shop
        updates.append(((r, today_price_col), price))
        updates.append(((r, today_shop_col), shop_label))

        # hent historiske priser fra sheet (inkl. dagens, som vi har i 'price')
        row_values = ws.row_values(r)

        hist_prices = []
        for c in price_cols:
            if c == today_price_col:
                continue
            if c - 1 < len(row_values):
                v = parse_float(row_values[c - 1])
                if v is not None:
                    hist_prices.append(v)

        # median beregnes på hist + dagens
        prices_for_median = hist_prices + [price]
        median_price = float(np.median(prices_for_median)) if prices_for_median else price

        updates.append(((r, 2), median_price))

        if price < median_price:
            push_messages.append(f"Tilbud: {name} → {price} kr ({shop_label}) | median: {median_price:.2f}")

    # Batch update (mindre API spam)
    for (r, c), val in updates:
        ws.update_cell(r, c, val)

    # Push
    for msg in push_messages:
        send_push(msg, PUSH_USER_KEY, PUSH_APP_TOKEN)

    print("Scan færdig. Produkter opdateret:", len(cheapest_today))
    print("Push sendt:", len(push_messages))


if __name__ == "__main__":
    main()
