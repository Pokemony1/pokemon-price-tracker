import os
import datetime
import numpy as np
import importlib
import pkgutil

from pokemon_price_tracker.google_sheet import connect_google_sheet
from pokemon_price_tracker.push_notification import send_push


def load_shops():
    """
    Loader alle shops fra pokemon_price_tracker/Shops/ der har funktionen get_products().
    Returnerer liste af tuples: (shop_label, module)
    """
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
    Sikrer headers:
      A1 = Product
      B1 = Median
      og for dagens dato 2 kolonner:
        "<date> Price"
        "<date> Shop"
    Returnerer (today_price_col, today_shop_col)
    """
    header = ws.row_values(1)

    # Sørg for Product og Median
    if len(header) < 1 or header[0] != "Product":
        ws.update_cell(1, 1, "Product")
    if len(header) < 2 or header[1] != "Median":
        ws.update_cell(1, 2, "Median")

    header = ws.row_values(1)

    price_header = f"{today_str} Price"
    shop_header = f"{today_str} Shop"

    # Find eksisterende pris-kolonne for i dag
    if price_header in header:
        price_col = header.index(price_header) + 1
        shop_col = price_col + 1

        # Hvis shop-header ikke matcher / mangler, fix den
        if len(header) < shop_col or header[shop_col - 1] != shop_header:
            ws.update_cell(1, shop_col, shop_header)

        return price_col, shop_col

    # Ellers tilføj 2 nye kolonner i slutningen
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
    # ENV fra GitHub Actions Secrets
    SHEET_NAME = os.getenv("SHEET_NAME", "PokemonPrices")
    PUSH_USER_KEY = os.getenv("PUSH_USER_KEY", "")
    PUSH_APP_TOKEN = os.getenv("PUSH_APP_TOKEN", "")

    # 1) Connect til sheet
    ws = connect_google_sheet(SHEET_NAME)

    # ✅ BEVIS: skriv LAST_RUN så du kan se den rammer det rigtige ark
    ws.update_cell(1, 10, "LAST_RUN")
    ws.update_cell(1, 11, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("Skrev LAST_RUN i arket")

    # 2) Dagens dato-kolonner
    today_str = datetime.datetime.now().strftime("%d-%m-%Y")
    today_price_col, today_shop_col = ensure_headers(ws, today_str)

    # 3) Load shops
    shops = load_shops()
    print("Shops loaded:", [s[0] for s in shops])

    # 4) Saml alle tilbud fra shops
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

    # 5) Vælg billigste pr. produkt (prioritér available=True)
    cheapest_today = {}
    for name, offers in all_offers.items():
        avail_offers = [o for o in offers if o[2] is True]
        use = avail_offers if avail_offers else offers
        cheapest = min(use, key=lambda t: t[0])
        cheapest_today[name] = cheapest  # (price, shop, available)

    # 6) Find eksisterende rækker i sheet
    row_map = get_product_row_map(ws)

    # 7) Tilføj nye produkter i bunden
    if cheapest_today:
        last_row = len(ws.col_values(1)) + 1
        new_rows = []
        for name in cheapest_today.keys():
            if name not in row_map:
                new_rows.append([name])
        if new_rows:
            ws.update(f"A{last_row}:A{last_row + len(new_rows) - 1}", new_rows)
            row_map = get_product_row_map(ws)

    # 8) Find alle pris-kolonner (col 3,5,7,... som ender med " Price")
    header = ws.row_values(1)
    price_cols = []
    for c in range(3, len(header) + 1, 2):
        if header[c - 1].endswith(" Price"):
            price_cols.append(c)

    # 9) Opdater dagens data + beregn median + push ved tilbud
    push_messages = []
    updates_count = 0

    for name, (price, shop_label, _available) in cheapest_today.items():
        r = row_map.get(name)
        if not r:
            continue

        # Skriv dagens pris og shop
        ws.update_cell(r, today_price_col, price)
        ws.update_cell(r, today_shop_col, shop_label)
        updates_count += 1

        # Hent historiske priser fra tidligere kolonner
        row_values = ws.row_values(r)
        hist_prices = []
        for c in price_cols:
            if c == today_price_col:
                continue
            if c - 1 < len(row_values):
                v = parse_float(row_values[c - 1])
                if v is not None:
                    hist_prices.append(v)

        prices_for_median = hist_prices + [price]
        median_price = float(np.median(prices_for_median)) if prices_for_median else price

        # Skriv median i kolonne B
        ws.update_cell(r, 2, median_price)

        # Push hvis dagens pris < median
        if price < median_price:
            push_messages.append(
                f"Tilbud: {name} → {price} kr ({shop_label}) | median: {median_price:.2f}"
            )

    # Send push beskeder
    for msg in push_messages:
        send_push(msg, PUSH_USER_KEY, PUSH_APP_TOKEN)

    print("Scan færdig. Produkter opdateret:", updates_count)
    print("Push sendt:", len(push_messages))


# ✅ VIGTIGT: Uden denne kører filen, men main() bliver aldrig kaldt
if __name__ == "__main__":
    main()
