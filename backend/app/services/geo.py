"""Координаты строек для карты на главной странице.

Порядок источников:
1. Геокодер Яндекса — если задан ``YANDEX_GEOCODER_KEY`` (точнее всего для московских адресов);
2. Nominatim (OpenStreetMap) — без ключа, не чаще 1 запроса в секунду по правилам сервиса;
3. встроенный справочник округов и крупных магистралей Москвы — работает без интернета,
   точка приблизительная (``geo_source = "approx"``), интерфейс так её и подписывает.

Если адрес не распознан, координат нет: пользователь ставит точку на карте вручную
(``PATCH /projects/{id}`` с ``lat``/``lon``, ``geo_source = "manual"``).
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request

from .common import AppContext, ServiceError, require_project

log = logging.getLogger("stroykontrol.geo")

MOSCOW_CENTER = (55.7558, 37.6173)
USER_AGENT = "StroyKontrol/1.0 (hackathon demo; construction monitoring)"

# Приблизительные точки: центры административных округов и характерные участки магистралей.
# Проверяются по порядку — более конкретные ключи раньше общих.
GAZETTEER: list[tuple[tuple[str, ...], tuple[float, float]]] = [
    (("дмитровское",), (55.8710, 37.5480)),
    (("алтуфьевское",), (55.8800, 37.5870)),
    (("ярославское",), (55.8600, 37.6950)),
    (("щёлковское", "щелковское"), (55.8100, 37.8000)),
    (("волоколамское",), (55.8200, 37.4400)),
    (("ленинградское", "ленинградский пр"), (55.8300, 37.4900)),
    (("варшавское",), (55.6200, 37.6200)),
    (("каширское",), (55.6400, 37.7000)),
    (("рязанский",), (55.7200, 37.7800)),
    (("кутузовский",), (55.7400, 37.5300)),
    (("ленинский пр",), (55.6900, 37.5500)),
    (("мичуринский",), (55.6900, 37.4900)),
    (("профсоюзная",), (55.6500, 37.5300)),
    (("хорошёвское", "хорошевское"), (55.7770, 37.5200)),
    (("зеленоград",), (55.9870, 37.1946)),
    (("новомосковский", "коммунарка"), (55.5588, 37.3710)),
    (("троицк",), (55.4839, 37.3055)),
    (("цао", "центральный административный"), (55.7539, 37.6208)),
    (("свао", "северо-восточный"), (55.8637, 37.6334)),
    (("сзао", "северо-западный"), (55.8298, 37.4500)),
    (("ювао", "юго-восточный"), (55.6926, 37.7545)),
    (("юзао", "юго-западный"), (55.6536, 37.5498)),
    (("сао", "северный административный"), (55.8385, 37.5256)),
    (("вао", "восточный административный"), (55.7876, 37.7757)),
    (("юао", "южный административный"), (55.6100, 37.6816)),
    (("зао", "западный административный"), (55.7066, 37.4531)),
]

_nominatim_lock = threading.Lock()
_nominatim_last = 0.0
_cache: dict[str, tuple[float, float, str]] = {}


def _query(address: str) -> str:
    text = " ".join((address or "").split())
    return text if "москв" in text.lower() else f"Москва, {text}"


def _http_json(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ru"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310 — адрес формируется из констант
        return json.loads(resp.read().decode("utf-8"))


def _yandex(query: str, key: str, timeout: float) -> tuple[float, float] | None:
    url = "https://geocode-maps.yandex.ru/1.x/?" + urllib.parse.urlencode(
        {"apikey": key, "geocode": query, "format": "json", "results": 1, "lang": "ru_RU"})
    data = _http_json(url, timeout)
    members = data["response"]["GeoObjectCollection"]["featureMember"]
    if not members:
        return None
    lon, lat = map(float, members[0]["GeoObject"]["Point"]["pos"].split())
    return lat, lon


def _nominatim(query: str, base_url: str, timeout: float) -> tuple[float, float] | None:
    global _nominatim_last
    url = base_url.rstrip("/") + "/search?" + urllib.parse.urlencode({
        "q": query, "format": "jsonv2", "limit": 1, "countrycodes": "ru",
        "viewbox": "36.80,56.10,38.20,55.10", "bounded": 0,
    })
    with _nominatim_lock:                      # правило сервиса: не чаще 1 запроса в секунду
        wait = 1.1 - (time.monotonic() - _nominatim_last)
        if wait > 0:
            time.sleep(wait)
        try:
            data = _http_json(url, timeout)
        finally:
            _nominatim_last = time.monotonic()
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"])


def approximate(address: str) -> tuple[float, float] | None:
    text = f" {(address or '').lower().replace(',', ' ').replace('.', ' ')} "
    for keys, point in GAZETTEER:
        for k in keys:
            # короткие аббревиатуры округов ищем как отдельные слова, чтобы «сао» не нашлось внутри слова
            if (len(k) <= 4 and f" {k} " in text) or (len(k) > 4 and k in text):
                return point
    return None


def geocode(settings, address: str) -> tuple[float, float, str] | None:
    """(lat, lon, источник) или None. Сетевые ошибки не пробрасываются — идём к следующему источнику."""
    address = (address or "").strip()
    if not address:
        return None
    if address in _cache:          # кешируются только точные ответы геокодеров
        return _cache[address]
    query = _query(address)
    mode = getattr(settings, "geocoder", "auto")
    timeout = float(getattr(settings, "geocoder_timeout", 4))
    result = None
    if mode != "off":
        key = getattr(settings, "yandex_geocoder_key", "")
        if key and mode in ("auto", "yandex"):
            try:
                point = _yandex(query, key, timeout)
                result = (*point, "yandex") if point else None
            except Exception as exc:   # сеть, ключ, формат ответа
                log.warning("Геокодер Яндекса недоступен: %s", exc)
        if result is None and mode in ("auto", "nominatim"):
            try:
                point = _nominatim(query, getattr(settings, "nominatim_url", "https://nominatim.openstreetmap.org"),
                                   timeout)
                result = (*point, "nominatim") if point else None
            except Exception as exc:
                log.warning("Nominatim недоступен: %s", exc)
    if result is None:
        point = approximate(address)
        result = (*point, "approx") if point else None
    if result and result[2] in ("yandex", "nominatim"):
        _cache[address] = result
    return result


def check_point(lat, lon) -> tuple[float, float]:
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise ServiceError(422, "Некорректные координаты")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ServiceError(422, "Координаты вне допустимого диапазона")
    return round(lat, 6), round(lon, 6)


def geocode_project(ctx: AppContext, user_id: int, project_id: int, force: bool = False) -> dict:
    """Определяет координаты стройки по адресу и сохраняет их. Ручную точку без ``force`` не трогает."""
    project = require_project(ctx, user_id, project_id)
    if project.get("lat") is not None and not force:
        return {"id": project_id, "lat": project["lat"], "lon": project["lon"],
                "geo_source": project["geo_source"], "found": True}
    found = geocode(ctx.settings, project["address"])
    if not found:
        return {"id": project_id, "lat": None, "lon": None, "geo_source": None, "found": False}
    lat, lon, source = found
    ctx.db.execute("UPDATE projects SET lat = ?, lon = ?, geo_source = ? WHERE id = ?", (lat, lon, source, project_id))
    return {"id": project_id, "lat": lat, "lon": lon, "geo_source": source, "found": True}
