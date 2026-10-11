"""Features of the priced room/listing, never the hotel's room inventory."""
import re


def housing_features(item):
    facts = {"bathtub": None, "rooms": None, "duplex": None, "evidence": {}}
    room = item.get("room") or ""
    name = item.get("name") or ""
    # A listing title can describe an entire apartment. A hotel title cannot
    # establish that its cheapest room has the same facilities/layout.
    apartment = bool(re.search(r"квартир|апартамент|студи", name, re.I)) and not re.search(r"апарт[- ]?отел|гостиниц|\bотел", name, re.I)
    texts = [("Название номера", room)] + ([("Название жилья", name)] if apartment else [])
    for origin, text in texts:
        if not text:
            continue
        t = text.lower().replace("ё", "е")
        def put(key, value):
            if facts[key] is None:
                facts[key] = value
                facts["evidence"][key] = f"{origin}: {text}"
        # 'Ванная комната' is a bathroom, not confirmation of a bathtub.
        bath = re.sub(r"\bванн(?:ая|ой|ую|ые|ых|ыми)\s+комнат\w*", "", t)
        if re.search(r"без ванны|ванны нет|нет ванны|ванна отсутствует|не ванна|только душ|душ вместо ванны|shower only|no bathtub", bath):
            put("bathtub", False)
        elif not re.search(r"(?:без|нет|не)\s+(?:джакузи|bathtub)", bath) and re.search(r"\bванна\b|\bс ванн(?:ой|ою)\b|\bджакузи\b|\bbathtub\b", bath):
            put("bathtub", True)
        if re.search(r"одноуровнев|один уровень|1[- ]уровнев|single[- ]level|не двухуровнев|без второго уровня", t):
            put("duplex", False)
        elif re.search(r"двух(?:уровнев|этажн)|2[- ]?(?:уровнев|этажн)|дуплекс|\bduplex\b|two[- ]level|split[- ]level", t):
            put("duplex", True)
        match = re.search(r"(?<!\d)([1-9])\s*[- ]?\s*комнат\w*", t)
        if match:
            put("rooms", int(match[1]))
        else:
            for word, count in (("однокомнат", 1), ("двухкомнат", 2), ("трехкомнат", 3), ("четырехкомнат", 4), ("пятикомнат", 5)):
                if word in t:
                    put("rooms", count)
                    break
            if facts["rooms"] is None and re.search(r"\bстуди\w*|\bstudio\b", t):
                put("rooms", 0)
    return facts
