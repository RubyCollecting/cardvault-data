"""
Japanese OCG prices for Card Vault, from Yuyu-tei (yuyu-tei.jp).

Reads the set codes listed in ocg-sets.txt (next to this script), fetches Yuyu-tei's single-card
page for each set once a day (politely: one request every few seconds, nothing else), converts
yen to euro with the European Central Bank's daily rate and writes site/ocg-prices.json.

Prices of cards that are currently sold out keep yesterday's price, marked with the date it was
last seen, so a card doesn't lose its price just because the shop ran out.
"""
import datetime, html, json, os, re, sys, time, unicodedata, urllib.error, urllib.request

SHOP = "https://yuyu-tei.jp/sell/ygo/s/{set}"
UA = "CardVault personal collection tracker (once a day, sets listed by the owner)"
HERE = os.path.dirname(os.path.abspath(__file__))
SETS_FILE = os.path.join(HERE, "ocg-sets.txt")

RARITY = {  # Yuyu-tei's rarity abbreviations -> the English names used by the card database
    "N": "Common", "NR": "Normal Rare", "R": "Rare", "SR": "Super Rare", "UR": "Ultra Rare",
    "SE": "Secret Rare", "PSE": "Prismatic Secret Rare", "UL": "Ultimate Rare", "HR": "Holographic Rare",
    "CR": "Collector's Rare", "QCSE": "Quarter Century Secret Rare", "GMR": "Grandmaster Rare",
    "EXSE": "Extra Secret Rare", "20thSE": "20th Secret Rare", "GR": "Gold Rare", "GSE": "Gold Secret Rare",
    "PG": "Premium Gold Rare", "P-N": "Normal Parallel Rare", "NP": "Normal Parallel Rare",
    "P-SR": "Super Parallel Rare", "P-UR": "Ultra Parallel Rare", "KC-UR": "Ultra Rare",
    "M": "Millennium Rare", "MLR": "Millennium Rare", "SLR": "Starlight Rare",
}
OF_MARK = re.compile(r"[(（]\s*(オーバーフレーム|OF)\s*[)）]")
CARD = re.compile(r"\b([A-Z0-9]{2,6}-JP[A-Z]{0,2}\d{2,4})\s+([0-9A-Za-z-]{1,8})\s+(.+)")
PRICE = re.compile(r"([\d,]+)\s*円")
STOCK = re.compile(r"在庫\s*:\s*(×|\d+)")
LINK = re.compile(r"/sell/ygo/card/[a-z0-9]+/(\d+)")


def nfkc(s):
    return unicodedata.normalize("NFKC", s or "").strip()


def fetch(url, tries=3):
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                raise
            time.sleep(5 * (a + 1))
        except Exception:
            time.sleep(5 * (a + 1))
    raise RuntimeError("no response from " + url)


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def ecb_jpy():
    """Euro to yen reference rate from the European Central Bank."""
    xml = fetch("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml")
    m = re.search(r"currency='JPY'\s+rate='([\d.]+)'", xml)
    d = re.search(r"time='(\d{4}-\d{2}-\d{2})'", xml)
    return float(m.group(1)), d.group(1) if d else None


def text_lines(page):
    """The page as lines of plain text, with each card link's id kept as a [[id]] marker."""
    page = re.sub(r"\s+", " ", re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", page))
    page = re.sub(r'(?i)<a\b[^>]*href="[^"]*' + LINK.pattern + r'[^"]*"[^>]*>', r"\n[[\1]] ", page)
    page = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|a|span|td|tr)>", "\n", page)
    page = html.unescape(re.sub(r"<[^>]+>", " ", page))
    return [l for l in (nfkc(re.sub(r"\s+", " ", x)) for x in page.split("\n")) if l]


def parse(page, set_code):
    """Listings on one Yuyu-tei set page: code, rarity, name, yen price, stock, listing id."""
    lines = text_lines(page)
    starts = []
    for i, l in enumerate(lines):
        m = CARD.search(l)
        if m and m.group(1).startswith(set_code + "-"):
            if starts and starts[-1][1].group(1, 2) == m.group(1, 2) and i - starts[-1][0] <= 2:
                continue  # the same card named twice in a row (image text, then link)
            starts.append((i, m))
    out = []
    for n, (i, m) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else min(len(lines), i + 12)
        chunk = lines[i:end]
        price = next((PRICE.search(l) for l in chunk if PRICE.search(l)), None)
        stock = next((STOCK.search(l) for l in chunk if STOCK.search(l)), None)
        if not price:
            continue
        lid = next((x for x in (re.search(r"\[\[(\d+)\]\]", l) for l in chunk) if x), None)
        name = re.sub(r"\[\[\d+\]\]", "", m.group(3)).strip()
        out.append({
            "code": m.group(1), "rarity": m.group(2), "name": name,
            "yen": int(price.group(1).replace(",", "")),
            "stock": 0 if not stock or stock.group(1) == "×" else int(stock.group(1)),
            "id": int(lid.group(1)) if lid else None,
            "of": bool(OF_MARK.search(name)), "dmg": "傷" in name,
        })
    return out


def build(listings, previous, today):
    """One price per code + rarity + Over Frame: the cheapest in-stock undamaged copy."""
    best = {}
    for it in listings:
        rar = RARITY.get(it["rarity"], it["rarity"])
        key = (it["code"], rar, it["of"])
        cand = dict(it, r=rar, y=it["yen"] if it["stock"] > 0 else None)
        def score(c):  # in stock beats sold out, undamaged beats damaged, then cheaper
            return (c["y"] is None, c["dmg"], c["y"] or c["yen"])
        if key not in best or score(cand) < score(best[key]):
            best[key] = cand
    out = {}
    for (code, rar, of), c in best.items():
        e = {"r": rar, "y": c["y"], "s": c["stock"], "id": c["id"], "d": today}
        if of:
            e["of"] = 1
        if c["dmg"]:
            e["dmg"] = 1
        if e["y"] is None:  # sold out: keep the last price we saw, with its date
            for p in previous.get(code, []):
                if p.get("r") == rar and bool(p.get("of")) == of and p.get("y"):
                    e["y"], e["d"], e["last"] = p["y"], p.get("d"), 1
                    break
            else:
                e["y"], e["list"] = c["yen"], 1  # the shop's list price while sold out
        out.setdefault(code, []).append(e)
    return out


def main():
    site = sys.argv[1] if len(sys.argv) > 1 else "site"
    base = os.environ.get("PAGES_URL", "").rstrip("/") + "/"
    sleep = float(os.environ.get("OCG_SLEEP", "3"))
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    previous = {}
    try:
        previous = get_json(base + "ocg-prices.json")
    except Exception as e:
        print("No earlier OCG price file yet:", e)
    wanted = []
    if os.path.exists(SETS_FILE):
        for line in open(SETS_FILE, encoding="utf-8"):
            line = line.split("#")[0].strip().upper()
            if line:
                wanted.append(line)
    # once a day is enough: if today's prices are already published, just carry the file over
    if (previous.get("date") == today and sorted(previous.get("wanted", [])) == sorted(wanted)
            and previous.get("prices") and not previous.get("errors")):
        print("OCG prices are already from today; keeping them.")
        json.dump(previous, open(os.path.join(site, "ocg-prices.json"), "w"), ensure_ascii=False, separators=(",", ":"))
        return
    result = {"source": "yuyu-tei", "date": today, "wanted": wanted, "sets": {}, "prices": {}, "errors": []}
    try:
        result["eur_jpy"], result["rate_date"] = ecb_jpy()
    except Exception as e:
        result["errors"].append("exchange rate: %s" % e)
        result["eur_jpy"], result["rate_date"] = previous.get("eur_jpy"), previous.get("rate_date")
    if not wanted:
        print("::warning::ocg-sets.txt lists no sets; nothing to fetch (looked in %s)." % SETS_FILE)
    prev_prices = previous.get("prices", {})
    for n, code in enumerate(wanted):
        if n:
            time.sleep(sleep)
        url = SHOP.format(set=code.lower())
        try:
            page = fetch(url)
            listings = parse(page, code)
            if not listings:
                sample = [l for l in text_lines(page) if code + "-JP" in l][:3]
                raise RuntimeError("no cards found on %s (%d characters; lines with card codes: %s)"
                                   % (url, len(page), sample))
        except Exception as e:
            result["errors"].append("set %s: %s" % (code, e))
            print("Set", code, "failed:", e)
            for k, v in prev_prices.items():  # keep yesterday's prices for this set
                if k.startswith(code + "-"):
                    result["prices"][k] = v
            continue
        result["sets"][code] = {"url": url, "listings": len(listings)}
        result["prices"].update(build(listings, prev_prices, today))
        print("Set %s: %d listings" % (code, len(listings)))
    json.dump(result, open(os.path.join(site, "ocg-prices.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    print("Wrote ocg-prices.json:", len(result["prices"]), "card codes; errors:", result["errors"] or "none")
    for e in result["errors"]:
        print("::warning::OCG prices " + e)
    if wanted and not result["prices"]:
        sys.exit("No OCG prices at all; see the messages above.")


if __name__ == "__main__":
    main()
