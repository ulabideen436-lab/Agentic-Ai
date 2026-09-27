"""Build the generated parts of the corpus from a POS catalogue export.

Writes:
  data/corpus/products/*.md      one document per product
  data/structured/prices_stock.csv   retail price + stock status (no cost data)
  data/structured/orders.csv     200 synthetic orders built on those products

Then run scripts/stage.py, which stages everything into data/raw/ and writes
data/manifest.csv.

Usage:
  python scripts/build_corpus.py --catalogue <path to products-export.json>

Only the retail price, name and stock status leave the export. Cost price,
wholesale price and supplier are read but never written anywhere.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus"
STRUCTURED = ROOT / "data" / "structured"
TODAY = date(2026, 9, 26)

# Ported from the POS app's categorize.ts. First match wins; the order is the
# design: a word naming what the item IS beats a word for packing or bed size.
#
# One deliberate difference from the POS: "POLY BAG" names a blanket sold in
# plastic packing (MIMOSA POLY BAG, Rs 9,500), not a storage bag, so it is a
# blanket here. The POS files it under bags.
CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("blanket", re.compile(r"POLY BAG")),
    ("bag", re.compile(r"\bBAG\b")),
    ("jae_namaz", re.compile(r"JAE ?NAMAZ")),
    ("dasterkhawan", re.compile(r"DASTERKHAWAN")),
    ("sofa_cover", re.compile(r"SOFA COVER")),
    ("mattress_cover", re.compile(r"MATTRESS COVER")),
    ("razai_cover", re.compile(r"RAZAI COVER|RAZI COVER")),
    ("razai", re.compile(r"\bRAZAI\b|\bRAZI\b")),
    ("gadda", re.compile(r"GADDA")),
    ("bed_cover", re.compile(r"BED COVER")),
    ("bed_sheet", re.compile(r"BEDSHEET|BED ?SHEETS?\b")),
    ("blanket", re.compile(r"BLANKET")),
    ("curtain", re.compile(r"CURTAIN|PARDA")),
    ("pillow", re.compile(r"TAKIYA")),
    ("velvet", re.compile(r"VELVET")),
    ("blanket", re.compile(r"CLOUDY")),
    ("bed_sheet", re.compile(r"\bBOX\b")),
    ("bed_sheet", re.compile(r"SINGLE BED|DOUBLE BED")),
]

# How many product pages per type. Velvet is left out: the catalogue does not
# say whether those pieces are razai covers or sheets, and a page that guesses
# would answer questions wrongly.
QUOTA = {
    "bed_sheet": 16, "blanket": 16, "bed_cover": 8, "razai": 8,
    "razai_cover": 3, "gadda": 5, "jae_namaz": 5, "dasterkhawan": 3,
    "mattress_cover": 3, "sofa_cover": 2, "curtain": 2, "pillow": 1, "bag": 3,
}

TYPE_INFO = {
    "bed_sheet": dict(label="Bed sheet", urdu="بیڈ شیٹ / چادر", roman="bedsheet, bed sheet, chadar, chaddar, chader",
                      size_guide="Bed sheet sizes", care="Washing bed sheets"),
    "blanket": dict(label="Blanket", urdu="کمبل", roman="kambal, kumbal, blanket, blankit, cloudy, claudy",
                    size_guide="Blanket sizes (including cloudy blankets)", care="Caring for cloudy, mink and fleece blankets"),
    "bed_cover": dict(label="Bed cover set", urdu="بیڈ کور", roman="bed cover, bedcover, bad cover",
                      size_guide="Bed cover set sizes and contents", care="Washing bed sheets"),
    "razai": dict(label="Razai", urdu="رضائی", roman="razai, rajai, rezai, rzai, razi",
                  size_guide="Razai and razai cover sizes", care="Caring for a razai"),
    "razai_cover": dict(label="Razai cover", urdu="رضائی کور", roman="razai cover, rajai cover, rezai cover, razi cover",
                        size_guide="Razai and razai cover sizes", care="Caring for velvet razai covers"),
    "gadda": dict(label="Gadda", urdu="گدا", roman="gadda, gaddha, gadha, gaddah, gada",
                  size_guide="Gadda sizes", care="Caring for a gadda"),
    "jae_namaz": dict(label="Jae namaz", urdu="جائے نماز", roman="jae namaz, janamaz, jaenamaz, jai namaz, musalla",
                      size_guide="Jae namaz (prayer mat) sizes", care="Caring for jae namaz and dasterkhawan"),
    "dasterkhawan": dict(label="Dasterkhawan", urdu="دسترخوان", roman="dasterkhawan, dastarkhwan, dastarkhan, dasterkhan",
                         size_guide="Dasterkhawan sizes", care="Caring for jae namaz and dasterkhawan"),
    "mattress_cover": dict(label="Mattress cover", urdu="میٹرس کور", roman="mattress cover, matress cover, gadde ka cover",
                           size_guide="Mattress cover sizes", care="Washing bed sheets"),
    "sofa_cover": dict(label="Sofa cover", urdu="صوفہ کور", roman="sofa cover, sofa kavar, sofay ka cover",
                       size_guide="Sofa cover and gol takiya sizes", care="Caring for curtains and sofa covers"),
    "curtain": dict(label="Curtain", urdu="پردہ", roman="parda, pardah, parday, parde, curtain",
                    size_guide="Curtain (parda) sizes", care="Caring for curtains and sofa covers"),
    "pillow": dict(label="Pillow", urdu="تکیہ", roman="takiya, takia, takya, gol takiya",
                   size_guide="Sofa cover and gol takiya sizes", care="Caring for curtains and sofa covers"),
    "bag": dict(label="Storage bag", urdu="بیگ", roman="bag, blanket bag, razai bag",
                size_guide="", care="Storing winter bedding in summer"),
}

# Measurements per type and size word, matching the size guides.
SIZES = {
    ("bed_sheet", "single"): "60 × 90 inches (152 × 229 cm)",
    ("bed_sheet", "double"): "90 × 100 inches (229 × 254 cm)",
    ("bed_sheet", "king"): "108 × 108 inches (274 × 274 cm)",
    ("blanket", "single"): "63 × 87 inches (160 × 220 cm)",
    ("blanket", "double"): "87 × 94 inches (220 × 240 cm)",
    ("blanket", "king"): "94 × 102 inches (240 × 260 cm)",
    ("blanket", "baby_small"): "30 × 40 inches (76 × 102 cm)",
    ("blanket", "baby_large"): "40 × 55 inches (102 × 140 cm)",
    ("razai", "single"): "60 × 90 inches (152 × 229 cm)",
    ("razai", "double"): "90 × 100 inches (229 × 254 cm)",
    ("razai_cover", "single"): "62 × 92 inches (157 × 234 cm)",
    ("razai_cover", "double"): "92 × 102 inches (234 × 259 cm)",
    ("gadda", "single"): "36 × 72 inches (3 × 6 ft), 3 inches thick",
    ("gadda", "double"): "54 × 78 inches (4.5 × 6.5 ft), 3–4 inches thick",
    ("bed_cover", "double"): "Bed cover and bed sheet 90 × 100 inches; pillow covers 18 × 28 inches",
    ("mattress_cover", "single"): "Fits a mattress of 36–42 × 78 inches, up to 8 inches deep",
    ("mattress_cover", "double"): "Fits a mattress of 60–72 × 78 inches, up to 8 inches deep",
    ("jae_namaz", "standard"): "70 × 110 cm",
    ("jae_namaz", "large"): "80 × 120 cm",
    ("dasterkhawan", "standard"): "36 × 54 inches (91 × 137 cm)",
    ("curtain", "standard"): "54 inches wide × 90 inches long",
    ("sofa_cover", "standard"): "5-seater: one 3-seater (70–90 in wide) and two 1-seaters (30–45 in wide)",
    ("pillow", "standard"): "7 inches across × 20 inches long",
}

# Delivery charges and zones, matching the shipping documents. Zone A (the
# shop's own city) is left out of synthetic orders until the city is filled in.
ZONES = {
    "B": ["Lahore", "Karachi", "Islamabad", "Rawalpindi", "Faisalabad", "Multan",
          "Gujranwala", "Sialkot", "Peshawar", "Hyderabad", "Quetta"],
    "C": ["Sahiwal", "Okara", "Sargodha", "Bahawalpur", "Jhang", "Kasur", "Sheikhupura",
          "Mardan", "Abbottabad", "Sukkur", "Larkana", "Dera Ghazi Khan"],
    "D": ["Gilgit", "Skardu", "Turbat", "Chitral"],
}
ZONE_CHARGE = {"B": 250, "C": 250, "D": 400}
FREE_DELIVERY_FROM = 10_000


def categorise(name: str) -> str | None:
    upper = name.upper()
    for category, pattern in CATEGORY_RULES:
        if pattern.search(upper):
            return category
    return None


def normalise(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().upper()


def title_case(name: str) -> str:
    keep_upper = {"ABC", "NB", "HJK", "HBK", "PK", "DG", "SP", "JR", "USA", "UNO-1"}
    words = []
    for word in normalise(name).split(" "):
        if word in keep_upper or re.fullmatch(r"\d+PCS|\d+", word):
            words.append(word.replace("PCS", " pcs") if "PCS" in word else word)
        else:
            words.append(word.capitalize())
    return " ".join(words)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def size_word(product_type: str, name: str) -> str | None:
    n = normalise(name)
    if product_type == "jae_namaz":
        if re.search(r"80\s*\*\s*120", n):
            return "large"
        return "standard"
    if product_type in {"dasterkhawan", "curtain", "sofa_cover", "pillow"}:
        return "standard"
    if product_type == "blanket" and "BABY" in n:
        return "baby_large" if "LARGE" in n else "baby_small"
    if "KING" in n and "ESKIMO" not in n:
        return "king"
    if "SINGLE" in n:
        return "single"
    if "DOUBLE" in n:
        return "double"
    if product_type == "bed_cover":
        return "double"
    return None


def pieces(name: str) -> int | None:
    match = re.search(r"(\d+)\s*PCS", normalise(name))
    return int(match.group(1)) if match else None


def contents(product_type: str, name: str, size: str | None) -> str:
    n = normalise(name)
    count = pieces(name)
    if product_type == "bed_sheet":
        if count == 3:
            return "3 pieces: 1 bed sheet and 2 pillow covers."
        if count:
            return f"{count} pieces. The exact pieces are not yet confirmed by the shop."
        if "BOX" in n:
            return "Boxed bed sheet set. The number of pieces is not yet confirmed by the shop."
        if size == "single":
            return "1 single bed sheet and 1 pillow cover."
        return "1 bed sheet and 2 pillow covers."
    if product_type == "bed_cover":
        if count == 4 or count is None:
            return "4 pieces: 1 quilted bed cover, 1 bed sheet and 2 pillow covers."
        return (f"{count} pieces: the 4-piece contents (bed cover, bed sheet, 2 pillow covers) plus "
                "cushion covers and extra pillow covers. The full list is not yet confirmed by the shop.")
    if product_type == "razai":
        if count:
            return f"{count}-piece razai set. The full list of pieces is not yet confirmed by the shop."
        return "1 razai. The cover is sold separately."
    if product_type == "sofa_cover" and count:
        return f"{count} pieces, for a 5-seater sofa (one 3-seater and two 1-seaters)."
    if product_type == "dasterkhawan":
        return "1 dasterkhawan. Also sold in packs of 12."
    label = TYPE_INFO[product_type]["label"].lower()
    return f"1 {label}."


def fabric(product_type: str, name: str) -> str:
    n = normalise(name)
    if "COTTON" in n or "SUTI" in n:
        return "Cotton."
    if "MALAI" in n:
        return "Malai velvet."
    if "VELVET" in n:
        return "Velvet."
    if "SILK" in n:
        return "Polyester with a silky finish (not pure silk)."
    if "JERSEY" in n or "JERSI" in n:
        return "Jersey (stretch knit)."
    if "SHERPA" in n:
        return "Sherpa."
    if "FLEES" in n or "FLEECE" in n:
        return "Fleece."
    if product_type == "blanket" and "CLOUDY" in n:
        return "Cloudy (thick, soft polyester)."
    if product_type == "blanket" and "BABY" in n:
        return "Soft polyester (mink or plush)."
    if product_type == "jae_namaz":
        return "Velvet-pile prayer mat."
    return "Not yet recorded by the shop."


def stock_status(quantity: float | None) -> str:
    if quantity is None:
        return "unknown"
    if quantity <= 0:
        return "out_of_stock"
    if quantity <= 5:
        return "low_stock"
    return "in_stock"


STOCK_TEXT = {
    "in_stock": "In stock",
    "low_stock": "Low stock (5 or fewer left)",
    "out_of_stock": "Out of stock. See the stock and restocking policy.",
    "unknown": "Not recorded",
}


def load_catalogue(path: Path) -> tuple[list[dict], list[str]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    products, seen, duplicates = [], set(), []
    for row in rows:
        name = normalise(row.get("name", ""))
        product_type = categorise(name)
        if not name or product_type is None:
            continue
        # Same name twice with different prices is exactly the contradictory
        # duplicate the corpus spec warns about: keep the first, report the rest.
        if name in seen:
            duplicates.append(name)
            continue
        seen.add(name)
        try:
            price = round(float(row.get("retail_price") or 0))
        except ValueError:
            price = 0
        quantity = row.get("stock_quantity")
        products.append({
            "sku": row["id"],
            "name": name,
            "title": title_case(name),
            "product_type": product_type,
            "retail_price": price,
            "stock_status": stock_status(float(quantity) if quantity is not None else None),
            "total_sold": int(row.get("total_sold") or 0),
        })
    return products, duplicates


def select_for_pages(products: list[dict]) -> list[dict]:
    chosen = []
    for product_type, quota in QUOTA.items():
        pool = [p for p in products if p["product_type"] == product_type and p["retail_price"] > 0]
        # Best sellers first, then spread across the price range for variety.
        pool.sort(key=lambda p: (-p["total_sold"], p["retail_price"]))
        best = pool[: quota // 2]
        rest = sorted((p for p in pool if p not in best), key=lambda p: p["retail_price"])
        need = quota - len(best)
        if rest and need > 0:
            step = max(1, len(rest) / need)
            best += [rest[int(i * step)] for i in range(min(need, len(rest)))]
        chosen += best
    return chosen


def product_page(p: dict) -> str:
    info = TYPE_INFO[p["product_type"]]
    size = size_word(p["product_type"], p["name"])
    measurement = SIZES.get((p["product_type"], size)) if size else None
    size_label = {"baby_small": "small baby", "baby_large": "large baby"}.get(size, size)
    size_line = (f"{size_label.capitalize()}: {measurement}." if measurement
                 else "Not stated in the product name. Ask the shop, or see the size guide.")
    # Where scripts/stage.py puts the staged copy, which is what citations trace to.
    rel = f"data/raw/products/{slug(p['title'])}-{p['sku']}.md"
    guide = f"See \"{info['size_guide']}\"." if info["size_guide"] else ""
    return f"""---
doc_id: product-{p['sku']}-001
title: "{p['title']}"
doc_type: product
origin: pos-catalogue
language: mixed
product_type: {p['product_type']}
last_updated: {TODAY.isoformat()}
visibility: public
contains_personal_data: false
raw_path: {rel}
verified: false
sku: {p['sku']}
---

# {p['title']}

- **Product name (English):** {p['title']} ({info['label'].lower()})
- **Product name (Urdu script):** {info['urdu']} — {p['title']}
- **Product name (Roman Urdu):** {p['title'].lower()} {info['label'].lower()}; {info['roman']}
- **Category:** {info['label']}
- **Size and measurements:** {size_line} {guide}
- **Fabric / material:** {fabric(p['product_type'], p['name'])}
- **Thread count or GSM:** Not yet recorded by the shop.
- **Colours available:** Current designs are shared as photos on WhatsApp.
- **Price:** Rs {p['retail_price']:,} on {TODAY.isoformat()}. The live price list is the final word on price.
- **What's included:** {contents(p['product_type'], p['name'], size)}
- **Care:** See "{info['care']}".
- **Stock status:** {STOCK_TEXT[p['stock_status']]} on {TODAY.isoformat()}.
"""


def write_products(chosen: list[dict]) -> None:
    folder = CORPUS / "products"
    for old in folder.glob("*.md"):
        old.unlink()
    for p in chosen:
        (folder / f"{slug(p['title'])}-{p['sku']}.md").write_text(product_page(p), encoding="utf-8")


def write_prices(products: list[dict]) -> None:
    with (STRUCTURED / "prices_stock.csv").open("w", newline="", encoding="utf-8") as f:
        # LF, so the file's sha256 in data/manifest.csv survives a git checkout.
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["sku", "name", "product_type", "retail_price", "stock_status", "as_of"])
        for p in products:
            writer.writerow([p["sku"], p["title"], p["product_type"], p["retail_price"],
                             p["stock_status"], TODAY.isoformat()])


def write_orders(products: list[dict], count: int = 200) -> None:
    """Synthetic orders. No real customer appears here, by construction."""
    rng = random.Random(42)
    sellable = [p for p in products if p["retail_price"] > 0]
    customers = [f"C{i:04d}" for i in range(1, 61)]
    home_city = {c: rng.choice([(z, city) for z, cities in ZONES.items() for city in cities])
                 for c in customers}
    start = date(2026, 6, 1)
    rows = []
    for i in range(1, count + 1):
        customer = rng.choice(customers)
        zone, city = home_city[customer]
        ordered = start + timedelta(days=rng.randint(0, (TODAY - start).days))
        age = (TODAY - ordered).days
        if age <= 1:
            status = rng.choice(["pending_confirmation", "confirmed"])
        elif age <= 3:
            status = rng.choice(["confirmed", "packed", "dispatched"])
        elif age <= 8:
            status = rng.choices(["dispatched", "delivered", "cancelled"], [4, 5, 1])[0]
        else:
            status = rng.choices(["delivered", "returned", "refused", "cancelled"], [85, 5, 5, 5])[0]
        items = rng.sample(sellable, k=rng.choice([1, 1, 1, 2, 2, 3]))
        lines = [(p, rng.choice([1, 1, 1, 2])) for p in items]
        subtotal = sum(p["retail_price"] * qty for p, qty in lines)
        payment = rng.choices(["cod", "bank_transfer", "easypaisa", "jazzcash"], [6, 2, 1, 1])[0]
        if subtotal > 25_000 and payment == "cod":
            payment = "cod_with_advance"
        delivery = 0 if subtotal >= FREE_DELIVERY_FROM and zone != "D" else ZONE_CHARGE[zone]
        shipped = status in {"dispatched", "delivered", "returned", "refused"}
        rows.append({
            "order_id": f"ZY-{26000 + i}",
            "customer_id": customer,
            "visibility": f"customer:{customer}",
            "order_date": ordered.isoformat(),
            "status": status,
            "items": "; ".join(f"{p['sku']} x{qty} ({p['title']})" for p, qty in lines),
            "subtotal": subtotal,
            "delivery_charge": delivery,
            "total": subtotal + delivery,
            "payment_method": payment,
            "city": city,
            "zone": zone,
            "tracking_number": f"TCS{rng.randint(10**9, 10**10 - 1)}" if shipped else "",
        })
    with (STRUCTURED / "orders.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalogue", type=Path, required=True, help="POS products-export.json")
    args = parser.parse_args()

    STRUCTURED.mkdir(parents=True, exist_ok=True)
    (CORPUS / "products").mkdir(parents=True, exist_ok=True)
    products, duplicates = load_catalogue(args.catalogue)
    chosen = select_for_pages(products)
    write_products(chosen)
    write_prices(products)
    write_orders(products)
    print(f"{len(products)} categorised products -> prices_stock.csv")
    print(f"{len(chosen)} product pages written")
    print("200 synthetic orders -> orders.csv")
    if duplicates:
        print(f"Duplicate names skipped (fix in the POS): {sorted(set(duplicates))}")
    print("Next: python scripts/stage.py to stage these and rebuild data/manifest.csv")


if __name__ == "__main__":
    main()
