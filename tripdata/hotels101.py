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
        # Breakfast and the crossed-out rate also have data-price-value.
        price = card.select_one('.room-price [data-price-value][data-price-currency="RUB"]')
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


def crawl(stop, max_pages=1000, log=print, coverage=None):
    # The server HTML repeats page one. The visible pager updates prices and
    # preserves dates in the browser; follow it instead of guessing HTTP pages.
    from playwright.sync_api import sync_playwright
    out = {}
    complete, reason = False, "limit"
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        context = browser.new_context(locale="ru-RU")
        context.route("**/*", lambda route: route.abort() if route.request.resource_type in {"image", "media", "font"} else route.continue_())
        page = context.new_page()
        page.goto(search_url("101hotels", stop), wait_until="domcontentloaded", timeout=60000)
        page.locator('input[name="price-to"]').fill(str(40000 // stop["nights"]))
        page.locator('input[name="price-to"]').press("Enter")
        page.wait_for_url("**price=**", timeout=30000)
        for step in range(max_pages):
            page.get_by_text(f'Цена за {stop["nights"]} ночей', exact=True).first.wait_for(state="visible", timeout=60000)
            batch = parse_page(page.content(), stop)
            if not batch:
                raise ValueError("101Hotels вернул пустую выдачу; прошлый снимок сохранён")
            previous = len(out)
            out.update({x["externalId"]: x for x in batch})
            log(f"101Hotels: страница {step + 1}, {len(out)} предложений")
            if len(out) == previous:
                reason = "stalled"
                break
            next_page = page.locator(".page-link.next")
            if not next_page.count():
                complete, reason = True, "end"
                break
            next_page.click()
        context.close()
        browser.close()
    if coverage is not None:
        coverage.update(pages=step + 1, priced=len(out), saved=len(out), complete=complete, reason=reason)
    return list(out.values())
