"""Source registry, isolated snapshots and stable IDs. No credentials in cache."""
import datetime as dt
import hashlib
import math
from urllib.parse import urlparse, urlencode
from .paths import CACHE, read_json, write_json, list_path

SOURCES = {
    "ostrovok": ("Островок", "https://ostrovok.ru/hotel/russia/moscow/"),
    "ozon": ("Ozon Travel", "https://www.ozon.ru/travel/hotels/search-new"),
    "yandex": ("Яндекс Путешествия", "https://travel.yandex.ru/hotels/moscow/"),
    "sutochno": ("Суточно.ру", "https://sutochno.ru/front/searchapp/search/"),
    "tvil": ("Твил", "https://tvil.ru/city/moskva/"),
    "101hotels": ("101Hotels", "https://101hotels.com/main/cities/moskva"),
    "avito": ("Авито посуточно", "https://www.avito.ru/moskva/kvartiry/sdam/posutochno"),
    "cian": ("Циан посуточно", "https://www.cian.ru/snyat-kvartiru-posutochno/"),
    "kvartirka": ("Квартирка", "https://kvartirka.com/"),
    "tutu": ("Туту", "https://hotel.tutu.ru/c_russia/moscow/"),
    "onetwotrip": ("OneTwoTrip", "https://www.onetwotrip.com/ru/hotels/search/russia/moscow"),
    "bronevik": ("Броневик", "https://bronevik.com/ru/hotel/russia/moscow/"),
    "mts": ("МТС Travel", "https://travel.mts.ru/"),
}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def search_url(source, stop):
    base = SOURCES[source][1]
    ci, co = stop["ci"], stop["co"]
    ru = lambda x: dt.date.fromisoformat(x).strftime("%d.%m.%Y")
    params = {
        "ostrovok": {"dates": f"{ru(ci)}-{ru(co)}", "guests": 2},
        "ozon": {"Dlts": 2, "checkIn": ci, "checkOut": co, "cityOrRegionId": 140158000, "filters": "price=40000"},
        "yandex": {"adults": 2, "checkinDate": ci, "checkoutDate": co, "geoId": 213, "roomCount": 1, "maxPrice": 40000},
        "101hotels": {"in": ru(ci), "out": ru(co), "adults": 2},
        "tvil": {"o[maleCount]": 2, "o[arrival]": ci, "o[departure]": co},
        "tutu": {"check_in": ci, "check_out": co, "room[0]": "2.", "geo_id": 2657260, "geo_type": "locality", "geo_name": "Москва", "filters[0]": "rangeFilters.price.0-40000-per_stay"},
        "onetwotrip": {"id": 524901, "to": "Москва", "type": "geo", "country_slug": "russia", "city_slug": "moscow", "date_start": ci, "date_end": co, "rooms[0]": 2, "country_code": "RU", "page": 1, "s": "true", "prices[minPriceValue]": 0, "prices[maxPriceValue]": 40000},
        "sutochno": {"guests_adults": 2, "id": 397366, "type": "city", "term": "Москва", "occupied": f"{ci};{co}"},
    }.get(source, {})
    return base + ("?" + urlencode(params) if params else "")


def source_id(source, external_id):
    # Negative 48-bit IDs cannot collide with existing Ostrovok master IDs;
    # safe in JS numbers and the existing Firebase/local-storage mark schema.
    return -int(hashlib.sha256(f"{source}:{external_id}".encode()).hexdigest()[:12], 16)


def snapshot_path(stop_id, source):
    return CACHE / "sources" / source / f"{stop_id}.json.gz"


def valid_url(source, url):
    try:
        p = urlparse(url or "")
        port = p.port
    except ValueError:
        return False
    root = urlparse(SOURCES[source][1]).hostname
    root = root.removeprefix("www.")
    return bool(p.scheme == "https" and not p.username and not p.password and port in (None, 443) and p.hostname and (p.hostname == root or p.hostname.endswith("." + root)))


def normalize(source, item, stop, collected_at):
    if not item.get("externalId") or not item.get("name") or not valid_url(source, item.get("url")):
        raise ValueError("Объект должен иметь externalId, name и HTTPS-ссылку своей площадки")
    total = item.get("total")
    if not isinstance(total, (int, float)) or isinstance(total, bool) or not math.isfinite(total) or total <= 0:
        raise ValueError("Нужна полная цена RUB за весь срок на выбранные даты для двоих")
    if item.get("currency", "RUB") != "RUB":
        raise ValueError("Поддерживаются только цены в RUB")
    if item.get("ci") != stop["ci"] or item.get("co") != stop["co"] or item.get("adults") != 2:
        raise ValueError("Даты/гости предложения не соответствуют остановке")
    score, scale = item.get("score"), item.get("scoreMax", 10)
    if scale not in (5, 10, 100) or (score is not None and (not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= scale)):
        raise ValueError("Некорректная шкала рейтинга")
    out = {**item, "id": source_id(source, str(item["externalId"])), "source": source,
           "total": total, "night": round(total / stop["nights"]),
           "sourceScore": score, "scoreMax": scale, "score": score * 10 / scale if score is not None else None,
           "collectedAt": collected_at, "tags": item.get("tags") or [], "fac": item.get("fac") or []}
    cancel = item.get("free")
    if cancel is not None and not isinstance(cancel, bool):
        raise ValueError("free должен быть true, false или null (неизвестно)")
    out["free"] = cancel
    for key, lo, hi in (("lat", -90, 90), ("lng", -180, 180), ("km", 0, 1000)):
        value = out.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi):
            raise ValueError("Некорректные координаты или расстояние")
    if (out.get("lat") is None) != (out.get("lng") is None):
        raise ValueError("Нужны обе координаты либо ни одной")
    if cancel is True and "Бесплатная отмена" not in out["tags"]:
        out["tags"].append("Бесплатная отмена")
    return out


def save_snapshot(source, stop, items, mode="automatic", complete=False, merge=False, coverage=None):
    if source not in SOURCES or source == "ostrovok":
        raise ValueError("Неизвестный дополнительный источник")
    stamp = now()
    normalized = [normalize(source, h, stop, stamp) for h in items]
    if not normalized:
        raise ValueError("Пустой снимок: предыдущие предложения сохранены")
    ids = [x["id"] for x in normalized]
    if len(set(ids)) != len(ids):
        raise ValueError("Дубли externalId в снимке")
    previous = read_json(snapshot_path(stop["id"], source), {}) or {}
    if merge and previous.get("ci") == stop["ci"] and previous.get("co") == stop["co"] and previous.get("adults") == 2:
        combined = {item["id"]: item for item in previous.get("items", [])}
        combined.update({item["id"]: item for item in normalized})
        normalized = list(combined.values())
    if previous.get("ci") == stop["ci"] and previous.get("co") == stop["co"] and len(normalized) < len(previous.get("items", [])) * .5:
        raise ValueError("Выдача уменьшилась больше чем вдвое: предыдущий снимок сохранён")
    write_json(snapshot_path(stop["id"], source), {"ci": stop["ci"], "co": stop["co"], "adults": 2,
               "collectedAt": stamp, "mode": mode, "complete": complete, "coverage": coverage, "items": normalized})
    set_status(source, stop, "ok", "", len(normalized))
    return normalized


def set_status(source, stop, state, message="", count=None, collected_at=None, coverage=None):
    path = CACHE / "source_status.json"
    statuses = read_json(path, {}) or {}
    key = f"{stop['id']}:{source}"
    previous = statuses.get(key, {})
    statuses[key] = {"state": state, "attemptedAt": now(), "message": message, "count": count,
                     "collectedAt": collected_at or previous.get("collectedAt"),
                     "coverage": coverage if coverage is not None else previous.get("coverage")}
    write_json(path, statuses)


def load_list(stop):
    items = [{**h, "source": "ostrovok"} for h in read_json(list_path(stop["id"]), []) or []
             if (h.get("ci") is None or (h.get("ci") == stop["ci"] and h.get("co") == stop["co"] and h.get("adults") == 2))]
    for source in SOURCES:
        if source == "ostrovok":
            continue
        snap = read_json(snapshot_path(stop["id"], source), {}) or {}
        if snap.get("ci") == stop["ci"] and snap.get("co") == stop["co"] and snap.get("adults") == 2:
            items.extend(snap.get("items") or [])
    return items


def source_statuses(stops):
    attempts = read_json(CACHE / "source_status.json", {}) or {}
    result = {}
    for stop in stops:
        result[stop["id"]] = []
        for source, (label, _) in SOURCES.items():
            snap = read_json(snapshot_path(stop["id"], source), {}) or {}
            matching = snap.get("ci") == stop["ci"] and snap.get("co") == stop["co"] and snap.get("adults") == 2
            count = len(snap.get("items") or []) if matching else 0
            status = attempts.get(f"{stop['id']}:{source}", {})
            if source == "ostrovok":
                count = len(read_json(list_path(stop["id"]), []) or [])
            result[stop["id"]].append({"id": source, "label": label, "url": search_url(source, stop),
                "count": count, "state": status.get("state", "ok" if count else "pending"),
                "message": status.get("message", ""), "attemptedAt": status.get("attemptedAt"),
                "collectedAt": snap.get("collectedAt") if matching else status.get("collectedAt"),
                "mode": snap.get("mode", "automatic" if source == "ostrovok" else None),
                "complete": bool(status.get("coverage", {}).get("complete")) if source == "ostrovok" and status.get("coverage") else bool(snap.get("complete")),
                "coverage": status.get("coverage") if source == "ostrovok" else snap.get("coverage"), "automatic": source in {"ostrovok", "101hotels", "ozon", "yandex", "sutochno", "tvil", "tutu", "onetwotrip"}})
    return result
