"""Moduł analizy forów i okazji lotniczych.
RSS Fly4free.pl (https://www.fly4free.pl/feed/) co 2 h z deduplikacją po linku.
Tylko oficjalne/publiczne kanały, niskie tempo.
"""
import re, requests, time, xml.etree.ElementTree as ET
from core import db, alerts, vault

UA = "OrbitBots/0.1 by orbit-user (flight deal research; contact via app owner)"

db.init("""
CREATE TABLE IF NOT EXISTS fly4free_deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    link TEXT UNIQUE NOT NULL,
    pub_date TEXT,
    price TEXT,
    origin TEXT,
    created TEXT DEFAULT CURRENT_TIMESTAMP
);
""")

POLISH_CITIES = [
    "Warszaw", "Modlin", "Kraków", "Krakow", "Katowic", "Gdańsk", "Gdansk",
    "Wrocław", "Wroclaw", "Poznań", "Poznan", "Łódź", "Lodz", "Rzeszów", "Rzeszow",
    "Lublin", "Szczecin", "Bydgoszcz", "Radom", "Olsztyn", "Polsce", "Polski"
]

def fly4free_rss(url="https://www.fly4free.pl/feed/"):
    """Pobiera surowe wpisy z RSS Fly4free."""
    r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    # Usunięcie wiodących białych znaków przed <?xml (WordPress dodaje \t\t)
    xml_data = r.content.strip()
    root = ET.fromstring(xml_data)
    items = []
    for item in root.iter("item"):
        t = item.findtext("title") or ""
        l = item.findtext("link") or ""
        d = item.findtext("pubDate") or ""
        items.append(dict(title=t.strip(), link=l.strip(), pubDate=d.strip(), source="fly4free"))
    return items

def extract_deal_info(title: str):
    """Wykrywa cenę i miasto wylotu z tytułu posta."""
    # Szukaj ceny np. "od 89 PLN", "za 120 zł", "za 350 PLN"
    price_match = re.search(r'(?:za|od|ceny od)?\s*(\d+[\s\d]*)\s*(?:zł|PLN|EUR|€)', title, re.IGNORECASE)
    price = price_match.group(0).strip() if price_match else ""

    # Szukaj polskiego miasta
    origin = ""
    for city in POLISH_CITIES:
        if city.lower() in title.lower():
            origin = city
            break
    return origin, price

def fetch_and_save_fly4free(url="https://www.fly4free.pl/feed/"):
    """Pobiera wpisy, zapisuje do bazy z deduplikacją po linku i generuje alerty dla okazji z Polski."""
    items = fly4free_rss(url)
    new_count = 0
    for item in items:
        link = item["link"]
        title = item["title"]
        pub_date = item["pubDate"]
        origin, price = extract_deal_info(title)

        # Sprawdź czy już istnieje
        existing = db.query("SELECT id FROM fly4free_deals WHERE link = ?", (link,))
        if existing:
            continue

        db.execute(
            "INSERT INTO fly4free_deals(title, link, pub_date, price, origin) VALUES (?, ?, ?, ?, ?)",
            (title, link, pub_date, price, origin)
        )
        new_count += 1

        # Alert gdy okazja z polskiego miasta i cena
        if origin or price:
            alerts.notify(
                "flights",
                f"✈ Okazja Fly4free: {title[:80]}",
                f"{title}\nCena/Wylot: {price or 'okazja'} | {origin or 'Polska'}\nLink: {link}"
            )

    return {"new": new_count, "total_saved": len(db.query("SELECT id FROM fly4free_deals"))}

def reddit_status():
    return "ok" if vault.get("reddit") else "brak klucza (używany publiczny JSON — z tego serwera Reddit zwraca 403)"

def reddit(sub="flights", limit=25):
    cred = vault.get("reddit")
    if cred:
        tok = requests.post("https://www.reddit.com/api/v1/access_token",
                            auth=(cred["client_id"], cred["client_secret"]),
                            data={"grant_type": "client_credentials"},
                            headers={"User-Agent": UA}, timeout=20).json()["access_token"]
        r = requests.get(f"https://oauth.reddit.com/r/{sub}/new", params={"limit": limit},
                         headers={"Authorization": "bearer " + tok, "User-Agent": UA}, timeout=20)
    else:
        time.sleep(2)
        r = requests.get(f"https://www.reddit.com/r/{sub}/new.json", params={"limit": limit},
                         headers={"User-Agent": UA}, timeout=20)
    r.raise_for_status()
    return [dict(title=c["data"]["title"], link="https://reddit.com" + c["data"]["permalink"],
                 text=c["data"].get("selftext", "")[:2000], source="reddit/" + sub)
            for c in r.json()["data"]["children"]]
