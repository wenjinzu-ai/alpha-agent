from duckduckgo_search import DDGS

with DDGS() as ddgs:
    results = list(ddgs.text("Hermes Agent AI framework", max_results=3))
    for r in results:
        print(r["title"])
        print(f"  {r['body'][:150]}")
        print(f"  {r['href']}")
        print()