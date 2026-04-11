"""
Геокодирование и расчёт дорожного расстояния.

Стек (бесплатно, без API-ключей):
  • Nominatim (OpenStreetMap) — текст → координаты
  • OSRM Project   — маршрут по дорогам → расстояние в км
"""

import httpx

_NOMINATIM = "https://nominatim.openstreetmap.org/search"
_OSRM = "http://router.project-osrm.org/route/v1/driving"
_UA = {"User-Agent": "transfer-altai-bot/1.0"}

# ──────────────────────────────────────────────────────────────────────────────


async def geocode_address(address: str) -> dict | None:
    """
    Пытается найти адрес через Nominatim.

    Возвращает dict:
        {"lat": float, "lon": float, "display": str}
    или None, если адрес не найден.

    Делает два попытки: сначала с уточнением «Алтай», потом без него.
    """
    queries = [f"{address}, Алтай", address]

    async with httpx.AsyncClient(timeout=10.0) as client:
        for query in queries:
            params = {
                "q": query,
                "format": "json",
                "limit": 1,
                "countrycodes": "ru",
                "accept-language": "ru",
            }
            try:
                r = await client.get(_NOMINATIM, params=params, headers=_UA)
                data = r.json()
                if data:
                    return {
                        "lat": float(data[0]["lat"]),
                        "lon": float(data[0]["lon"]),
                        "display": _trim_address(data[0]["display_name"]),
                    }
            except Exception:
                continue

    return None


async def get_route_distance_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float | None:
    """
    Вычисляет расстояние по дорогам между двумя точками через OSRM.
    Возвращает км (округлено до 0.1) или None при ошибке сети/маршрута.
    """
    url = f"{_OSRM}/{lon1},{lat1};{lon2},{lat2}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url, params={"overview": "false"}, headers=_UA)
            data = r.json()
        if data.get("code") == "Ok":
            meters = data["routes"][0]["distance"]
            return round(meters / 1000, 1)
    except Exception:
        pass
    return None


def _trim_address(display_name: str, parts: int = 4) -> str:
    """Nominatim возвращает длинные строки — берём только первые N частей."""
    chunks = [p.strip() for p in display_name.split(",")]
    return ", ".join(chunks[:parts])
