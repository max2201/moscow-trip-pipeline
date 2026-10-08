# Москва, 14–22 октября — сбор данных

Данные для сайта https://max2201.github.io/moscow-trip-vue/ : жильё с Островка (ostrovok.ru) на даты поездки, отзывы гостей и их разбор.

- `python run.py prices` — выдача Островка на даты поездки (до 8 000 ₽ за ночь, не дальше 12 км от Красной площади);
- `python run.py reviews` — отзывы новых отелей (анализ сохраняется в `cache/hotels/msk.jsonl`, сами тексты — нет);
- `python run.py build` — сборка `site-data/` для сайта;
- `python run.py all` — всё по очереди. Каждое утро это делает GitHub Actions (`.github/workflows/update.yml`).

Содержимое (районы, места, события) — в `content/`. Это копия сборщика поездки в Таиланд (thailand-trip-pipeline), переделанная под Островок.
