from aiogram.fsm.state import State, StatesGroup


class BookingStates(StatesGroup):
    from_city = State()
    custom_from_address = State()   # ввод произвольного адреса отправления
    to_city = State()
    custom_to_address = State()     # ввод произвольного адреса назначения
    trip_date = State()
    trip_time = State()
    passengers = State()
    has_children = State()
    children_count = State()
    baggage = State()
    need_minivan = State()
    stops = State()
    confirm_summary = State()
    get_name = State()
    get_phone = State()


class PriceStates(StatesGroup):
    from_city = State()
    to_city = State()
    passengers = State()
    has_children = State()
    need_minivan = State()


class ReviewStates(StatesGroup):
    waiting_rating = State()
    waiting_text = State()


class AdminSettingsStates(StatesGroup):
    waiting_new_text = State()
    waiting_new_price = State()
    waiting_new_photo = State()
    waiting_route_from = State()
    waiting_route_to = State()
    waiting_route_price = State()
    waiting_edit_route_price = State()


class ManagerStates(StatesGroup):
    describe = State()
    get_name = State()
    get_phone = State()


class ManagerPriceStates(StatesGroup):
    waiting_price = State()
