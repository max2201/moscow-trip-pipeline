"""Collect dated public offers with a regular browser. Never solves captchas."""
from pathlib import Path
from urllib.parse import urlparse
from .sources import search_url

SUPPORTED = {"ozon", "yandex", "sutochno", "tvil", "tutu", "onetwotrip"}
SCRIPT = (Path(__file__).with_name("collect_cards.js")).read_text(encoding="utf-8")


def crawl(source, stop, max_pages=1000, log=print, coverage=None, checkpoint=None):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="ru-RU", viewport={"width": 1440, "height": 1000})
        context.route("**/*", lambda route: route.abort() if route.request.resource_type in {"image", "media", "font"} else route.continue_())
        page = context.new_page()
        page.goto(search_url(source, stop), wait_until="domcontentloaded", timeout=60000)
        if source == "tvil":
            price = page.get_by_test_id("range-input-max")
            price.wait_for(state="visible", timeout=60000)
            page.wait_for_function("() => !document.querySelector('[data-testid=range-input-max]').readOnly", timeout=60000)
            price.press("Control+A")
            price.press_sequentially(str(40000 // stop["nights"]))
            price.press("Tab")
            page.get_by_role("button", name="Найти", exact=True).click()
        if source == "yandex" and not page.locator('h3[itemprop="name"]').count():
            button = page.get_by_role("button", name="Найти", exact=True)
            if button.count():
                button.click()
        # The initial list can contain only skeleton prices. Nine seconds of
        # empty parser results did not mean there were no hotels.
        try:
            page.wait_for_function(f"arg => ({SCRIPT})(arg).length > 0", arg={"source": source, "stop": stop}, timeout=90000)
        except Exception:
            raise ValueError("За 90 секунд не появились подтверждённые цены; предыдущий снимок сохранён")
        if source == "onetwotrip":
            # URL price parameters alone do not initialise the visible range.
            # The UI is explicitly in whole-stay mode ("8 ночей").
            page.get_by_role("button", name=f'{stop["nights"]} ночей', exact=True).wait_for(state="visible")
            before_ids = [x["externalId"] for x in page.evaluate(SCRIPT, {"source": source, "stop": stop})]
            price_inputs = page.locator('input[inputmode="numeric"]')
            price_inputs.nth(1).press("Control+A")
            price_inputs.nth(1).press_sequentially("40000")
            price_inputs.nth(1).press("Enter")
            price_inputs.nth(1).press("Tab")
            # Sponsored offers can exceed the range. Wait for the refreshed
            # list, then enforce the exact budget per card during export.
            page.wait_for_function(f"arg => {{ const xs = ({SCRIPT})(arg.input); return xs.length > 0 && (xs.some(x => !arg.ids.includes(x.externalId)) || xs.filter(x => x.total <= 40000).length >= Math.ceil(xs.length / 2)); }}",
                                   arg={"input": {"source": source, "stop": stop}, "ids": before_ids}, timeout=30000)
        result = {}
        unchanged = 0
        reason = "limit"
        complete = False
        seen_cards = set()
        stage = "Сбор карточек"
        failure = None
        last_scroll = None
        try:
            for step in range(max_pages * 10 if source == "tutu" else max_pages):
                page.wait_for_timeout(250 if source == "tutu" else 1500)
                scroll = page.evaluate("""() => {
                    let e = document.elementFromPoint(400, 600);
                    while (e) {
                        if (e.scrollHeight > e.clientHeight + 10 && /auto|scroll/.test(getComputedStyle(e).overflowY)) return e.scrollTop;
                        e = e.parentElement;
                    }
                    return document.scrollingElement.scrollTop;
                }""")
                moved = last_scroll is None or scroll != last_scroll
                last_scroll = scroll
                title = page.title().lower()
                if "captcha" in page.url.lower() or "капч" in title or "доступ ограничен" in title:
                    raise ValueError("Площадка требует проверку в браузере; снимок сохранён")
                stage = "Чтение цен"
                batch = page.evaluate(SCRIPT, {"source": source, "stop": stop, "skipIds": list(seen_cards)})
                seen_cards.update(x["externalId"] for x in batch)
                if source == "onetwotrip":
                    confirmed = []
                    for item in batch:
                        if item["total"] > 40000:
                            continue
                        if item["externalId"] in result:
                            confirmed.append(result[item["externalId"]])
                            continue
                        # Off-screen cards omit the Select button. The hotel title
                        # remains available and opens the same verified popup.
                        button = page.locator(f'[data-hotel-id="{item["externalId"]}"]').get_by_text(item["name"], exact=True)
                        stage = "Открытие ссылки OneTwoTrip"
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
                if checkpoint is not None and result and (step == 0 or (step + 1) % 10 == 0):
                    checkpoint(list(result.values()), {"pages": step + 1, "priced": len(seen_cards), "saved": len(result), "complete": False, "reason": "in_progress"})
                if unchanged >= 5 and not (source == "tutu" and moved):
                    # A stable bottom is recorded as partial unless the source
                    # explicitly confirms the end. Never claim all offers merely
                    # because repeated scrolls produced no new priced cards.
                    reason = "stalled"
                    break
                stage = "Переход к следующей странице"
                if source == "onetwotrip":
                    more = page.get_by_role("button", name="Показать 15 отелей", exact=True)
                    if more.count() and more.is_visible() and more.is_enabled():
                        more.click()
                    else:
                        # With an active price range the source shows numbered
                        # pages instead of the load-more button.
                        next_page = page.locator(".tcbxi button.eU-w6").last
                        if next_page.count() and next_page.is_enabled():
                            next_page.click()
                        else:
                            complete = bool(next_page.count())
                            reason = "end" if complete else "stalled"
                            break
                elif source == "tvil":
                    more = page.get_by_role("button", name="Показать еще 20 вариантов")
                    if more.count():
                        more.click()
                    else:
                        reason = "end"
                        complete = True
                        break
                elif source in {"sutochno", "yandex"}:
                    more = page.get_by_text("Далее", exact=True)
                    if more.count() and more.first.is_enabled():
                        more.first.click()
                    elif source == "sutochno" or more.count():
                        reason = "end"
                        complete = True
                        break
                    else:
                        page.mouse.move(600, 600)
                        page.mouse.wheel(0, 7000)
                else:
                    # Aim the wheel at the list, away from the map. The old wheel
                    # could zoom the map while leaving the hotel list unchanged.
                    page.mouse.move(400, 600)
                    # Tutu requests prices only for cards entering the viewport.
                    # Large wheel jumps skipped the intervening properties.
                    page.mouse.wheel(0, 700 if source == "tutu" else 7000)
                # Wait for fresh priced objects instead of checking once immediately
                # after the scroll. Slow price loading must not consume page budget.
                previous_ids = list(seen_cards)
                try:
                    page.wait_for_function(f"arg => ({SCRIPT})(arg.input).length > 0",
                                          arg={"input": {"source": source, "stop": stop, "skipIds": previous_ids}}, timeout=15000)
                except Exception:
                    pass
        except Exception as error:
            failure = str(error) if isinstance(error, ValueError) else stage + ": " + type(error).__name__
            if not result:
                raise ValueError(failure) from error
            reason, complete = "error", False
        context.close()
        browser.close()
        if not result:
            raise ValueError("Нет подтверждённых цен на выбранные даты; возможна проверка доступа или изменение разметки")
        if coverage is not None:
            coverage.update(pages=step + 1, priced=len(seen_cards), saved=len(result), reason=reason, complete=complete)
            if failure:
                coverage["message"] = failure
        return list(result.values())
