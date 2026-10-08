"""Островок (ostrovok.ru): выдача с ценами на даты поездки и отзывы гостей.

Отдаёт данные в том же виде, что и прежний сборщик trip.com, поэтому анализ отзывов и сборка сайта не меняются:
- crawl_list(...) → список отелей с ценой, координатами, районом, номером и метро;
- fetch_reviews(...) → {"rev": [{"t", "r", "d"}], "cr": оценки по категориям, "total", "fac": удобства}.
Всё — открытые запросы сайта Островка (те же, что делает браузер), без входа в аккаунт.
"""
import json, math, re, time, uuid
import requests

BASE = "https://ostrovok.ru"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
_s = requests.Session()
_s.headers.update({"User-Agent": UA, "Accept": "application/json", "Accept-Language": "ru"})

# Типы жилья Островка → названия, по которым сайт группирует жильё (как было у trip.com)
KIND = {
    "Hotel": "Отель", "Mini-hotel": "Небольшая гостиница", "Boutique_and_Design": "Самобытный объект размещения",
    "Hostel": "Хостел", "Capsule Hotel": "Капсульный отель", "Apartment": "Квартира", "Apart-hotel": "Сервисные апартаменты",
    "Aparthotel": "Сервисные апартаменты", "Guesthouse": "Гостевой дом", "BNB": "Отель типа «постель и завтрак»",
    "Resort": "Курортный отель", "Sanatorium": "Курортный отель", "Cottages_and_Houses": "Дом для отпуска",
    "Villas_and_Bungalows": "Вилла", "Camping": "Кемпинг", "Glamping": "Кемпинг", "Farm": "Фермерский дом",
}
# Фильтры Островка → удобства (русские названия, их понимает сборка сайта)
FAC = {
    "has_pool": "Бассейн", "has_fitness": "Фитнес-центр", "has_meal": "Ресторан", "has_spa": "Спа и сауна",
    "has_parking": "Парковка", "has_airport_transfer": "Трансфер от аэропорта", "has_busyness": "Бизнес-центр",
    "has_internet": "Wi-Fi", "air-conditioning": "Кондиционер", "has_kids": "Подходит для детей",
    "has_pets": "Можно с животными", "has_disabled_support": "Доступная среда", "has_jacuzzi": "Джакузи",
    "kitchen": "Кухня", "has_kitchen": "Кухня",
}
# Мелкие районы Островка важнее крупных: из списка районов отеля берём первый по этому порядку
FINE = ["Китай-город", "Патриаршие пруды", "Кузнецкий Мост", "Арбат"]
COARSE = {"Центр Москвы", "Бульварное кольцо", "Садовое кольцо", "Третье транспортное кольцо"}


def _req(method, url, tries=4, **kw):
    for i in range(tries):
        try:
            r = _s.request(method, url, timeout=60, **kw)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                return None
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2 + 3 * i)
    return None


def neighbourhoods(slug):
    """id района → название, из страницы выдачи города."""
    r = _s.get(f"{BASE}/hotel/{slug}/", headers={"Accept": "text/html"}, timeout=60)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        return {}
    p = json.loads(m.group(1))["props"]["pageProps"]
    return {x["regionId"]: x["name"] for x in (p.get("regionNeighbourhoods") or []) + (p.get("childrenNeighbourhods") or [])}


def _zone(sv, names):
    zs = [names.get(z.get("region_id")) for z in (sv.get("geoblock_v2") or {}).get("neighbourhood_serp_filters") or []]
    zs = [z for z in zs if z]
    for f in FINE:
        if f in zs:
            return f, zs
    for z in zs:
        if z not in COARSE and "округ" not in z:
            return z, zs
    return "", zs


def parse(h, names):
    sv = h.get("static_vm") or {}
    rate = (h.get("rates") or [{}])[0]
    pay = ((rate.get("payment_options") or {}).get("payment_types") or [{}])[0]
    night = pay.get("average_show_price_per_day")
    total = pay.get("show_amount")
    room = rate.get("room_name") or ((rate.get("rooms") or [{}])[0].get("room_name"))
    tags = []
    if (rate.get("cancellation_info") or {}).get("free_cancellation_before"):
        tags.append("Бесплатная отмена")
    meals = ((rate.get("meal_data") or {}).get("meals") or [])
    if any(m.get("has_breakfast") for m in meals):
        tags.append("Завтрак включён")
    zone, zones = _zone(sv, names)
    rt = sv.get("rating") or {}
    return {
        "id": int(h["master_id"]), "oid": h.get("ota_hotel_id"), "name": sv.get("name"),
        "cat": KIND.get(sv.get("kind"), sv.get("kind") or ""), "star": round((sv.get("star_rating") or 0) / 10),
        "lat": sv.get("latitude"), "lng": sv.get("longitude"), "zone": zone, "zones": zones,
        "addr": sv.get("address"), "km": sv.get("search_region_center_distance"),
        "metro": [[m.get("name"), m.get("distance")] for m in (sv.get("nearest_subways") or [])[:3]],
        "score": rt.get("total") or sv.get("rating_total"), "cnt": rt.get("count"),
        "night": round(float(night)) if night else None, "total": round(float(total)) if total else None,
        "room": room, "tags": tags, "fac": [FAC[f] for f in sv.get("serp_filters") or [] if f in FAC],
        "rooms_n": sv.get("rooms_number"), "tc": 0,
    }


def crawl_list(region_id, ci, co, log=print, slug="russia/moscow", max_km=None, max_night=None, center=None, adults=2, max_pages=400):
    """Доступные на даты отели города. ci/co — 'ГГГГММДД'.
    center=(lat, lng) и max_km — только в этом радиусе; max_night — не дороже этой цены за ночь (фильтры самого Островка)."""
    names = neighbourhoods(slug)
    d = lambda s: f"{s[:4]}-{s[4:6]}-{s[6:]}"
    sp = {"arrival_date": d(ci), "departure_date": d(co), "currency": "RUB", "language": "ru",
          "paxes": [{"adults": adults}], "region_id": region_id, "search_uuid": str(uuid.uuid4())}
    j = _req("GET", f"{BASE}/hotel/search/v2/site/serp", params={"body": json.dumps({"session_params": sp})})
    sid = (((j or {}).get("session_info") or {}).get("session") or {}).get("id")
    if not sid:
        log("островок: не удалось начать поиск"); return []
    flt = {}
    if center and max_km:
        flt["point_distance"] = {"lat": center[0], "lng": center[1], "max_distance": max_km}
    if max_night:
        flt["price_per_night"] = [0, max_night]
    body = lambda page: {"session_params": sp, "page": page, "filters": flt, "session_id": sid, "map_hotels": False}
    # ждём, пока поиск соберёт цены у всех поставщиков
    total = 0
    for i in range(40):
        j = _req("POST", f"{BASE}/hotel/search/v2/site/serp", params={"session": sid}, json=body(1)) or {}
        total = j.get("total_av_hotels") or 0
        if j.get("search_finished"):
            break
        time.sleep(3)
    pages = min(math.ceil(total / 20), max_pages)
    log(f"островок: {total} отелей с ценой, {pages} страниц")
    out = {}
    for p in range(1, pages + 1):
        j = _req("POST", f"{BASE}/hotel/search/v2/site/serp", params={"session": sid}, json=body(p)) or {}
        for h in j.get("hotels") or []:
            try:
                it = parse(h, names)
            except Exception:
                continue
            out.setdefault(it["id"], it)
        if p % 25 == 0:
            log(f"  страница {p}/{pages}: {len(out)} отелей")
        time.sleep(0.3)
    return list(out.values())


def fetch_reviews(oid, max_pages=20, fac=None):
    """Отзывы гостей Островка (до max_pages*50 самых свежих) и средние оценки по категориям."""
    url = f"{BASE}/hotel/search/v1/site/reviews"
    d1 = _req("GET", url, params={"hotel": oid, "page": 1, "page_size": 50, "lang": "ru"})
    if d1 is None:
        return None
    total = d1.get("total") or 0
    cl = list(d1.get("reviews") or [])
    for p in range(2, min(math.ceil(total / 50), max_pages) + 1):
        d = _req("GET", url, params={"hotel": oid, "page": p, "page_size": 50, "lang": "ru"})
        if not d or not d.get("reviews"):
            break
        cl += d["reviews"]
        time.sleep(0.15)
    rev, det = [], {}
    for c in cl:
        plus, minus = (c.get("review_plus") or "").strip(), (c.get("review_minus") or "").strip()
        t = ". ".join(x for x in (plus, minus) if x)
        rev.append({"t": t, "r": c.get("rating"), "d": (c.get("review_date") or "")[:10], "plus": plus, "minus": minus})
        for k, v in (c.get("detailed") or {}).items():
            if isinstance(v, (int, float)) and v:
                det.setdefault(k, []).append(v)
    avg = lambda k: round(sum(det[k]) / len(det[k]), 1) if det.get(k) else None
    rated = [c.get("rating") for c in cl if c.get("rating")]
    cr = {"ratingAll": round(sum(rated) / len(rated), 1) if rated else None, "ratingRoom": avg("cleanness"),
          "ratingFacility": avg("room"), "ratingLocation": avg("location"), "ratingService": avg("services"),
          "ratingValue": avg("price"), "showCommentNum": total}
    return {"total": total, "cr": cr, "rev": rev, "fac": {"yes": fac or [], "no": [], "yr": "", "rn": ""}}
