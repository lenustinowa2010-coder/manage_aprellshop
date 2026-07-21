# -*- coding: utf-8 -*-
"""
APRELL — превращает названия средств Collonil в блоке «Материалы и уход»
в кликабельные ссылки на страницы средств на aprellshop.ru.

Что делает:
  1. Обходит раздел ухода на сайте (/catalog/uxod-za-kozhej/…), собирает пары
     «название средства → ссылка на его страницу».
  2. В каждом материале базы (массив mats, поле Collonil — 5-й элемент строки)
     находит названия средств и оборачивает их в ссылки: media-независимо,
     прямо в тексте. Служебные слова «салфетки», «щётка/щётки» остаются текстом.
  3. Пишет результат в data.json и пересобирает index.html (рендер вкладки
     «Материалы и уход» уже понимает ссылки — они пишутся готовым <a> тегом).
  4. Отчёт collonil_report.txt: что связалось, что не нашлось на сайте.

Запуск (из папки с data.json и index.html):
    python3 link_collonil.py

Только стандартный Python. Сайт открывается с твоего Mac (из песочницы ассистента
он недоступен — поэтому скрипт локальный).
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
REPORT = HERE / "collonil_report.txt"

SITE = "https://aprellshop.ru"
CARE_ROOT = SITE + "/catalog/uxod-za-kozhej/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15")

# Известные ссылки-подсказки (из ручной проверки) — на случай, если обход
# что-то не поймает. Скрипт дополнит их найденным на сайте.
SEED = {
    "nilfett": "/catalog/uxod-za-kozhej/sredstvo-po-uxodu/nilfett",
    "waterstop spray": "/catalog/uxod-za-kozhej/sredstvo-po-uxodu/waterstop-spray-400",
    "carbon pro": "/catalog/uxod-za-kozhej/sredstvo-po-uxodu/carbon-pro",
    "leather gel": "/catalog/uxod-za-kozhej/sredstvo-po-uxodu/leather-gel",
    "clean & care": "/catalog/uxod-za-kozhej/sredstvo-po-uxodu/clean-and-care",
    "clean and care": "/catalog/uxod-za-kozhej/sredstvo-po-uxodu/clean-and-care",
}

# Названия средств, которые встречаются в тексте (для поиска в строке Collonil).
# Ключ — как ищем в тексте (низкий регистр), важно от длинных к коротким.
PRODUCT_NAMES = [
    "waterstop spray", "carbon pro", "clean & care", "clean and care",
    "lack polish", "leather gel", "nilfett", "poliertuch", "wet wipes",
    "auftragsbürste", "glanzbürste", "velours boy",
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "ru,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def norm(s):
    return re.sub(r"[^0-9a-zа-яё&]", "", (s or "").lower().replace("ё", "е"))


def crawl_care_catalog():
    """Собираем со страниц раздела ухода пары (нормализованное название → url).
    Идём по листингу и вытаскиваем ссылки на карточки товаров + их заголовки."""
    found = {}
    to_visit = [CARE_ROOT, CARE_ROOT + "sredstvo-po-uxodu/"]
    seen_pages = set()
    # ссылки на карточки: <a href="/catalog/uxod-za-kozhej/...">Название</a>
    link_re = re.compile(
        r'href=["\'](/catalog/uxod-za-kozhej/[^"\'?#]+)["\'][^>]*>\s*([^<]{2,80}?)\s*<',
        re.IGNORECASE)
    for page in to_visit:
        if page in seen_pages:
            continue
        seen_pages.add(page)
        try:
            html = fetch(page)
        except Exception:
            continue
        for m in link_re.finditer(html):
            url, title = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
            n = norm(title)
            if n and url.rstrip("/") != CARE_ROOT.rstrip("/").replace(SITE, ""):
                found.setdefault(n, SITE + url)
        time.sleep(1.0)
    return found


def build_link_map(crawled):
    """Строим карту: нормализованное название средства → полный url."""
    link = {}
    for name, path in SEED.items():
        link[norm(name)] = SITE + path
    # добавляем/уточняем найденным на сайте
    for n, url in crawled.items():
        link.setdefault(n, url)
    return link


def strip_links(text):
    """Возвращаем текст к чистому виду: убираем ранее вставленные <a>…</a>
    и чиним «выехавшие» из битого прогона хвосты тегов."""
    if not text:
        return text
    # нормальные ссылки: <a ...>Название</a> → Название
    text = re.sub(r'<a\b[^>]*>(.*?)</a>', r'\1', text, flags=re.IGNORECASE | re.DOTALL)
    # битые хвосты от прошлого бага: '" target="_blank" rel="noopener">' → убрать
    text = re.sub(r'"\s*target="_blank"\s*rel="noopener"\s*>', '', text)
    # осиротевшие открывающие/закрывающие теги
    text = re.sub(r'<a\b[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</a>', '', text, flags=re.IGNORECASE)
    # артефакт прошлого бага: 'nilfettNilfett' → 'Nilfett' (одно и то же слово
    # разного регистра слиплось). Схлопываем повтор названия, оставляя вариант
    # с заглавной, как в оригинале.
    for name in PRODUCT_NAMES:
        dup = re.compile(re.escape(name) + re.escape(name), re.IGNORECASE)
        text = dup.sub(lambda m, n=name: n[:1].upper() + n[1:], text)
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text


def linkify(text, link_map, missing):
    """Оборачиваем названия средств в тексте в <a>…</a> за ОДИН проход.
    Каждый участок текста обрабатывается один раз — внутрь уже вставленных
    ссылок замена не заходит (иначе теги рвутся). Дубли-названия (nilfett /
    Nilfett) не задваиваются."""
    if not text or text.strip() == "—":
        return text

    # 1) собираем все совпадения названий в тексте (регистронезависимо),
    #    от длинных к коротким, отбрасывая пересекающиеся интервалы.
    spans = []  # (start, end, name)
    taken = [False] * (len(text) + 1)
    for name in sorted(PRODUCT_NAMES, key=len, reverse=True):
        for m in re.finditer(re.escape(name), text, re.IGNORECASE):
            s, e = m.start(), m.end()
            if any(taken[s:e]):
                continue
            spans.append((s, e, name))
            for i in range(s, e):
                taken[i] = True

    if not spans:
        return text

    # 2) собираем строку заново, вставляя ссылки только на «свободных» участках
    spans.sort()
    out = []
    pos = 0
    for s, e, name in spans:
        out.append(text[pos:s])
        frag = text[s:e]
        url = link_map.get(norm(name))
        if url:
            out.append(f'<a href="{url}" target="_blank" rel="noopener">{frag}</a>')
        else:
            missing.add(name)
            out.append(frag)
        pos = e
    out.append(text[pos:])
    return "".join(out)


def rebuild_index(data):
    if not INDEX.exists():
        return False
    s = INDEX.read_text(encoding="utf-8")
    mk = "const EMBED = "
    st = s.find(mk)
    if st < 0:
        return False
    st += len(mk)
    tail = s.find("let DATA", st)
    en = s.rfind(";", st, tail)
    if tail < 0 or en < 0:
        return False
    s = s[:st] + json.dumps(data, ensure_ascii=False) + s[en:]
    shutil.copy(INDEX, HERE / "index.backup.html")
    INDEX.write_text(s, encoding="utf-8")
    return True


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    mats = data.get("mats", [])
    if not mats:
        print("В базе нет массива mats (материалы и уход) — нечего связывать.")
        return

    print("Собираю ссылки на средства с сайта…")
    crawled = crawl_care_catalog()
    link_map = build_link_map(crawled)
    print(f"Найдено средств на сайте: {len(crawled)}; "
          f"итоговая карта ссылок: {len(link_map)}.")

    missing = set()
    changed = 0
    for row in mats:
        if len(row) >= 5 and isinstance(row[4], str):
            clean = strip_links(row[4])          # сначала откат к чистому тексту
            new = linkify(clean, link_map, missing)
            if new != row[4]:
                row[4] = new
                changed += 1

    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.copy(DATA, HERE / "data.backup.json")

    lines = ["APRELL — ссылки на средства Collonil", ""]
    lines.append(f"Обработано карточек материалов: {changed}.")
    lines.append("")
    lines.append("Карта ссылок:")
    for n in sorted(PRODUCT_NAMES, key=len, reverse=True):
        url = link_map.get(norm(n))
        lines.append(f"  {n:20} → {url or '— НЕ НАЙДЕНО на сайте'}")
    if missing:
        lines += ["", "⚠ Не нашли ссылку (осталось текстом):"] + \
                 [f"  {m}" for m in sorted(missing)]
        lines += ["", "Для них: открой раздел ухода на сайте, найди страницу, "
                      "и впиши ссылку в SEED в начале скрипта — при следующем "
                      "прогоне подхватится."]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nОтчёт: {REPORT.name}")

    if rebuild_index(data):
        print("index.html пересобран (бэкап — index.backup.html).")
    else:
        print("index.html не распознан — обнови только data.json.")


if __name__ == "__main__":
    main()
