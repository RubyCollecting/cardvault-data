"""
Daily price history for Card Vault.

Usage: python3 scripts/history.py SITE_DIR [ARCHIVE_DIR] [pokemon]

Turns today's price guide (SITE_DIR/price_guide_3.json) into one small file per day and publishes
the last PUBLISH_DAYS days in SITE_DIR/history/ (history/<date>.json plus history/index.json).

ARCHIVE_DIR is a checkout of the price-history branch. Every day ever recorded is kept there for
good, so a failed run or an empty Pages site can never shrink the history. The published days are
taken from the archive. Days the archive is missing are still copied over from the live Pages site
(PAGES_URL), which also seeds the archive on its first run. Without ARCHIVE_DIR (the branch could
not be reached this run) the script falls back to carrying days over from Pages alone.

With "pokemon" the same is done for the Pokémon price guide (SITE_DIR/pokemon/price_guide_6.json), published
in SITE_DIR/pokemon/history/ and kept in the archive's pokemon/ folder. Reverse holo prices are stored as the
product id made negative, which is how the app tells them apart from the regular print.
"""
import json, os, sys, shutil, datetime, urllib.request

PUBLISH_DAYS = 45   # the app keeps 46 days and would re-download anything older on every visit


def day_file(pg, reverse=False):
    rows = []
    for x in pg["priceGuides"]:
        v = next((x.get(k) for k in ("trend", "avg30", "avg7", "low") if x.get(k) is not None), None)
        if v is not None:
            rows.append((x["idProduct"], round(v, 2)))
        if reverse and x.get("idCategory") == 51:      # Pokémon singles: reverse holo price of the same product
            v = next((x.get(k) for k in ("trend-holo", "avg30-holo", "avg7-holo", "low-holo") if x.get(k)), None)
            if v:
                rows.append((-x["idProduct"], round(v, 2)))
    rows.sort()
    deltas, prev = [], 0
    for pid, _ in rows:
        deltas.append(pid - prev); prev = pid
    return {"date": pg["createdAt"][:10], "d": deltas, "p": [v for _, v in rows]}


def valid_day(raw, d):
    try:
        j = json.loads(raw)
        return j.get("date") == d and len(j.get("d", [])) == len(j.get("p", [])) > 0
    except Exception:
        return False


def main():
    site = sys.argv[1]
    archive = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
    pokemon = len(sys.argv) > 3 and sys.argv[3] == "pokemon"
    sub = "pokemon" if pokemon else ""
    pages = os.environ.get("PAGES_URL", "").rstrip("/") + "/" + (sub + "/" if sub else "")
    out = os.path.join(site, sub, "history")
    os.makedirs(out, exist_ok=True)
    if archive and sub:
        archive = os.path.join(archive, sub)
        os.makedirs(archive, exist_ok=True)
    store = archive or out          # where kept days live before publishing

    guide = os.path.join(site, sub, "price_guide_6.json" if pokemon else "price_guide_3.json")
    today_file = day_file(json.load(open(guide)), reverse=pokemon)
    day = today_file["date"]
    today = datetime.date.fromisoformat(day)
    json.dump(today_file, open(os.path.join(store, f"{day}.json"), "w"), separators=(",", ":"))

    def in_window(d):
        return 0 <= (today - datetime.date.fromisoformat(d)).days <= PUBLISH_DAYS

    have = {f[:-5] for f in os.listdir(store) if f.endswith(".json") and f[:4].isdigit()}

    # Days the archive doesn't have yet (first run, or a day recorded before the archive existed)
    try:
        live = json.load(urllib.request.urlopen(pages + "history/index.json", timeout=30)).get("dates", [])
    except Exception as e:
        print("Could not read the published history index:", e); live = []
    for d in live:
        if d in have or not (archive or in_window(d)):
            continue
        try:
            raw = urllib.request.urlopen(pages + f"history/{d}.json", timeout=60).read()
            if valid_day(raw, d):
                open(os.path.join(store, f"{d}.json"), "wb").write(raw); have.add(d)
                print("Carried over", d, "from Pages")
        except Exception as e:
            print("Could not carry over", d, e)

    dates = sorted(d for d in have if in_window(d))
    if archive:
        for d in dates:
            shutil.copyfile(os.path.join(archive, f"{d}.json"), os.path.join(out, f"{d}.json"))
        print("Days kept in the archive:", len(have))
    json.dump({"dates": dates}, open(os.path.join(out, "index.json"), "w"))
    print("Days published:", len(dates))


if __name__ == "__main__":
    main()
