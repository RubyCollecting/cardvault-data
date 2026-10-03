import urllib.request, urllib.parse, json, re
BUA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
def get(u,ua):
    r=urllib.request.Request(u,headers={"User-Agent":ua,"Accept":"*/*"})
    with urllib.request.urlopen(r,timeout=40) as x: return x.status, dict(x.headers), x.read()
for ua in [BUA,"CardVault/1.0 (personal collection app; github.com/RubyCollecting/cardvault-data)"]:
  for u in ["https://bulbapedia.bulbagarden.net/w/api.php?action=parse&format=json&prop=wikitext&origin=*&page=List_of_Japanese_Pok%C3%A9mon_Trading_Card_Game_expansions",
            "https://bulbapedia.bulbagarden.net/w/index.php?title=List_of_Pok%C3%A9mon_Trading_Card_Game_expansions&action=raw"]:
    try:
        s,h,b=get(u,ua);print("OK",ua[:10],u[:90],s,h.get("Access-Control-Allow-Origin"),len(b));w=b.decode("utf8","replace")
        print(w[:1500]);i=w.rfind("2026");print("....",w[max(0,i-5000):i+3000])
    except Exception as e: print("FAIL",ua[:10],u[:90],str(e)[:100])
s,h,b=get("https://www.pokebeach.com/forums/forums/-/index.rss",BUA)
for m in re.findall(rb"<item>(.*?)</item>",b,re.S)[:6]: print(m[:900].decode("utf8","replace"));print("--")
for u in ["https://www.pokemon-card.com/products/","https://www.serebii.net/card/","https://www.pokemon.com/us/pokemon-tcg/product-gallery","https://www.pokemon.com/us/pokemon-news"]:
    try:s,h,b=get(u,BUA);print("PAGE",u,s,len(b))
    except Exception as e:print("PAGE",u,"FAIL",str(e)[:80])
