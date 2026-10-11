"""Collect dated public offers with a regular browser. Never solves captchas."""
from pathlib import Path
from urllib.parse import urlparse
from .sources import search_url

SUPPORTED = {"ozon", "yandex", "sutochno", "tvil", "tutu", "onetwotrip"}
SCRIPT = (Path(__file__).with_name("collect_cards.js")).read_text(encoding="utf-8")


def crawl(source, stop, max_pages=20, log=print):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="ru-RU", viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.goto(search_url(source, stop), wait_until="domcontentloaded", timeout=60000)
        if source == "yandex":
            button = page.get_by_role("button", name="Найти", exact=True)
            button.wait_for(timeout=20000)
            button.click()
        result = {}
        unchanged = 0
        for step in range(max_pages):
            page.wait_for_timeout(3000)
            title = page.title().lower()
            if "captcha" in page.url.lower() or "капч" in title or "доступ ограничен" in title:
                raise ValueError("Площадка требует проверку в браузере; снимок сохранён")
            batch = page.evaluate(SCRIPT, {"source": source, "stop": stop})
            if source == "onetwotrip":
                confirmed = []
                for item in batch:
                    if item["total"] > 40000 or (item.get("km") is not None and item["km"] > 12):
                        continue
                    if item["externalId"] in result:
                        confirmed.append(result[item["externalId"]])
                        continue
                    button = page.locator(f'[data-hotel-id="{item["externalId"]}"]').get_by_role("button", name="Выбрать", exact=True)
                    with page.expect_popup() as popup_info:
                        button.click()
                    popup = popup_info.value
                    popup.wait_for_load_state("domcontentloaded")
                    item["url"] = popup.url
                    popup.close()
                    if not urlparse(item["url"]).path.rstrip("/").endswith("-" + item["externalId"]):
                        raise ValueError("OneTwoTrip: ссылка не совпала с идентификатором объекта")
                    confirmed.append(item)
                batch = confirmed
            previous = len(result)
            result.update({x["externalId"]: x for x in batch})
            unchanged = unchanged + 1 if previous == len(result) else 0
            log(f"{source}: {len(result)} предложений")
            if unchanged >= 3:
                break
            if source == "onetwotrip":
                more = page.get_by_role("button", name="Показать 15 отелей", exact=True)
                if more.count():
                    more.click()
                else:
                    break
            elif source == "tvil":
                more = page.get_by_role("button", name="Показать еще 20 вариантов")
                if more.count():
                    more.click()
                else:
                    break
            elif source == "sutochno":
                more = page.get_by_text("Далее", exact=True)
                if more.count():
                    more.first.click()
                else:
                    break
            else:
                page.mouse.wheel(0, 7000)
        context.close()
        browser.close()
        if not result:
            raise ValueError("Нет подтверждённых цен на выбранные даты; возможна проверка доступа или изменение разметки")
        return list(result.values())
