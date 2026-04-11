from shared import settings_store


def _sc() -> dict:
    return settings_store.get_surcharges()


def calculate_price(
    from_city: str,
    to_city: str,
    passengers: int,
    has_children: bool,
    children_count: int,
    baggage: str,
    need_minivan: bool,
    stops: str,
    *,
    route_price: int | None = None,
) -> dict:
    """
    route_price -- if given, used as base price (from DB).
    If None, returns needs_manual=True.
    """
    sc = _sc()

    result: dict = {
        "base_price": 0,
        "extra_passenger_fee": 0,
        "minivan_fee": 0,
        "child_fee": 0,
        "baggage_fee": 0,
        "stops_fee": 0,
        "total": 0,
        "needs_manual": False,
        "breakdown": [],
    }

    if route_price is None:
        result["needs_manual"] = True
        return result

    base_price = route_price
    result["base_price"] = base_price
    result["breakdown"].append(f"Базовая цена маршрута: {base_price:,} ₽")

    _apply_surcharges(result, sc, passengers, has_children, children_count,
                      baggage, need_minivan, stops)
    return result


def calculate_price_by_km(
    distance_km: float,
    passengers: int,
    has_children: bool,
    children_count: int,
    baggage: str,
    need_minivan: bool,
    stops: str,
) -> dict:
    sc = _sc()
    per_km = sc["per_km"]

    result: dict = {
        "base_price": 0,
        "extra_passenger_fee": 0,
        "minivan_fee": 0,
        "child_fee": 0,
        "baggage_fee": 0,
        "stops_fee": 0,
        "total": 0,
        "needs_manual": False,
        "breakdown": [],
        "distance_km": distance_km,
    }

    base_price = round(distance_km * per_km)
    result["base_price"] = base_price
    result["breakdown"].append(
        f"Расстояние {distance_km} км × {per_km} ₽/км: {base_price:,} ₽"
    )

    _apply_surcharges(result, sc, passengers, has_children, children_count,
                      baggage, need_minivan, stops)
    return result


def _apply_surcharges(
    result: dict,
    sc: dict,
    passengers: int,
    has_children: bool,
    children_count: int,
    baggage: str,
    need_minivan: bool,
    stops: str,
) -> None:
    base_price = result["base_price"]

    if passengers > 3:
        extra = (passengers - 3) * sc["extra_passenger"]
        result["extra_passenger_fee"] = extra
        result["breakdown"].append(f"Доп. пассажиры (+{passengers - 3} чел.): +{extra:,} ₽")

    if need_minivan:
        result["minivan_fee"] = sc["minivan"]
        result["breakdown"].append(f"Минивэн: +{sc['minivan']:,} ₽")

    if has_children and children_count > 0:
        child_fee = children_count * sc["child_seat"]
        result["child_fee"] = child_fee
        result["breakdown"].append(f"Детские кресла ({children_count} шт.): +{child_fee:,} ₽")

    if baggage == "large":
        result["baggage_fee"] = sc["large_baggage"]
        result["breakdown"].append(f"Крупный багаж: +{sc['large_baggage']:,} ₽")

    stops_fees = {"none": 0, "1-2": sc["stops_1_2"], "3+": sc["stops_3plus"], "custom": 0}
    stops_fee = stops_fees.get(stops, 0)
    if stops_fee > 0:
        result["stops_fee"] = stops_fee
        result["breakdown"].append(f"Остановки по дороге: +{stops_fee:,} ₽")

    if stops == "custom":
        result["needs_manual"] = True

    result["total"] = (
        base_price
        + result["extra_passenger_fee"]
        + result["minivan_fee"]
        + result["child_fee"]
        + result["baggage_fee"]
        + result["stops_fee"]
    )
