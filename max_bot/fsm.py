"""
Минимальная in-memory FSM для MAX-бота.
Telegram aiogram даёт нам такой из коробки, а для MAX мы пишем свой.

Хранит состояние и произвольные данные по ключу (user_id, chat_id).
Ключ — tuple (user_id, chat_id). user_id обычно совпадает с chat_id
в личке, но в групповых чатах (если бы они были) это важно.

Не персистентное — при рестарте MAX-бота незавершённые диалоги сбросятся.
Для продакшена этого достаточно: заказ либо оформлен (и в БД), либо
недооформлен (и его просто нет).
"""

from __future__ import annotations

from typing import Any


class FSMContext:
    """Контекст одного пользователя — состояние + словарь данных."""

    def __init__(self, storage: "FSMStorage", key: tuple[int, int]) -> None:
        self._storage = storage
        self._key = key

    @property
    def state(self) -> str | None:
        return self._storage._states.get(self._key)

    async def set_state(self, state: str | None) -> None:
        if state is None:
            self._storage._states.pop(self._key, None)
        else:
            self._storage._states[self._key] = state

    async def get_data(self) -> dict[str, Any]:
        return dict(self._storage._data.get(self._key, {}))

    async def update_data(self, **kwargs) -> dict[str, Any]:
        cur = self._storage._data.setdefault(self._key, {})
        cur.update(kwargs)
        return dict(cur)

    async def set_data(self, data: dict[str, Any]) -> None:
        self._storage._data[self._key] = dict(data)

    async def clear(self) -> None:
        self._storage._states.pop(self._key, None)
        self._storage._data.pop(self._key, None)


class FSMStorage:
    """Глобальное хранилище всех активных контекстов."""

    def __init__(self) -> None:
        self._states: dict[tuple[int, int], str] = {}
        self._data: dict[tuple[int, int], dict[str, Any]] = {}

    def context(self, user_id: int, chat_id: int | None = None) -> FSMContext:
        return FSMContext(self, (user_id, chat_id or user_id))
