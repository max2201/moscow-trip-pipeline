"""101Hotels server-rendered dated offers (price-value is the whole stay)."""
import datetime as dt
import json
import re
import time
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from .sources import search_url


def parse_page(html, stop):
    soup = BeautifulSoup(html, "html.parser")
    ru = lambda s: dt.date.fromisoformat(s).strftime("%d.%m.%Y")
    for field, date in [("in", stop["ci"]), ("out", stop["co"])]:
        node = soup.select_one(f'input[name="{field}"]')
        if not node or node.get("value") != ru(date):
            raise ValueError("101Hotels не подтвердил даты поиска")
    out = []
    for card in soup.select("article.item-inner"):
        identity = card.select_one("[data-hotel_id]")
        name = card.select_one('.item-name [itemprop="name"]')
        link = card.select_one('.item-name a[href]')
        price = card.select_one('[data-price-value][data-price-currency="RUB"]')
        if not all([identity, name, link, price]):
            continue
        value = float(price["data-price-value"])
        if value <= 0:
            continue
        def meta(key):
            e = card.select_one(f'[itemprop="{key}"]')
            return e.get("content") if e else None
        coords = card.select_one("[data-hotel-coords]")
        lat, lng = json.loads(coords["data-hotel-coords"]) if coords else (None, None)
        stars = card.select_one(".stars")
        star = re.search(r"stars_(\d)", " ".join(stars.get("class", []))) if stars else None
        rating = card.select_one('[itemprop="ratingValue"]')
        score = re.search(r"[\d.]+", rating.get_text()) if rating else None
        url = urljoin("https://101hotels.com", link["href"]) + search_url("101hotels", stop).split("moskva", 1)[1]
        text = card.get_text(" ", strip=True)
        out.append({"externalId": identity["data-hotel_id"], "name": name.get_text(strip=True),
                    "url": url, "ci": stop["ci"], "co": stop["co"], "adults": 2,
                    "total": value, "score": float(score[0]) if score else None, "scoreMax": 10,
                    "cnt": int(meta("reviewCount") or 0), "lat": lat, "lng": lng,
                    "addr": card.select_one(".item-address").get_text(strip=True) if card.select_one(".item-address") else "",
                    "star": int(star[1]) if star else 0, "cat": "Квартира" if re.search("Квартира|Апартамент", name.get_text(), re.I) else "Хостел" if "хостел" in name.get_text().lower() else "Отель",
                    "free": True if "Бесплатная отмена" in text else None,
                    "fac": [e.get("title") for e in card.select(".services-list .include[title]")], "room": ""})
    return out


def crawl(stop, max_pages=30, log=print):
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"})
    out = {}
    for page in range(1, max_pages + 1):
        response = session.get(search_url("101hotels", stop), params={"page": page}, timeout=45)
        response.raise_for_status()
        response.encoding = "utf-8"
        batch = parse_page(response.text, stop)
        if not batch:
            raise ValueError("101Hotels вернул пустую выдачу")
        previous = len(out)
        out.update({x["externalId"]: x for x in batch})
        if len(out) == previous:
            break
        log(f"101Hotels: страница {page}, {len(out)} предложений")
        time.sleep(.5)
    return list(out.values())
