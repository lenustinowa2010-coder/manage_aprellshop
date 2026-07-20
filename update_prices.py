# -*- coding: utf-8 -*-
"""
APRELL — автоподтяжка АКТУАЛЬНЫХ ЦЕН с aprellshop.ru в базу менеджера.

Что делает:
  1. Открывает data.json (лежит рядом со скриптом).
  2. Для каждого цвета, у которого есть ссылка на страницу товара (поле "u"),
     заходит на карточку и забирает:
       - price    — текущую цену (₽),
       - oldPrice — старую (зачёркнутую) цену, если на сайте есть скидка.
     Цена пишется в КАЖДЫЙ цвет отдельно (в его объект внутри "site").
  3. Сравнивает с тем, что было в базе, и печатает ОТЧЁТ: что и где изменилось.
     Отчёт также сохраняется в price_report.txt рядом со скриптом.
  4. Сохраняет data.json и пересобирает зашитую копию внутри index.html.
     Старые версии кладёт рядом: data.backup.json / index.backup.html.

Как запустить (в Терминале, из папки с data.json и index.html):
    python3 update_prices.py

Ничего доустанавливать не нужно — только стандартный Python.
Скрипт НЕ трогает фото; для фото есть отдельный update_photos.py.
"""

import json
import re
import time
import shutil
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data.json"
INDEX = HERE / "index.html"
REPORT = HERE / "price_report.txt"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15")

# Актуальная цена — из мета-тега og:price:amount (одно надёжное число).
META_PRICE_RE = re.compile(
    r'og:price:amount["\']\s+content=["\']\s*(\d+)', re.IGNORECASE)
# Запасной вариант, если мета нет: первое число вида "NNNNN ₽/руб" на странице.
ANY_PRICE_RE = re.compile(r'(\d[\d\s\u00a0]{2,})\s*(?:&nbsp;)?\s*(?:₽|руб)', re.IGNORECASE)
# Старая (зачёркнутая) цена — внутри <del>…</del> или <s>…</s>.
# Берём всё содержимое тега и вытаскиваем из него число с ₽/руб.
OLD_PRICE_RE = re.compile(r'<(del|s)\b[^>]*>(.*?)</\1>', re.IGNORECASE | re.DOTALL)


def to_int(raw: str) -> int:
    return int(re.sub(r'[\s\u00a0]', '', raw))


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "ru,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_prices(html: str):
    """Возвращает (price, old_price|None). price=None если ничего не нашли."""
    price = None
    m = META_PRICE_RE.search(html)
    if m:
        price = int(m.group(1))
    else:
        nums = [to_int(x.group(1)) for x in ANY_PRICE_RE.finditer(html)]
        nums = [n for n in nums if n > 0]
        if nums:
            price = min(nums)  # текущая обычно ниже старой

    old = None
    for tag in OLD_PRICE_RE.finditer(html):
        # внутри <del>/<s> берём самое большое число (это и есть старая цена)
        nums = [to_int(x) for x in re.findall(r'\d[\d\s\u00a0]{2,}', tag.group(2))]
        nums = [n for n in nums if n > 0]
        if not nums:
            continue
        val = max(nums)
        if price is None or val > price:
            old = val
            break
    return price, old


def rebuild_index(data: dict) -> bool:
    if not INDEX.exists():
        return False
    s = INDEX.read_text(encoding="utf-8")
    marker = "const EMBED = "
    start = s.find(marker)
    if start < 0:
        return False
    start += len(marker)
    tail = s.find("let DATA", start)
    end = s.rfind(";", start, tail)
    if tail < 0 or end < 0:
        return False
    s = s[:start] + json.dumps(data, ensure_ascii=False) + s[end:]
    shutil.copy(INDEX, HERE / "index.backup.html")
    INDEX.write_text(s, encoding="utf-8")
    return True


def fmt(n):
    return f"{n:,}".replace(",", " ") + " ₽" if n is not None else "—"


def main() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))

    variants = [v for m in data.get("models", []) for v in m.get("site", [])
                if v.get("u")]
    if not variants:
        print("В базе нет цветов со ссылками на страницы товаров.")
        return

    print(f"Проверяю цены: {len(variants)} цветов.\n")
    changes, fails = [], []

    for v in variants:
        label = f"{v.get('a','?')} · {v.get('c','?')}"
        try:
            price, old = parse_prices(fetch(v["u"]))
            if price is None:
                fails.append(f"{label}: цену не нашла — проверь {v['u']}")
                print(f"  ! {label}: цена не распознана")
                time.sleep(1.5)
                continue

            was_p, was_o = v.get("price"), v.get("oldPrice")
            if was_p != price or was_o != (old or None):
                changes.append((label, was_p, was_o, price, old))
                arrow = "" if was_p is None else \
                        (" ↓" if (was_p and price < was_p) else
                         " ↑" if (was_p and price > was_p) else "")
                print(f"  ~ {label}: {fmt(was_p)} → {fmt(price)}"
                      f"{(' (было ' + fmt(was_o) + ')') if was_o else ''}"
                      f"{(' | старая ' + fmt(old)) if old else ''}{arrow}")

            v["price"] = price
            if old:
                v["oldPrice"] = old
            elif "oldPrice" in v:
                del v["oldPrice"]  # скидка закончилась — убираем старую цену
        except Exception as e:
            fails.append(f"{label}: ошибка ({e})")
            print(f"  ! {label}: ошибка ({e})")
        time.sleep(1.5)  # вежливая пауза для сайта

    # ---- отчёт ----
    lines = [f"APRELL — сверка цен, {time.strftime('%Y-%m-%d %H:%M')}", ""]
    if changes:
        lines.append(f"Изменилось: {len(changes)}")
        for label, wp, wo, p, o in changes:
            seg = f"  {label}: {fmt(wp)}"
            if wo:
                seg += f" (старая {fmt(wo)})"
            seg += f"  →  {fmt(p)}"
            if o:
                seg += f" (старая {fmt(o)})"
            lines.append(seg)
    else:
        lines.append("Изменений нет — цены в базе совпадают с сайтом.")
    if fails:
        lines += ["", f"Не удалось прочитать: {len(fails)}"] + \
                 [f"  {x}" for x in fails]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    shutil.copy(DATA, HERE / "data.backup.json")
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"\nОтчёт сохранён: {REPORT.name}")
    print(f"data.json обновлён (изменений: {len(changes)}, ошибок: {len(fails)}).")

    if rebuild_index(data):
        print("index.html пересобран, старая версия — index.backup.html.")
    else:
        print("index.html не распознан — обнови только data.json, сайт подтянет сам.")


if __name__ == "__main__":
    main()
