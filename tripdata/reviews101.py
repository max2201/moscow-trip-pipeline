"""Analyze the review texts actually published in 101Hotels property HTML.

The visible first sample is not the entire review archive. Store counters only.
"""
import re
import requests
from bs4 import BeautifulSoup
from .sources import valid_url, now

MONTHS = dict(zip(("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"), range(1, 13)))


def parse_reviews(html):
    soup = BeautifulSoup(html, "html.parser")
    reviews, seen = [], set()
    for item in soup.select(".hotel-reviews__item"):
        body = item.select_one(".hotel-reviews__item-text")
        if not body:
            continue
        text = body.get_text(" ", strip=True)
        key = item.get("data-id") or text
        if key in seen or len(text) <= 3:
            continue
        seen.add(key)
        date = item.select_one(".hotel-reviews__item-client-dates")
        match = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", date.get_text() if date else "")
        iso = f"{match[3]}-{MONTHS[match[2]]:02d}-{int(match[1]):02d}" if match and match[2] in MONTHS else ""
        score = item.select_one(".hotel-reviews__item-score-number")
        try:
            value = float(score.get_text(strip=True).replace(",", ".")) if score else None
        except ValueError:
            value = None
        reviews.append({"t": text, "r": value if value is not None and 0 <= value <= 10 else None, "d": iso})
    score = soup.select_one(".hotel-reviews__total-score")
    count = soup.select_one(".hotel-reviews__total-reviews-count")
    try:
        rating = float(score.get_text(strip=True).replace(",", ".")) if score else None
    except ValueError:
        rating = None
    digits = re.sub(r"\D", "", count.get_text() if count else "")
    return {"rev": reviews, "cr": {"ratingAll": rating, "showCommentNum": int(digits) if digits else 0}, "total": int(digits) if digits else 0, "fac": {"yes": []}}


def fetch_reviews(item):
    if not valid_url("101hotels", item.get("url")):
        return None
    try:
        response = requests.get(item["url"], timeout=30)
        if response.status_code != 200:
            return None
        data = parse_reviews(response.content)
        if not data["rev"]:
            return None
        # Keep the already verified offer rating if HTML omits it.
        if data["cr"]["ratingAll"] is None:
            data["cr"]["ratingAll"] = item.get("score")
        data["fac"]["yes"] = item.get("fac") or []
        data["reviewCoverage"] = {"source": "101hotels", "url": item["url"], "collectedAt": now(), "complete": len(data["rev"]) >= data["total"] > 0, "reason": "visible_sample"}
        return data
    except requests.RequestException:
        return None
