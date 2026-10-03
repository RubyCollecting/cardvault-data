"""
Yu-Gi-Oh! and Pokémon news for Card Vault.

Reads the RSS/Atom feeds listed in news-feeds.txt (or the defaults below), keeps the last 60 days,
labels each item (TCG / OCG, new cards, products, banlists, Rush Duel and video games) and writes
site/news.json. Items from earlier runs are carried over, so nothing is lost between runs even when
a site posts more than its feed shows at once.

With --game pokemon it reads pokemon-news-feeds.txt instead and writes site/pokemon/news.json, with the
same tags so the app's filters work for both games: TCG = English, OCG = Japanese, BANLIST = Standard
format and rules, GAME = TCG Pocket and the video games.
"""
import json, os, re, sys, html, html.entities, datetime, email.utils, urllib.request, xml.etree.ElementTree as ET

UA = "CardVault personal news reader (twice a day)"
DEFAULT_FEEDS = [
    ("YGOrganization", "https://ygorganization.com/feed/"),
]
POKEMON_FEEDS = [
    ("PokéBeach", "https://www.pokebeach.com/forums/forums/front-page-news.18/index.rss"),
]
KEEP_DAYS = 60
NS = {"atom": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/",
      "content": "http://purl.org/rss/1.0/modules/content/", "dc": "http://purl.org/dc/elements/1.1/"}


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read()


def text(el):
    return (el.text or "").strip() if el is not None else ""


def strip_html(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def first_img(s):
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', s or "", re.I)
    return m.group(1) if m else ""


def parse_date(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.astimezone(datetime.timezone.utc)


XML_ENTITIES = ("amp", "lt", "gt", "quot", "apos")


def repair_xml(raw):
    """Fix the usual mistakes in hand-built feeds: stray control characters, HTML entities
    such as &nbsp; and bare & signs."""
    s = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", s)

    def entity(m):
        name = m.group(1)
        if name in XML_ENTITIES:
            return m.group(0)
        ch = html.entities.html5.get(name + ";")
        return "".join("&#%d;" % ord(c) for c in ch) if ch else "&amp;" + name + ";"
    s = re.sub(r"&([A-Za-z][A-Za-z0-9]*);", entity, s)
    s = re.sub(r"&(?!#\d+;|#x[0-9A-Fa-f]+;|[A-Za-z][A-Za-z0-9]*;)", "&amp;", s)
    return re.sub(r"^\s*<\?xml[^>]*\?>", "", s).encode("utf-8")


def parse_feed(raw, source):
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        root = ET.fromstring(repair_xml(raw))
    out = []
    items = root.findall(".//item")
    if items:  # RSS 2.0
        for it in items:
            body = text(it.find("content:encoded", NS)) or text(it.find("description"))
            img = ""
            for tag in ("media:content", "media:thumbnail"):
                m = it.find(tag, NS)
                if m is not None and m.get("url"):
                    img = m.get("url"); break
            enc = it.find("enclosure")
            if not img and enc is not None and (enc.get("type") or "").startswith("image"):
                img = enc.get("url") or ""
            out.append({"title": strip_html(text(it.find("title"))), "link": text(it.find("link")),
                        "date": parse_date(text(it.find("pubDate")) or text(it.find("dc:date", NS))),
                        "summary": strip_html(text(it.find("description")) or body),
                        "cats": [strip_html(text(c)) for c in it.findall("category")],
                        "img": img or first_img(body), "source": source})
    else:  # Atom
        for it in root.findall("atom:entry", NS):
            link = ""
            for l in it.findall("atom:link", NS):
                if l.get("rel", "alternate") == "alternate":
                    link = l.get("href", ""); break
            body = text(it.find("atom:content", NS)) or text(it.find("atom:summary", NS))
            th = it.find("media:group/media:thumbnail", NS) or it.find("media:thumbnail", NS)
            out.append({"title": strip_html(text(it.find("atom:title", NS))), "link": link,
                        "date": parse_date(text(it.find("atom:published", NS)) or text(it.find("atom:updated", NS))),
                        "summary": strip_html(text(it.find("atom:summary", NS)) or body),
                        "cats": [c.get("term", "") for c in it.findall("atom:category", NS)],
                        "img": (th.get("url") if th is not None else "") or first_img(body), "source": source})
    return out


def label(item):
    """Tags used by the app's filters."""
    t = item["title"]
    # "OCG & TCG" is YGOrganization's category for the card game as a whole, not a region
    c = " ".join(x for x in item.get("cats", []) if not re.fullmatch(r"OCG\s*&\s*TCG", x.strip()))
    both = (t + " " + c)
    tags = []
    if re.search(r"\bOCG-AE\b|Asian[- ]English", both, re.I): tags.append("AE")
    if re.search(r"\[[^\]]*\bOCG\b(?!-AE)[^\]]*\]|\bOCG\b(?!-AE)|Japan", both): tags.append("OCG")
    if re.search(r"\bTCG\b", both): tags.append("TCG")
    if re.search(r"Rush Duel|\[RD[/\]]", both, re.I): tags.append("RUSH")
    if re.search(r"Duel Links|Master Duel|\bDUEL LINKS\b|\bMASTER DUEL\b|Cross Duel", both, re.I): tags.append("GAME")
    if re.search(r"Forbidden|Limited List|Banlist|Ban List", both, re.I): tags.append("BANLIST")
    if re.search(r"Announce|Announced|New Product|Pre-?order|Release|Booster|Structure Deck|Tin|Collection|Pack\b", both, re.I): tags.append("PRODUCT")
    bracket = [b for b in re.findall(r"\[(?:RD/)?([A-Z0-9]{3,5})(?:-[A-Z]{2})?\]", t) if b not in ("OCG", "TCG", "MW", "IMPH")]
    if "BANLIST" not in tags and (re.search(r"New Cards|Reveal|Revealed|Set Spoilers", both, re.I) or bracket): tags.append("CARDS")
    if re.search(r"Rulings", both, re.I): tags.append("RULINGS")
    if re.search(r"\[MW\]|Market Watch|Prices", both, re.I): tags.append("MARKET")
    if "AE" in tags and "OCG" in tags and not re.search(r"\[OCG\]", t):
        tags.remove("OCG")   # Asian-English releases are their own region
    m = re.search(r"\[(?:RD/)?([A-Z0-9]{3,5})(?:-[A-Z]{2})?\]", t)
    if m and m.group(1) not in ("OCG", "TCG", "MW", "RD", "IMPH"):
        item["set"] = m.group(1)
    item["tags"] = sorted(set(tags))
    return item


def label_pokemon(item):
    """The same tags for Pokémon news. Most English news sites cover both regions, so the region
    comes from the title: Japanese sets and products are usually called Japanese, the rest is English."""
    t = item["title"]
    both = t + " " + " ".join(item.get("cats", []))
    tags = []
    if re.search(r"\bJapan(ese)?\b|\bJP\b", both, re.I): tags.append("OCG")
    elif re.search(r"\bEnglish\b|\bInternational\b|Pokemon Center|Pokémon Center|\bUS\b|\bEU\b|Europe", both, re.I): tags.append("TCG")
    if re.search(r"\bPocket\b|Pok[eé]mon GO|\bUnite\b|\bLegends\b|\bChampions\b|Switch|\bDLC\b|Sleep\b|\bMasters EX\b|\banime\b|\bmovie\b", both, re.I): tags.append("GAME")
    if re.search(r"Rotation|Standard Format|Ban(ned)? List|\bbanned\b|Errata|Regulation Mark|Legal", both, re.I): tags.append("BANLIST")
    if re.search(r"Pre-?orders?|Release|Booster|Elite Trainer Box|\bETB\b|Collection|\bTin\b|Bundle|Blister|Premium|Product|Box\b|Accessories|Set\b|Restock", both, re.I): tags.append("PRODUCT")
    if re.search(r"Cards? Revealed|Card Images|Revealed|Reveal|Card List|Spoilers?|Promos?", both, re.I): tags.append("CARDS")
    if re.search(r"Rulings?|Rules", both, re.I): tags.append("RULINGS")
    if re.search(r"Prices?|Market|Sales|Sold for|Auction", both, re.I): tags.append("MARKET")
    item["tags"] = sorted(set(tags))
    return item


def main():
    argv = sys.argv[1:]
    pokemon = "--game" in argv and argv[argv.index("--game") + 1:argv.index("--game") + 2] == ["pokemon"]
    if "--game" in argv:
        del argv[argv.index("--game"):argv.index("--game") + 2]
    site = argv[0] if argv else "site"
    base = os.environ.get("PAGES_URL", "").rstrip("/") + "/"
    folder = "pokemon/" if pokemon else ""
    feeds = []
    feeds_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pokemon-news-feeds.txt" if pokemon else "news-feeds.txt")
    if os.path.exists(feeds_file):
        for line in open(feeds_file, encoding="utf-8"):
            line = line.split("#", 1)[0].strip()
            if "|" in line:
                name, url = [x.strip() for x in line.split("|", 1)]
                if url:
                    feeds.append((name, url))
    feeds = feeds or (POKEMON_FEEDS if pokemon else DEFAULT_FEEDS)
    previous = []
    try:
        previous = json.loads(fetch(base + folder + "news.json")).get("items", [])
    except Exception as e:
        print("No earlier news file yet:", e)
    items, status = [], {}
    for name, url in feeds:
        got = 0
        pages = [url] + ([url + ("&" if "?" in url else "?") + "paged=%d" % p for p in (2, 3)] if "/feed" in url else [])
        for u in pages:
            try:
                new = parse_feed(fetch(u), name)
            except Exception as e:
                if u == url:
                    status[name] = "failed: %s" % e
                    print("Feed", name, "failed:", e)
                break
            items += new; got += len(new)
            if not new:
                break
        if got:
            status[name] = "%d items" % got
            print("Feed", name, "->", got, "items")
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=KEEP_DAYS)
    merged = {}
    for it in previous:
        merged[it.get("link") or it.get("title")] = it
    for it in items:
        if not it["title"] or not it["date"]:
            continue
        it = label_pokemon(it) if pokemon else label(it)
        it["date"] = it["date"].strftime("%Y-%m-%dT%H:%M:%SZ")
        it["summary"] = it["summary"][:320]
        it.pop("cats", None)
        merged[it["link"] or it["title"]] = it
    keep = [it for it in merged.values() if it.get("date", "") >= cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")]
    keep.sort(key=lambda x: x["date"], reverse=True)
    out = {"updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "feeds": status, "items": keep[:400]}
    os.makedirs(os.path.join(site, folder), exist_ok=True)
    json.dump(out, open(os.path.join(site, folder, "news.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    print("Wrote", folder + "news.json:", len(out["items"]), "items")


if __name__ == "__main__":
    main()
