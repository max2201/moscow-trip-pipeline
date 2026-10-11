import unittest
from tripdata.housing import housing_features


class HousingTest(unittest.TestCase):
    def test_bathroom_and_shower_are_not_bathtub_confirmation(self):
        for room in ("Собственная ванная комната", "Общая ванная комната", "Номер с ванной комнатой", "Номер (душ)"):
            self.assertIsNone(housing_features({"room": room})["bathtub"])
        self.assertTrue(housing_features({"room": "Номер с ванной (ванна)"})["bathtub"])
        self.assertFalse(housing_features({"room": "Номер без ванны, только душ"})["bathtub"])
        self.assertFalse(housing_features({"room": "Ванна отсутствует"})["bathtub"])
        self.assertIsNone(housing_features({"room": "Номер без джакузи"})["bathtub"])

    def test_room_count_not_guests_bedrooms_or_hotel_inventory(self):
        for room in ("Двухместный номер", "2 спальни", "2 × Номер Standard"):
            self.assertIsNone(housing_features({"room": room, "rooms_n": 100})["rooms"])
        for room, count in (("Апартаменты c 2 комнатами", 2), ("2-комнатная квартира", 2), ("Трёхкомнатная квартира", 3), ("Студия", 0)):
            self.assertEqual(housing_features({"room": room})["rooms"], count)

    def test_duplex_not_bunk_bed_or_loft_design(self):
        for room in ("Двухъярусная кровать", "Лофт", "Мансарда"):
            self.assertIsNone(housing_features({"room": room})["duplex"])
        self.assertTrue(housing_features({"room": "Студия Дуплекс"})["duplex"])
        self.assertFalse(housing_features({"room": "Одноуровневая студия"})["duplex"])
        self.assertFalse(housing_features({"room": "Не двухуровневые апартаменты"})["duplex"])

    def test_hotel_title_does_not_describe_selected_room(self):
        self.assertIsNone(housing_features({"name": "Апарт-отель Дуплекс с ванной", "room": "Номер Standard"})["duplex"])
        facts = housing_features({"name": "Апартаменты Двухуровневый лофт с ванной", "room": "Апартаменты c 1 комнатой"})
        self.assertTrue(facts["duplex"])
        self.assertTrue(facts["bathtub"])
        self.assertEqual(facts["rooms"], 1)
        self.assertIn("Название жилья:", facts["evidence"]["duplex"])
        self.assertEqual(housing_features({"name": "Двухкомнатная квартира", "room": "Студия"})["rooms"], 0)
