"""
Yu-Gi-Oh! news for Card Vault.

Reads the RSS/Atom feeds listed in news-feeds.txt (or the defaults below), keeps the last 60 days,
labels each item (TCG / OCG, new cards, products, banlists, Rush Duel and video games) and writes
site/news.json. Items from earlier runs are carried over, so nothing is lost between runs even when
a site posts more than its feed shows at once.
"""
import json, os, re, sys, html, html.entities, datetime, email.utils, urllib.request, xml.etree.ElementTree as ET

UA = "CardVault personal news reader (twice a day)"
DEFAULT_FEEDS = [
    ("YGOrganization", "https://ygorganization.com/feed/"),
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


def main():
    site = sys.argv[1] if len(sys.argv) > 1 else "site"
    base = os.environ.get("PAGES_URL", "").rstrip("/") + "/"
    feeds = []
    feeds_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "news-feeds.txt")
    if os.path.exists(feeds_file):
        for line in open(feeds_file, encoding="utf-8"):
            line = line.split("#", 1)[0].strip()
            if "|" in line:
                name, url = [x.strip() for x in line.split("|", 1)]
                if url:
                    feeds.append((name, url))
    feeds = feeds or DEFAULT_FEEDS
    previous = []
    try:
        previous = json.loads(fetch(base + "news.json")).get("items", [])
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
        it = label(it)
        it["date"] = it["date"].strftime("%Y-%m-%dT%H:%M:%SZ")
        it["summary"] = it["summary"][:320]
        it.pop("cats", None)
        merged[it["link"] or it["title"]] = it
    keep = [it for it in merged.values() if it.get("date", "") >= cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")]
    keep.sort(key=lambda x: x["date"], reverse=True)
    out = {"updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "feeds": status, "items": keep[:400]}
    json.dump(out, open(os.path.join(site, "news.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    print("Wrote news.json:", len(out["items"]), "items")


if __name__ == "__main__":
    main()
