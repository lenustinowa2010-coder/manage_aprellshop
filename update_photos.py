# -*- coding: utf-8 -*-
"""
APRELL — автоподтяжка фото с aprellshop.ru в базу менеджера.

Что делает:
  1. Открывает data.json (лежит рядом со скриптом).
  2. Для каждого цвета, у которого есть ссылка на страницу товара (поле "u"),
     но нет фото (поле "i" пустое), скачивает страницу и забирает первые 5
     кадров галереи.
  3. Сохраняет data.json и пересобирает зашитую копию данных внутри index.html.
     Старые версии кладёт рядом: data.backup.json и index.backup.html.

Как запустить (в Терминале, из папки с data.json и index.html):
    python3 update_photos.py            # добрать только цвета без фото
    python3 update_photos.py --refresh  # перекачать галереи у ВСЕХ цветов
    python3 update_photos.py --limit 8  # брать по 8 кадров вместо 5

После запуска — загрузить оба файла на GitHub как обычно.
Ничего доустанавливать не нужно: скрипт использует только стандартный Python.
"""

import json
import re
import sys
import time
import shutil
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE / "data.json"
INDEX = HERE / "index.html"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15")
SITE = "https://aprellshop.ru"

# Кадры галереи на карточке товара — картинки размера 680x1054
IMG_RE = re.compile(
    r'["\'](?:https://aprellshop\.ru)?(/assets/cache_image/goods/[^"\']+?_680x1054_[a-z0-9]+\.(?:jpg|jpeg|png))["\']',
    re.IGNORECASE,
)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "ru,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def gallery(url: str, limit: int) -> list[str]:
    html = fetch(url)
    seen, out = set(), []
    for m in IMG_RE.finditer(html):
        full = SITE + m.group(1)
        if full not in seen:
            seen.add(full)
            out.append(full)
        if len(out) >= limit:
            break
    return out


def rebuild_index(data: dict) -> bool:
    """Заменяет зашитый JSON (const EMBED = {...};) внутри index.html."""
    if not INDEX.exists():
        return False
    s = INDEX.read_text(encoding="utf-8")
    marker = "const EMBED = "
    start = s.find(marker)
    if start < 0:
        return False
    start += len(marker)
    # конец зашитого JSON — точка с запятой перед строкой "let DATA"
    tail = s.find("let DATA", start)
    end = s.rfind(";", start, tail)
    if tail < 0 or end < 0:
        return False
    s = s[:start] + json.dumps(data, ensure_ascii=False) + s[end:]
    shutil.copy(INDEX, HERE / "index.backup.html")
    INDEX.write_text(s, encoding="utf-8")
    return True


def main() -> None:
    refresh = "--refresh" in sys.argv
    limit = 5
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    data = json.loads(DATA.read_text(encoding="utf-8"))

    todo = []
    for model in data.get("models", []):
        for v in model.get("site", []):
            if v.get("u") and (refresh or not v.get("i")):
                todo.append(v)

    if not todo:
        print("Все цвета уже с фото — делать нечего. "
              "Чтобы перекачать заново, запусти с --refresh.")
        return

    print(f"К обработке: {len(todo)} цветов (по {limit} кадров).")
    ok = fail = 0
    for v in todo:
        label = f"{v.get('a','?')} · {v.get('c','?')}"
        try:
            imgs = gallery(v["u"], limit)
            if imgs:
                v["i"] = imgs
                ok += 1
                print(f"  + {label}: {len(imgs)} фото")
            else:
                fail += 1
                print(f"  ! {label}: галерея не найдена — проверь страницу {v['u']}")
        except Exception as e:
            fail += 1
            print(f"  ! {label}: ошибка ({e})")
        time.sleep(1.5)  # вежливая пауза, чтобы не дёргать сайт

    shutil.copy(DATA, HERE / "data.backup.json")
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\ndata.json сохранён (добавлено: {ok}, с ошибками: {fail}).")

    if rebuild_index(data):
        print("index.html пересобран, старая версия — index.backup.html.")
    else:
        print("index.html не найден или не распознан — обнови только data.json, "
              "сайт подтянет его сам.")


if __name__ == "__main__":
    main()
