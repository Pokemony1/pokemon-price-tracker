import os
import datetime
import numpy as np
import importlib
import pkgutil
import gspread


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
    # --------- HARD TEST / DEBUG (så du ALTID kan se output) ----------
    print("STARTER SCRIPT")
    sheet_name = os.getenv("SHEET_NAME", "PokemonPrices")
    print("SHEET_NAME =", sheet_name)

    # Push env (må gerne være tom under test)
    push_user_key = os.getenv("PUSH_USER_KEY", "")
    push_app_token = os.getenv("PUSH_APP_TOKEN", "")

    # Connect
    ws = connect_google_sheet()
    print("CONNECTED TO GOOGLE SHEET OK")

    # Skriv tydeligt bevis i arket
    ws.update_cell(1, 1, "HELLO_FROM_GITHUB_ACTIONS")
    ws.update_cell(1, 2, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("SKREV HELLO + TIMESTAMP I A1/B1 OK")
    # ---------------------------------------------------------------

    # Dagens dato-kolonner
    today_str = datetime.datetime.now().strftime("%d-%m-%Y")
    today_price_col, today_shop_col = ensure_headers(ws, today_str)
    print("HEADERS OK:", today_price_col, today_shop_col)

    # Load shops
    shops = load_shops()
    print("Shops loaded:", [s[0] for s in shops])

    # Saml alle tilbud fra shops
    # all_offers[name] = list of (price, shop_label, available)
    all_offers = {}

    for shop_label, shop_module in shops:
        try:
            products = shop_module.get_products()
            print(f"{shop_label}: hentede {len(products)} produkter")
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

    print("TOTAL unikke produkter fundet:", len(all_offers))

    # Vælg billigste pr. produkt (prioritér available=True)
    cheapest_today = {}
    for name, offers in all_offers.items():
        avail_offers = [o for o in offers if o[2] is True]
        use = avail_offers if avail_offers else offers
        cheapest = min(use, key=lambda t: t[0])
        cheapest_today[name] = cheapest  # (price, shop, available)

    # Find eksisterende rækker i sheet
    row_map = get_product_row_map(ws)

    # Tilføj nye produkter i bunden
    if cheapest_today:
        last_row = len(ws.col_values(1)) + 1
        new_rows = []
        for name in cheapest_today.keys():
            if name not in row_map:
                new_rows.append([name])
        if new_rows:
            ws.update(f"A{last_row}:A{last_row + len(new_rows) - 1}", new_rows)
            row_map = get_product_row_map(ws)
            print("Tilføjede nye produkter:", len(new_rows))

    # Find alle pris-kolonner (col 3,5,7,... som ender med " Price")
    header = ws.row_values(1)
    price_cols = []
    for c in range(3, len(header) + 1, 2):
        if header[c - 1].endswith(" Price"):
            price_cols.append(c)

        # 9) Opdater dagens data + beregn median + push ved tilbud (BATCH)
    push_messages = []
    updates_count = 0

    # For at undgå 429-quota: byg én stor "values" matrix og skriv med ws.update()
    max_row = max(row_map.values()) if row_map else 1
    max_col = max(today_shop_col, 2)  # vi skriver mindst til kolonne 2 (Median)

    # Hent hele området A1..(max_row,max_col) én gang
    # (det er hurtigere og giver os historik uden mange API-kald)
    all_values = ws.get_all_values()
    # Sørg for at all_values har nok rækker/kolonner
    while len(all_values) < max_row:
        all_values.append([])
    for r_i in range(len(all_values)):
        row = all_values[r_i]
        if len(row) < max_col:
            row.extend([""] * (max_col - len(row)))

    # Pris-kolonner til median (col 3,5,7,...) som ender med " Price"
    header = all_values[0] if all_values else []
    price_cols = []
    for c in range(3, len(header) + 1, 2):
        if header[c - 1].endswith(" Price"):
            price_cols.append(c)

    for name, (price, shop_label, _available) in cheapest_today.items():
        r = row_map.get(name)
        if not r:
            continue

        # Skriv dagens pris + shop i vores lokale matrix
        all_values[r - 1][today_price_col - 1] = str(price)
        all_values[r - 1][today_shop_col - 1] = str(shop_label)

        # Historiske priser (fra matrix) -> median
        hist_prices = []
        for c in price_cols:
            if c == today_price_col:
                continue
            v = all_values[r - 1][c - 1] if c - 1 < len(all_values[r - 1]) else ""
            try:
                fv = float(v) if v != "" else None
            except Exception:
                fv = None
            if fv is not None:
                hist_prices.append(fv)

        prices_for_median = hist_prices + [float(price)]
        median_price = float(np.median(prices_for_median)) if prices_for_median else float(price)

        # Skriv median i kolonne B
        all_values[r - 1][1] = f"{median_price:.6g}"

        updates_count += 1

        # Push hvis dagens pris < median
        if float(price) < median_price:
            push_messages.append(
                f"Tilbud: {name} → {price} kr ({shop_label}) | median: {median_price:.2f}"
            )

    # Skriv hele området tilbage i ÉT kald (A1..)
    # NB: gspread update() forventer values først i nyere versioner
    ws.update(values=all_values[:max_row], range_name=f"A1:{gspread.utils.rowcol_to_a1(max_row, max_col)}")
