"""Сборщик данных для сайта поездки в Москву (источник — Островок, ostrovok.ru).

  python run.py prices            цены и выдача отелей на даты всех остановок (≈10 мин на город)
  python run.py reviews           докачать отзывы для новых отелей (кеш: cache/reviews)
  python run.py build             анализ → site-data/ (index.json, cities/, prices/)
  python run.py all               prices + reviews + build
  python run.py prices --stop m1  только одна остановка
"""
import argparse, datetime, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from tripdata.paths import CITY_IDS, CONTENT, HOTEL_META, TRIP_DATA, SITE_DATA, read_json, write_json, list_path, load_settings, load_hotels, save_hotels
from tripdata import ostrovok
from tripdata.sources import SOURCES, save_snapshot, set_status, normalize, now
from tripdata import hotels101, browser_sources
from tripdata.build import build_trip, notes_raw, merge_notes, export_site
from tripdata.compact import compact


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def stops():
    return read_json(CONTENT / "stops.json")["stops"]


def cmd_prices(args):
    """Выдача и цены на даты каждой остановки. Три остановки параллельно."""
    meta = read_json(HOTEL_META, {}) or {}
    todo = [s for s in stops() if not args.stop or s["id"] in args.stop]
    keep = {s["anchor"] for s in stops()} | {s["proposed"] for s in stops()} | {i for v in (read_json(CONTENT / "saved.json", {}) or {}).values() for i in v}

    def work(s):
        ci, co = s["ci"].replace("-", ""), s["co"].replace("-", "")
        log(f"{s['id']} {s['title']} {s['ci']}–{s['co']}: собираю выдачу")
        cfg = load_settings()
        center = (s["alat"], s["alng"]) if s.get("alat") else None
        coverage = {}
        try:
            items = ostrovok.crawl_list(CITY_IDS[s["city"]], ci, co, log=log, center=center, max_km=cfg.get("maxKm"), max_night=cfg["limits"].get(s["city"]), coverage=coverage)
            return s, ci, co, items, coverage
        except Exception as error:
            set_status("ostrovok", s, "error", type(error).__name__)
            log(s["id"], "Островок: снимок сохранён", type(error).__name__)
            return s, ci, co, None, coverage

    with ThreadPoolExecutor(3) as ex:
        for s, ci, co, items, coverage in ex.map(work, todo):
            if items is None:
                continue
            priced = sum(1 for h in items if h.get("night"))
            if len(items) < 50 or priced < 20:
                log(f"{s['id']}: подозрительно мало ({len(items)} отелей, {priced} с ценой) — Островок мог ограничить запросы, снимок не обновляю")
                set_status("ostrovok", s, "error", "Получена неполная выдача; прошлый снимок сохранён")
                continue
            stamp = now()
            items = [{**item, "ci": s["ci"], "co": s["co"], "adults": 2, "collectedAt": stamp} for item in items]
            write_json(list_path(s["id"]), items)
            set_status("ostrovok", s, "ok", count=len(items), collected_at=stamp, coverage=coverage)
            for it in items:  # последняя выдача нужна только для отелей из плана и сохранённых
                if it["id"] in keep: meta[str(it["id"])] = {**it, "_ci": ci, "_co": co}
            log(f"{s['id']}: {len(items)} отелей, {priced} с ценой")
    write_json(HOTEL_META, meta)


def needed():
    """Какие отели должны быть с отзывами: в лимите цены хотя бы на одну остановку, из плана, сохранённые."""
    limits = load_settings()["limits"]
    saved = read_json(CONTENT / "saved.json", {}) or {}
    need = {}
    for s in stops():
        ids = need.setdefault(s["city"], set())
        for h in read_json(list_path(s["id"]), []) or []:
            if h.get("night") and h["night"] <= limits.get(s["city"], 5000):
                ids.add(h["id"])
        ids |= {s["anchor"], s["proposed"]}
    for city, lst in saved.items():
        need.setdefault(city, set()).update(lst)
    return need


def cmd_sources(args):
    selected = args.source or [x for x in SOURCES if x != "ostrovok"]
    for s in [s for s in stops() if not args.stop or s["id"] in args.stop]:
        for source in selected:
            if source == "ostrovok":
                continue
            if source == "avito":
                set_status(source, s, "manual", "Нужен импорт предложений, открытых пользователем самостоятельно")
                continue
            if source != "101hotels" and source not in browser_sources.SUPPORTED:
                set_status(source, s, "pending", "Автоматический сбор ещё не подключён; доступен импорт подтверждённых предложений")
                continue
            try:
                coverage = {}
                def checkpoint(items, progress):
                    valid = []
                    for item in items:
                        try:
                            normalize(source, item, s, now())
                            valid.append(item)
                        except ValueError:
                            continue
                    if valid:
                        save_snapshot(source, s, valid, merge=True, complete=False, coverage=progress)
                items = hotels101.crawl(s, max_pages=args.max_pages, log=log, coverage=coverage) if source == "101hotels" else browser_sources.crawl(source, s, max_pages=args.max_pages, log=log, coverage=coverage, checkpoint=checkpoint)
                # Validate cards individually. A malformed distance/rating in one
                # card must not discard the other confirmed offers. Manual
                # imports and the snapshot shrink/empty guards remain strict.
                confirmed = []
                for item in items:
                    try:
                        normalize(source, item, s, now())
                        confirmed.append(item)
                    except ValueError as error:
                        log(source, "Карточка пропущена:", str(error))
                items = confirmed
                save_snapshot(source, s, items, complete=coverage.get("complete", False), merge=not coverage.get("complete", False), coverage=coverage)
                if coverage.get("message"):
                    set_status(source, s, "error", coverage["message"], count=len(items))
                log(source, len(items), "offers saved")
            except Exception as error:
                # No request URLs, cookies, browser state or credentials in logs/cache.
                message = str(error) if isinstance(error, ValueError) else type(error).__name__
                set_status(source, s, "error", message)
                log(source, message)


def cmd_import(args):
    if not args.input or not args.source or len(args.source) != 1:
        raise ValueError("import requires --source <source> --input <JSON file>")
    data = read_json(args.input)
    matches = [s for s in stops() if s["id"] == data.get("stop")]
    if len(matches) != 1 or data.get("source") != args.source[0]:
        raise ValueError("Import source/stop mismatch")
    items = save_snapshot(args.source[0], matches[0], data["items"], mode="manual", complete=data.get("complete", False), merge=not data.get("replace", False), coverage=data.get("coverage"))
    log("Imported", len(items), "offers")


def cmd_reviews(args):
    """Скачивает отзывы новых отелей, анализирует и сохраняет только результат анализа."""
    pages = load_settings().get("maxReviewPages", 20)
    for city, ids in needed().items():
        hot = load_hotels(city)
        todo = sorted(ids) if args.refresh else sorted(i for i in ids if i not in hot)
        log(f"{city}: отзывы нужно скачать для {len(todo)} отелей")
        info = {}
        for st in stops():
            if st["city"] != city: continue
            for h in read_json(list_path(st["id"]), []) or []: info.setdefault(h["id"], h)
        todo = [i for i in todo if i in info and info[i].get("oid")]
        def work(hid):
            d = ostrovok.fetch_reviews(info[hid]["oid"], max_pages=pages, fac=info[hid].get("fac"))
            return hid, (compact(hid, d) if d is not None else None)
        done = 0
        with ThreadPoolExecutor(args.workers) as ex:
            for hid, rec in ex.map(work, todo):
                if rec is None: continue
                hot[hid] = rec; done += 1
                if done % 100 == 0: save_hotels(city, hot); log(f"  {done}/{len(todo)}")
        save_hotels(city, hot)
        log(f"{city}: готово {done}/{len(todo)}")


def cmd_build(args):
    log("анализ отзывов и сборка отелей по остановкам")
    D = build_trip(log=log)
    raw = notes_raw(D)
    merge_notes(D, raw)
    write_json(TRIP_DATA, D)
    idx = export_site(D, built_at=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).date().isoformat())
    log(f"site-data/ готово: {sum(c['count'] for c in idx['cities'].values())} отелей, {idx['reviews']} отзывов")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["prices", "sources", "import", "reviews", "build", "all"])
    p.add_argument("--stop", nargs="*", help="только эти остановки (m1)")
    p.add_argument("--workers", type=int, default=int(os.environ.get("WORKERS", 8)))
    p.add_argument("--refresh", action="store_true", help="перекачать отзывы и для уже скачанных отелей")
    p.add_argument("--source", nargs="+", choices=list(SOURCES), help="Additional sources to collect/import")
    p.add_argument("--input", help="JSON file with source, stop and dated items")
    p.add_argument("--max-pages", type=int, default=1000, help="Safety limit; hitting it records partial coverage")
    a = p.parse_args()
    if a.command in ("prices", "all"): cmd_prices(a)
    if a.command in ("sources", "all"): cmd_sources(a)
    if a.command == "import": cmd_import(a)
    if a.command in ("reviews", "all"): cmd_reviews(a)
    if a.command in ("build", "all"): cmd_build(a)


if __name__ == "__main__":
    sys.exit(main())
