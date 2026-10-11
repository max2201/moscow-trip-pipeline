"""Read guest review snippets rendered in public Sutochno property pages."""
import requests
from bs4 import BeautifulSoup
from .sources import valid_url, now

RATING_LABELS = {"великолепно", "отлично", "хорошо", "нормально", "удовлетворительно", "плохо", "ужасно"}


def parse_reviews(html):
    soup = BeautifulSoup(html, "html.parser")
    reviews, seen = [], set()
    for item in soup.select("section.review-section"):
        # Owner responses and the automatically generated rating label are excluded.
        chunks = []
        for p in item.select(".votes-section__votes > .comment-text__comment > .comment-text__text"):
            text = " ".join(p.stripped_strings)
            if text.endswith(" Ещё"):
                text = text[:-4].rstrip()
            if len(text) > 3 and text.lower() not in RATING_LABELS:
                chunks.append(text)
        text = ". ".join(chunks)
        if not text:
            continue
        date = item.select_one("time[datetime]")
        iso = date["datetime"][:10] if date else ""
        key = (text, iso)
        if key in seen:
            continue
        seen.add(key)
        score = item.select_one(".review-section__rating .rating-badge")
        try:
            value = float(score.get_text(strip=True).replace(",", ".")) if score else None
        except ValueError:
            value = None
        reviews.append({"t": text, "r": value if value is not None and 0 <= value <= 10 else None, "d": iso})
    return reviews


def fetch_reviews(item):
    if not valid_url("sutochno", item.get("url")):
        return None
    try:
        response = requests.get(item["url"], timeout=30)
        if response.status_code != 200:
            return None
        reviews = parse_reviews(response.content)
        if not reviews:
            return None
        return {"rev": reviews, "cr": {"ratingAll": item.get("score"), "showCommentNum": item.get("cnt") or 0},
                "total": item.get("cnt") or 0, "fac": {"yes": item.get("fac") or []},
                "reviewCoverage": {"source": "sutochno", "url": item["url"], "collectedAt": now(), "complete": False, "reason": "visible_sample", "truncated": True}}
    except requests.RequestException:
        return None
