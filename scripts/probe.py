import urllib.request, json, re, sys
UA="CardVault personal news reader (twice a day)"
def get(u,h=None):
    r=urllib.request.Request(u,headers={"User-Agent":UA,**(h or {})})
    with urllib.request.urlopen(r,timeout=40) as x: return x.status, dict(x.headers), x.read()
feeds=["https://www.pokebeach.com/feed","https://www.pokebeach.com/forums/forums/-/index.rss","https://www.pokeguardian.com/feeds/posts/default?alt=rss",
 "https://www.pokemon.com/us/pokemon-news/rss","https://pokemonblog.com/feed/","https://www.serebii.net/rss.xml","https://www.serebii.net/index.xml",
 "https://limitlesstcg.com/feed","https://www.justinbasil.com/feed","https://pkmncards.com/feed/","https://www.pokecommunity.com/forums/-/index.rss",
 "https://pokemongohub.net/feed/","https://www.reddit.com/r/PokemonTCG/.rss","https://press.pokemon.com/en/rss"]
for u in feeds:
    try:
        s,h,b=get(u);t=re.findall(rb"<title[^>]*>(.*?)</title>",b)[:4]
        print("FEED",u,s,len(b),[x[:70].decode("utf8","replace") for x in t])
    except Exception as e: print("FEED",u,"FAIL",str(e)[:120])
for page in ["List_of_Pokémon_Trading_Card_Game_expansions","List_of_Japanese_Pokémon_Trading_Card_Game_expansions"]:
    u="https://bulbapedia.bulbagarden.net/w/api.php?action=parse&format=json&prop=wikitext&origin=*&page="+urllib.parse.quote(page)
    try:
        s,h,b=get(u);print("BULBA",page,s,"ACAO=",h.get("Access-Control-Allow-Origin"),len(b))
        w=json.loads(b)["parse"]["wikitext"]["*"];print("LEN",len(w))
        print(w[:3000]);print("....");
        i=w.find("2026");print(w[max(0,i-4000):i+5000])
    except Exception as e: print("BULBA",page,"FAIL",str(e)[:200])
