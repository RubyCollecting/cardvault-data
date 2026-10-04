"""
Rush Duel card prices from TCG Republic, once a day.

Cardmarket sells no Rush Duel singles, so Card Vault takes their prices from TCG Republic's
Rush Duel category (a Japanese shop, prices in USD). It reads the category's listing pages one by one,
with a pause between pages and a user agent that names this project. TCG Republic has no terms of
service, and its robots.txt allows these pages (checked 2026-10-04).

Writes site/rush-prices.json:
  {"updated": "...", "date": "YYYY-MM-DD", "currency": "USD", "source": "TCG Republic",
   "prices": {"RD/ORP2-JP001|ORR": [6091.12, 2000524095], ...},   # lowest in-stock price, product id
   "variants": {"RD/KP19-JP056|ORR|alt": [...]},                    # alternative artworks, kept apart
   "other": {"rarity text": count}}                                  # rarities that couldn't be named

Runs at most once a day: if the published copy is already from today (UTC), it is copied and nothing
is fetched. If TCG Republic can't be read, the published copy is kept.

Usage: python3 scripts/rush-prices.py site            (PAGES_URL = the published site)
       python3 scripts/rush-prices.py --parse page.html   (prints what one saved page yields)
"""
import datetime, html, json, os, re, sys, time, urllib.request

UA = "CardVaultBot/1.0 (personal collection app, once a day; github.com/RubyCollecting/cardvault-data)"
BASE = "https://tcgrepublic.com/category/category_page_49.html"   # Yu-Gi-Oh! Rush Duel
PAUSE = 3          # seconds between pages
MAX_PAGES = 400    # safety stop

# TCG Republic's rarity names -> the abbreviations yaml-yugi and the app use
RARITY = {
    "normal": "C", "common": "C", "rare": "R", "super": "SR", "ultra": "UR", "secret": "ScR",
    "rush": "RR", "gold rush": "GRR", "over rush": "ORR", "full over rush": "FORR",
    "normal parallel": "NPR", "np": "NPR", "super parallel": "SPR", "ultra parallel": "UPR", "ur parallel": "UPR", "urp": "UPR",
    "secret parallel": "ScPR",
}
# colour versions: (base rarity, version word) -> abbreviation
COLOUR = {("UR", "red"): "URRed", ("RR", "red"): "RRRed", ("ScR", "red"): "ScRRed",
          ("ScR", "blue"): "ScRBlue", ("ORR", "black"): "ORRBlack"}

ITEM = re.compile(r'<li class="product_thumbnail".*?</li>', re.S)
CODE = re.compile(r"(RD/[A-Z0-9]+-[A-Z]{2}[A-Z]?\d+)\s*(.*)$")


def rarity_of(text):
    """'Over Rush(PREMIUM BLACK Ver.)' -> ('ORRBlack', ''); 'Over Rush(Alternative Illustration)' -> ('ORR', 'alt')."""
    t = text.strip()
    extras = [e.lower() for e in re.findall(r"\(([^)]*)\)", t)]
    base = re.sub(r"\([^)]*\)", "", t).strip().lower()
    abbr = RARITY.get(base)
    if not abbr:
        return None, ""
    variant = ""
    for e in extras:
        if "sealed" in e or "当選" in e:
            continue
        m = re.search(r"\b(red|blue|black)\b", e)
        if m and (abbr, m.group(1)) in COLOUR:
            abbr = COLOUR[(abbr, m.group(1))]
        elif "altern" in e or "illustration" in e or "artwork" in e:
            variant = "alt"
        else:
            variant = variant or "other"
    return abbr, variant


def parse(page):
    """Products on one listing page: (code, rarity text, price or None, product id)."""
    main = page.split('id="main_container"', 1)
    if len(main) < 2:
        return [], 0
    body = main[1]
    m = re.search(r'paginator_items_total[^>]*>\s*([\d,]+)', page)
    total = int(m.group(1).replace(",", "")) if m else 0
    out = []
    for it in ITEM.findall(body):
        pid = re.search(r"product_page_(\d+)", it)
        alt = re.search(r'alt="([^"]*)"', it)
        if not pid or not alt:
            continue
        name = html.unescape(alt.group(1)).strip()
        cm = CODE.search(name)
        if not cm:
            continue                                     # sealed products, supplies
        price = re.search(r'price_with_unit_offscreen">([\d.]+)', it)
        out.append((cm.group(1), cm.group(2), float(price.group(1)) if price else None, int(pid.group(1))))
    return out, total


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def build(rows):
    prices, variants, other = {}, {}, {}
    for code, rtext, price, pid in rows:
        abbr, variant = rarity_of(rtext)
        if not abbr:
            other[rtext] = other.get(rtext, 0) + 1
            continue
        if price is None:
            continue                                     # sold out
        key = f"{code}|{abbr}"
        box = prices
        if variant:
            key += "|" + variant
            box = variants
        if key not in box or price < box[key][0]:
            box[key] = [price, pid]
    return prices, variants, other


def previous(site):
    base = os.environ.get("PAGES_URL", "").rstrip("/")
    if not base:
        return None
    try:
        with urllib.request.urlopen(base + "/rush-prices.json", timeout=60) as r:
            j = json.load(r)
        return j if isinstance(j, dict) and j.get("prices") else None
    except Exception:
        return None


def main():
    if sys.argv[1:2] == ["--parse"]:
        rows, total = parse(open(sys.argv[2], encoding="utf-8").read())
        prices, variants, other = build(rows)
        print(json.dumps({"total": total, "rows": len(rows), "prices": prices, "variants": variants, "other": other},
                         ensure_ascii=False, indent=1))
        return
    site = sys.argv[1]
    out = os.path.join(site, "rush-prices.json")
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    prev = previous(site)
    if prev and prev.get("date") == today:
        json.dump(prev, open(out, "w"), ensure_ascii=False, separators=(",", ":"))
        print(f"Already read today ({len(prev['prices'])} prices), copied the published file")
        return

    rows, pages, failed, total = [], 0, 0, 0
    p = 1
    while p <= MAX_PAGES:
        url = BASE + (f"?p={p}" if p > 1 else "")
        try:
            got, t = parse(fetch(url))
        except Exception as e:
            print(f"::warning::Page {p}: {e}")
            failed += 1
            if failed >= 5:
                break
            p += 1
            time.sleep(PAUSE * 3)
            continue
        total = total or t
        pages += 1
        if not got and p > 1 and not t:
            break
        rows += got
        last = max(1, -(-total // 48)) if total else p
        if p >= last:
            break
        p += 1
        time.sleep(PAUSE)

    prices, variants, other = build(rows)
    print(f"Read {pages} pages ({failed} failed), {len(rows)} Rush cards listed of {total} products, "
          f"{len(prices)} priced prints, {len(variants)} alternative artworks")
    if other:
        print("Rarities not named:", json.dumps(other, ensure_ascii=False))
    if failed > pages // 4 or len(prices) < 200:
        if prev:
            json.dump(prev, open(out, "w"), ensure_ascii=False, separators=(",", ":"))
            print(f"::warning::TCG Republic could not be read fully, kept the prices from {prev.get('date')}")
        else:
            print("::warning::No Rush Duel prices this run")
        return
    data = {"updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "date": today,
            "currency": "USD", "source": "TCG Republic", "url": "https://tcgrepublic.com/product/product_page_{id}.html",
            "prices": prices, "variants": variants, "other": other}
    json.dump(data, open(out, "w"), ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
