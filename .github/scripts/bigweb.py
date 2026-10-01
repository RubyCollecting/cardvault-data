"""
BIGWEB prices for Card Vault.

Reads the set codes listed in bigweb-sets.txt, fetches BIGWEB's listings for those sets
once a day (politely: one request every 2 seconds, nothing else), converts yen to euro
with the European Central Bank's daily rate and writes site/bigweb.json.

Prices of cards that are currently sold out are carried over from the previous day's file,
marked with the date they were last seen, so a card doesn't lose its price just because the
shop ran out.
"""
import json, os, re, sys, time, unicodedata, urllib.request, urllib.error, datetime

API = "https://api.bigweb.co.jp"
GAME = 9  # Yu-Gi-Oh on BIGWEB
UA = "CardVault personal collection tracker (once a day, sets listed by the owner)"
PAGE_URLS = [  # BIGWEB's site uses one of these; the first that returns the right set is used
    API + "/products?game_id=9&cardsets={id}&page={page}&limit=100",
    API + "/products?cardsets={id}&page={page}&limit=100",
    API + "/products?game_id=9&cardset_id={id}&page={page}&limit=100",
    API + "/products?cardset={id}&page={page}&limit=100",
]
OVERRIDE = os.environ.get("BIGWEB_PRODUCTS_URL", "").strip()
if OVERRIDE:
    PAGE_URLS = [OVERRIDE]

RARITY = {  # BIGWEB's Japanese rarity names -> the English names used by the card database
    "ノーマル": "Common", "ノーマルレア": "Normal Rare", "レア": "Rare", "スーパーレア": "Super Rare",
    "ウルトラレア": "Ultra Rare", "シークレットレア": "Secret Rare",
    "プリズマティックシークレットレア": "Prismatic Secret Rare", "アルティメットレア": "Ultimate Rare",
    "レリーフ": "Ultimate Rare", "ホログラフィックレア": "Holographic Rare", "コレクターズレア": "Collector's Rare",
    "クォーターセンチュリーシークレットレア": "Quarter Century Secret Rare",
    "グランドマスターレア": "Grandmaster Rare", "エクストラシークレットレア": "Extra Secret Rare",
    "20thシークレットレア": "20th Secret Rare", "ゴールドレア": "Gold Rare", "ゴールドシークレットレア": "Gold Secret Rare",
    "プレミアムゴールドレア": "Premium Gold Rare", "ノーマルパラレルレア": "Normal Parallel Rare",
    "スーパーパラレルレア": "Super Parallel Rare", "ウルトラパラレルレア": "Ultra Parallel Rare",
    "シークレットパラレルレア": "Prismatic Secret Rare", "ミレニアムレア": "Millennium Rare",
    "ウルトラレア(パラレル)": "Ultra Parallel Rare", "スターライトレア": "Starlight Rare",
}
OF_MARK = re.compile(r"[（(]?\s*(オーバーフレーム|ｵｰﾊﾞｰﾌﾚｰﾑ|OF|O\.F\.)\s*[)）]?", re.I)


def nfkc(s):
    return unicodedata.normalize("NFKC", s or "").strip()


def get_json(url, tries=3):
    for a in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                raise
            time.sleep(5 * (a + 1))
        except Exception:
            time.sleep(5 * (a + 1))
    raise RuntimeError("no response from " + url)


def ecb_jpy():
    """Euro to yen reference rate from the European Central Bank."""
    req = urllib.request.Request("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml", headers={"User-Agent": UA})
    xml = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    m = re.search(r"currency='JPY'\s+rate='([\d.]+)'", xml)
    d = re.search(r"time='(\d{4}-\d{2}-\d{2})'", xml)
    return float(m.group(1)), d.group(1) if d else None


def rarity_of(item):
    web = nfkc((item.get("rarity") or {}).get("web"))
    name = nfkc(item.get("name"))
    of = bool(OF_MARK.search(web) or OF_MARK.search(name))
    base = OF_MARK.sub("", web).strip()
    return RARITY.get(base, base or "?"), of


def condition_of(item):
    c = nfkc((item.get("condition") or {}).get("web"))
    return "damaged" if ("傷" in c or "特価" in c) else "play"


def fetch_set(cardset_id, sleep):
    pattern = None
    for p in PAGE_URLS:
        url = p.format(id=cardset_id, page=1)
        try:
            d = get_json(url)
        except Exception as e:
            print("   not this address:", url, "-", e)
            time.sleep(sleep)
            continue
        items = d.get("items") or []
        if d.get("success") and items and all((i.get("cardset") or {}).get("id") == cardset_id for i in items):
            pattern, first = p, d
            break
        print("   not this address (wrong or empty result):", url)
        time.sleep(sleep)
    if not pattern:
        raise RuntimeError("couldn't find BIGWEB's product list address for set %s" % cardset_id)
    items = list(first["items"])
    pages = int((first.get("pagenate") or {}).get("pageCount") or 1)
    for page in range(2, min(pages, 40) + 1):
        time.sleep(sleep)
        items += get_json(pattern.format(id=cardset_id, page=page)).get("items") or []
    return items, pattern


def build(items, previous, today):
    """One price per code + rarity + Over Frame: the cheapest in-stock copy in playable condition."""
    best = {}
    for it in items:
        code = nfkc(it.get("fname")).upper()
        if not re.match(r"^[A-Z0-9]+-[A-Z]{0,2}[0-9A-Z]+$", code):
            continue
        rar, of = rarity_of(it)
        cond = condition_of(it)
        price = int(it.get("sale_prices") or 0) or int(it.get("price") or 0)
        stock = int(it.get("stock_count") or 0) if not it.get("is_sold_out") else 0
        key = (code, rar, of)
        cand = {"r": rar, "of": of, "y": price if stock > 0 and price > 0 else None, "stock": stock,
                "id": it.get("id"), "cond": cond}
        cur = best.get(key)
        def score(c):  # in stock beats sold out, playable beats damaged, then cheaper
            return (c["y"] is None, c["cond"] != "play", c["y"] or 0)
        if cur is None or score(cand) < score(cur):
            best[key] = cand
    out = {}
    for (code, rar, of), c in best.items():
        e = {"r": rar, "y": c["y"], "s": c["stock"], "id": c["id"], "d": today}
        if of:
            e["of"] = 1
        if c["cond"] != "play":
            e["dmg"] = 1
        if e["y"] is None:  # sold out: keep the last price we saw, with its date
            for p in previous.get(code, []):
                if p.get("r") == rar and bool(p.get("of")) == of and p.get("y"):
                    e["y"], e["d"], e["last"] = p["y"], p.get("d"), 1
                    break
        out.setdefault(code, []).append(e)
    return out


def main():
    site = sys.argv[1] if len(sys.argv) > 1 else "site"
    base = os.environ.get("PAGES_URL", "").rstrip("/") + "/"
    sleep = float(os.environ.get("BIGWEB_SLEEP", "2"))
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    previous = {}
    try:
        previous = get_json(base + "bigweb.json", tries=1)
    except Exception as e:
        print("No earlier BIGWEB file yet:", e)
    wanted = []
    if os.path.exists("bigweb-sets.txt"):
        for line in open("bigweb-sets.txt", encoding="utf-8"):
            line = line.split("#")[0].strip().upper()
            if line:
                wanted.append(line)
    # once a day is enough: if today's prices are already published, just carry the file over
    if previous.get("date") == today and sorted(previous.get("wanted", [])) == sorted(wanted):
        print("BIGWEB prices are already from today; keeping them.")
        json.dump(previous, open(os.path.join(site, "bigweb.json"), "w"), ensure_ascii=False, separators=(",", ":"))
        return
    result = {"date": today, "wanted": wanted, "sets": {}, "prices": {}, "errors": []}
    try:
        rate, rate_date = ecb_jpy()
        result["eur_jpy"], result["rate_date"] = rate, rate_date
    except Exception as e:
        result["errors"].append("exchange rate: %s" % e)
        result["eur_jpy"] = previous.get("eur_jpy")
        result["rate_date"] = previous.get("rate_date")
    if not wanted:
        print("bigweb-sets.txt lists no sets; nothing to fetch.")
    else:
        cardsets = get_json(API + "/cardsets?game_id=%d" % GAME).get("cardsets") or []
        by_code = {}
        for cs in cardsets:
            for k in (cs.get("code"), cs.get("slip")):
                if k:
                    by_code.setdefault(nfkc(k).upper().rstrip("."), cs)
            m = re.match(r"^\[([A-Z0-9]+)\]", nfkc(cs.get("name") or cs.get("web") or ""))
            if m:
                by_code.setdefault(m.group(1), cs)
        prev_prices = previous.get("prices", {})
        for code in wanted:
            cs = by_code.get(code)
            if not cs:
                result["errors"].append("set %s isn't on BIGWEB" % code)
                print("Set", code, "not found on BIGWEB")
                continue
            print("Set", code, "->", cs.get("id"), nfkc(cs.get("name")))
            time.sleep(sleep)
            try:
                items, pattern = fetch_set(cs["id"], sleep)
            except Exception as e:
                result["errors"].append("set %s: %s" % (code, e))
                print("  failed:", e)
                # keep yesterday's prices for this set rather than losing them
                for k, v in prev_prices.items():
                    if k.startswith(code + "-"):
                        result["prices"][k] = v
                continue
            result["sets"][code] = {"id": cs["id"], "name": nfkc(cs.get("name")), "listings": len(items)}
            result["prices"].update(build(items, prev_prices, today))
            print("  %d listings" % len(items))
    json.dump(result, open(os.path.join(site, "bigweb.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    print("Wrote bigweb.json:", len(result["prices"]), "card codes;", "errors:", result["errors"] or "none")


if __name__ == "__main__":
    main()
