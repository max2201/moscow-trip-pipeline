import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from tripdata.paths import write_json, read_json
from tripdata.compact import compact
from tripdata.rating import rating_components
from tripdata.reviews101 import parse_reviews
from tripdata.reviews_sutochno import parse_reviews as suto_reviews


class RatingTest(unittest.TestCase):
    def test_interrupted_snapshot_write_preserves_previous_json_and_gzip(self):
        for name in ("snapshot.json", "snapshot.json.gz"):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / name
                write_json(path, {"saved": 42})
                with patch("tripdata.paths.json.dump", side_effect=RuntimeError("interrupted")):
                    with self.assertRaises(RuntimeError): write_json(path, {"saved": 1})
                self.assertEqual(read_json(path), {"saved": 42})
    def test_suto_snippets_exclude_rating_label_and_owner_reply(self):
        html = '''<section class="review-section"><div class="review-section__rating"><div class="rating-badge">8,0</div><time datetime="2026-07-01"></time></div><div class="votes-section__votes"><div class="comment-text__comment"><p class="comment-text__text">Великолепно</p></div><div class="comment-text__comment"><p class="comment-text__text">Грязное бельё и тараканы… <button>Ещё</button></p></div></div><div class="owner-answer"><p class="comment-text__text">Мы всё исправили</p></div></section>'''
        reviews = suto_reviews(html * 2)
        self.assertEqual(len(reviews), 1)
        self.assertNotIn("исправили", reviews[0]["t"])
        self.assertNotIn("Великолепно", reviews[0]["t"])
        self.assertEqual(reviews[0]["r"], 8)
        self.assertEqual(reviews[0]["d"], "2026-07-01")
    def test_platform_count_is_not_analyzed_text(self):
        empty = compact(1, {"rev": []})["a"]
        parts, info = rating_components(9.8, 10000, empty, {})
        self.assertEqual(info["basis"], "platform")
        self.assertEqual(info["textCount"], 0)
        self.assertEqual(parts[1:4], [0, 0, 0])
        self.assertLess(parts[4], 0)
        few, _ = rating_components(9.8, 1, empty, {})
        self.assertLess(sum(few), sum(parts))
        sample = compact(1, {"rev": [{"t": "Всё понравилось, чисто и удобно", "r": 10, "d": "2026-10-01"}] * 5})["a"]
        with_texts, _ = rating_components(9.8, 10000, sample, {})
        self.assertGreaterEqual(sum(with_texts), sum(parts) - .5)

    def test_absent_or_invalid_rating_is_reserved_not_guest_evidence(self):
        empty = compact(1, {"rev": []})["a"]
        for score in (None, 0, float("nan"), 11):
            parts, info = rating_components(score, 0, empty, {})
            self.assertEqual(parts, [6, 0, 0, 0, 0])
            self.assertEqual(info["basis"], "none")
            self.assertEqual(info["confidence"], "none")

    def test_actual_text_and_money_risks_change_ranking(self):
        rec = compact(1, {"rev": [{"t": "Грязное бельё, удержали залог и не вернули депозит", "r": 3, "d": "2026-10-01"}]})
        parts, info = rating_components(9, 50, rec["a"], rec["nt"][2])
        clean, _ = rating_components(9, 50, {**rec["a"], "neg": 0}, {})
        self.assertEqual(info["basis"], "texts")
        self.assertEqual(info["textCount"], 1)
        self.assertLess(sum(parts), sum(clean))

    def test_101_reads_guest_body_not_staff_response_and_deduplicates(self):
        item = '''<div class="hotel-reviews__item" data-id="1"><p class="hotel-reviews__item-client-dates">2 октября 2026</p><div class="hotel-reviews__item-score-number">4,5</div><p class="hotel-reviews__item-text">В номере тараканы, грязное бельё</p><p class="staff-response">Все проблемы решены</p></div>'''
        data = parse_reviews('<div class="hotel-reviews__total-score">8.9</div><div class="hotel-reviews__total-reviews-count">На основе 1 234 отзывов</div>' + item * 2)
        self.assertEqual(len(data["rev"]), 1)
        self.assertEqual(data["rev"][0]["d"], "2026-10-02")
        self.assertEqual(data["rev"][0]["r"], 4.5)
        self.assertNotIn("решены", data["rev"][0]["t"])
        self.assertEqual(data["total"], 1234)
        self.assertEqual(compact(1, data)["a"]["c"]["roach"], 1)
