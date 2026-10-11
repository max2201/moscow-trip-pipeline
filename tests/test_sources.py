import copy
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from tripdata import sources
from tripdata.build import eligible_offer, build_trip, room_flags
from tripdata.compact import compact
from tripdata.hotels101 import parse_page
from tripdata.paths import read_json, CONTENT

STOP = {"id": "m1", "city": "msk", "ci": "2026-10-14", "co": "2026-10-22", "nights": 8,
        "alat": 55.75393, "alng": 37.62079}
SETTINGS = {"maxTotal": 40000, "maxKm": 12, "limits": {"msk": 5000}}

def offer(**changes):
    return {"externalId": "hotel-1", "name": "Hotel", "url": "https://travel.yandex.ru/hotels/moscow/hotel-1/",
            "ci": STOP["ci"], "co": STOP["co"], "adults": 2, "total": 40000,
            "score": 4.5, "scoreMax": 5, "cnt": 100, **changes}

class SourcesTest(unittest.TestCase):
    def test_late_collection_failure_keeps_checkpoint_and_old_offers(self):
        from run import cmd_sources
        def fail_after_checkpoint(*args, **kwargs):
            kwargs["checkpoint"]([offer(externalId="new")], {"pages": 1, "reason": "in_progress", "complete": False})
            raise TimeoutError("late page failed")
        with tempfile.TemporaryDirectory() as directory, patch.object(sources, "CACHE", Path(directory)), \
                patch("run.stops", return_value=[STOP]), patch("run.log"), \
                patch("run.browser_sources.crawl", side_effect=fail_after_checkpoint):
            sources.save_snapshot("yandex", STOP, [offer(externalId="old")])
            cmd_sources(Namespace(source=["yandex"], stop=None, max_pages=1))
            snap = read_json(sources.snapshot_path("m1", "yandex"))
            self.assertEqual({x["externalId"] for x in snap["items"]}, {"old", "new"})
            self.assertFalse(snap["complete"])
            self.assertEqual(snap["coverage"]["pages"], 1)

    def test_automatic_bad_card_does_not_discard_valid_offers(self):
        from run import cmd_sources
        with tempfile.TemporaryDirectory() as directory, patch.object(sources, "CACHE", Path(directory)), \
                patch("run.stops", return_value=[STOP]), patch("run.log"), \
                patch("run.browser_sources.crawl", return_value=[offer(), offer(externalId="bad", km=1200)]):
            args = Namespace(source=["yandex"], stop=None, max_pages=1)
            cmd_sources(args)
            path = sources.snapshot_path("m1", "yandex")
            self.assertEqual(len(read_json(path)["items"]), 1)
            original = path.read_bytes()
            with patch("run.browser_sources.crawl", return_value=[offer(km=1200)]):
                cmd_sources(args)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(sources.source_statuses([STOP])["m1"][2]["state"], "error")

    def test_total_boundary_uses_whole_stay_without_rounding_down(self):
        for price, allowed in ((39999, True), (40000, True), (40000.01, False), (40000.001, False), (0, False)):
            normalized = sources.normalize("yandex", offer(total=price), STOP, "stamp") if price else offer(total=0)
            self.assertEqual(eligible_offer(normalized, STOP, SETTINGS), allowed)

    def test_wrong_dates_guests_currency_and_nonfinite_prices_rejected(self):
        for changes in ({"ci": "2026-10-15"}, {"co": "2026-10-23"}, {"adults": 1}, {"currency": "USD"},
                        {"total": float("nan")}, {"total": float("inf")}, {"total": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                sources.normalize("yandex", offer(**changes), STOP, "stamp")

    def test_rating_and_unknown_cancellation(self):
        item = sources.normalize("yandex", offer(), STOP, "stamp")
        self.assertEqual(item["score"], 9)
        self.assertIsNone(item["free"])
        self.assertNotIn("Бесплатная отмена", item["tags"])

    def test_ids_preserve_namespace_and_js_precision(self):
        a = sources.source_id("ozon", "42")
        self.assertLess(a, 0)
        self.assertLess(abs(a), 2**53)
        self.assertEqual(a, sources.source_id("ozon", "42"))
        self.assertNotEqual(a, sources.source_id("yandex", "42"))

    def test_only_provider_https_links(self):
        for url in ("javascript:alert(1)", "https://travel.yandex.ru.evil.com/", "https://evil.com/",
                    "https://password@travel.yandex.ru/", "https://travel.yandex.ru:bad/"):
            self.assertFalse(sources.valid_url("yandex", url), url)
        self.assertTrue(sources.valid_url("ozon", "https://www.ozon.ru/travel/hotels/"))

    def test_failed_snapshot_preserves_previous_and_changed_dates_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sources, "CACHE", Path(directory)):
            sources.save_snapshot("yandex", STOP, [offer(externalId=str(i)) for i in range(10)])
            path = sources.snapshot_path("m1", "yandex")
            original = path.read_bytes()
            for items in ([], [offer()], [offer(), offer()]):
                with self.assertRaises(ValueError):
                    sources.save_snapshot("yandex", STOP, items)
                self.assertEqual(path.read_bytes(), original)
            changed = {**STOP, "ci": "2026-10-15"}
            self.assertFalse(any(h.get("source") == "yandex" for h in sources.load_list(changed)))

    def test_manual_import_merges_without_erasing_previous_offers(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sources, "CACHE", Path(directory)):
            initial = sources.save_snapshot("yandex", STOP, [offer(externalId="a")])[0]
            merged = sources.save_snapshot("yandex", STOP, [offer(externalId="b")], mode="manual", merge=True)
            self.assertEqual(len(merged), 2)
            self.assertEqual(merged[0]["collectedAt"], initial["collectedAt"])

    def test_radius_and_missing_coordinates(self):
        self.assertFalse(eligible_offer(offer(km=12.01), STOP, SETTINGS))
        self.assertTrue(eligible_offer(offer(km=12), STOP, SETTINGS))
        self.assertTrue(eligible_offer(offer(), STOP, SETTINGS))
        with self.assertRaises(ValueError):
            sources.normalize("yandex", offer(lat=55.7), STOP, "stamp")

    def test_unread_reviews_do_not_create_analysis(self):
        item = sources.normalize("yandex", offer(), STOP, "stamp")
        with patch("tripdata.build.load_list", return_value=[item]), patch("tripdata.build.load_hotels", return_value={}):
            data = build_trip(log=lambda *a: None)
        hotel = data["cities"]["msk"]["hotels"][0]
        self.assertEqual(hotel["an"], 0)
        self.assertIsNotNone(hotel["cp"])
        self.assertEqual(hotel["rating"]["basis"], "platform")
        self.assertEqual(hotel["sc"], 9)
        self.assertEqual(hotel["rv"], 100)
        self.assertIsNone(data["stops"][0]["prices"][item["id"]][2])

    def test_shared_and_dorm_rooms(self):
        self.assertTrue(room_flags("2 × Общих номера", "Hotel")[0])
        self.assertTrue(room_flags("Четырёхместный номер с общей кухней и туалетом", "Hotel")[1])

    def test_101_parser_uses_full_total_and_rejects_undated_page(self):
        html = '''<input name="in" value="14.10.2026"><input name="out" value="22.10.2026">
        <article class="item-inner"><div data-hotel_id="123"></div><div class="item-name">
        <a href="/main/cities/moskva/hotel.html"><span itemprop="name">Hotel</span></a></div>
        <div class="meal-type"><span data-price-value="1550" data-price-currency="RUB">Завтрак</span></div>
        <div class="room-old-price"><span data-price-value="41000" data-price-currency="RUB">Старая цена</span></div>
        <div class="room-price"><span data-price-value="40000" data-price-currency="RUB">40000 за 8 ночей</span></div></article>'''
        self.assertEqual(parse_page(html, STOP)[0]["total"], 40000)
        with self.assertRaises(ValueError):
            parse_page(html.replace("22.10.2026", "23.10.2026"), STOP)

    def test_exported_snapshot_all_totals_within_limit(self):
        data = read_json(Path(__file__).resolve().parents[1] / "site-data/prices/m1.json")
        self.assertTrue(data)
        self.assertTrue(all(p[1] is not None and 0 < p[1] <= 40000 for p in data.values()))

if __name__ == "__main__":
    unittest.main()
