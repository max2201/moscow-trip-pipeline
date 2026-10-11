"""Offline DOM fixtures in CI: no third-party network calls or browser credentials."""
import os
import unittest
from pathlib import Path

STOP = {"ci": "2026-10-14", "co": "2026-10-22", "nights": 8}
SCRIPT = (Path(__file__).resolve().parents[1] / "tripdata/collect_cards.js").read_text(encoding="utf-8")

@unittest.skipUnless(os.environ.get("RUN_DOM_TESTS") == "1", "DOM fixtures run in CI Chromium")
class CardsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.driver = sync_playwright().start()
        cls.browser = cls.driver.chromium.launch()
        cls.page = cls.browser.new_page()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.driver.stop()

    def collect(self, source, html):
        self.page.set_content(html)
        return self.page.evaluate(SCRIPT, {"source": source, "stop": STOP})

    def test_tvil_public_price_and_visible_rating_not_member_discount(self):
        html = '''<div>96 Превосходно <span>434 отзыва</span>
        <a href="https://tvil.ru/city/moskva/hotels/42/?from=search&o[arrival]=2026-10-14&o[departure]=2026-10-22&o[maleCount]=2">Hotel</a>
        Центр ~ 10 км <div data-testid="price-item-all">Для всех <span data-testid="price-value">36 270₽</span> 8 ночей</div>
        <div>Для друзей 29 016₽</div><meta itemprop="reviewCount" content="999"></div>'''
        item = self.collect("tvil", html)[0]
        self.assertEqual((item["total"], item["score"], item["cnt"]), (36270, 96, 434))

    def test_sutochno_discounted_whole_stay_and_room_type(self):
        html = '''<div class="card"><a class="card-content" href="https://sutochno.ru/front/searchapp/detail/42?occupied=2026-10-14;2026-10-22&guests_adults=2">
        <h2>Двухместный номер</h2><div class="card-content__object-subtext">Гостиница</div>8,7 32 отзыва</a>
        16 000 ₽ <span>15 120 ₽ за 8 суток</span>1 890 ₽ за сутки</div>'''
        item = self.collect("sutochno", html)[0]
        self.assertEqual(item["total"], 15120)
        self.assertEqual(item["cat"], "Отель")
        self.assertEqual(item["room"], "Двухместный номер")

    def test_tutu_full_price_not_stars_old_price_or_cashback(self):
        html = '''<div><a href="https://hotel.tutu.ru/h_test/?check_in=2026-10-14&check_out=2026-10-22&room[0]=2.">Test</a>
        <span>9,0 96 отзывов</span>Отель 3 <div>19 ⁠368 ⁠₽</div><div>21 520 ₽</div>Кешбэк 581 <p>2 421 ₽ за ночь, 8 ночей</p></div>'''
        item = self.collect("tutu", html)[0]
        self.assertEqual(item["total"], 19368)

    def test_yandex_current_total_and_wrong_dates(self):
        html = '''<div><h3 itemprop="name"><a href="https://travel.yandex.ru/hotels/moscow/test/?checkinDate=2026-10-14&checkoutDate=2026-10-22&adults=2">Test</a></h3>
        4,5 100 отзывов <span data-qa="price">39 999 ₽</span><span>45 000 ₽</span>8 ночей 5 000 ₽ за ночь Двухместный номер Выбрать</div>'''
        self.assertEqual(self.collect("yandex", html)[0]["total"], 39999)
        self.assertEqual(self.collect("yandex", html.replace("2026-10-22", "2026-10-23")), [])

    def test_ozon_full_eight_night_total(self):
        html = '''<div><a href="https://www.ozon.ru/travel/hotels/product/test-42/?checkIn=2026-10-14&checkOut=2026-10-22&Dlts=2">Test</a>
        4,9 866 отзывов 34 988 ₽ 8 ночей • 2 взрослых 4 374 ₽ за ночь</div>'''
        self.assertEqual(self.collect("ozon", html)[0]["total"], 34988)
