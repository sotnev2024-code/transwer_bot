"""
Минимальный диспетчер апдейтов MAX.

Обрабатывает update_type:
  • "message_created"      — входящее сообщение от пользователя
  • "bot_started"          — пользователь запустил бота (аналог /start)
  • "message_callback"     — нажатие на inline-кнопку
  • "user_added"           — пользователь добавился в чат с ботом (тоже /start)

Хендлеры регистрируются через декораторы @dp.message, @dp.callback, @dp.command,
@dp.state_message, @dp.text.

Контекст, передаваемый в хендлер — это Update (обёртка) + FSMContext + MaxClient.
"""

from __future__ import annotations

import logging
import re
from typing import Awaitable, Callable, Any

from max_bot.fsm import FSMContext, FSMStorage
from max_bot.max_client import MaxClient

_log = logging.getLogger(__name__)

# Типы событий
EVENT_MESSAGE = "message_created"
EVENT_START = "bot_started"
EVENT_USER_ADDED = "user_added"
EVENT_CALLBACK = "message_callback"


class Update:
    """Нормализованное представление апдейта MAX."""

    def __init__(self, raw: dict) -> None:
        self.raw = raw
        self.type: str = raw.get("update_type", "")

        # ── сообщение (присутствует у message_created и у message_callback) ──
        msg = raw.get("message", {}) or {}
        self.message = msg
        body = msg.get("body", {}) or {}
        self.text: str = body.get("text", "") or ""
        self.message_id: str | None = body.get("mid")
        self.attachments: list[dict] = body.get("attachments", []) or []

        # ── sender / user ──
        # У сообщения от пользователя sender — это пользователь.
        # У callback-события sender может быть в callback.user или в самом raw.
        # Пробуем несколько источников.
        sender_candidates = [
            raw.get("callback", {}).get("user") if isinstance(raw.get("callback"), dict) else None,
            msg.get("sender"),
            raw.get("user"),
        ]
        sender = next((s for s in sender_candidates if isinstance(s, dict) and s), {})

        self.user_id: int = int(sender.get("user_id") or sender.get("id") or 0)
        self.username: str | None = sender.get("username")
        self.first_name: str | None = sender.get("first_name") or sender.get("name")
        self.last_name: str | None = sender.get("last_name")

        # ── chat_id ──
        recipient = msg.get("recipient") or {}
        # Для callback может быть chat_id прямо в raw, а recipient — это сам бот
        chat_id_candidates = [
            recipient.get("chat_id"),
            raw.get("chat_id"),
            raw.get("callback", {}).get("chat_id") if isinstance(raw.get("callback"), dict) else None,
            self.user_id,
        ]
        self.chat_id: int = int(next((c for c in chat_id_candidates if c), 0))

        # ── callback ──
        cb = raw.get("callback") or {}
        self.callback_id: str | None = cb.get("callback_id") or cb.get("id")
        self.callback_payload: str = cb.get("payload") or cb.get("data") or ""

        # ── contact (request_contact button result) ──
        # Формат MAX:
        #   attachments: [{ "type": "contact", "payload": {
        #       "vcf_info": "BEGIN:VCARD\nVERSION:3.0\nTEL;TYPE=cell:79991234567\nFN:Имя\nEND:VCARD",
        #       "max_info": { "user_id": ..., "first_name": ..., ... }
        #   }}]
        # Телефон лежит ВНУТРИ vCard-строки, его нужно вытащить regex-ом.
        self.contact_phone: str | None = None
        for att in self.attachments:
            if att.get("type") != "contact":
                continue
            payload = att.get("payload") or {}
            # Сначала пробуем «прямые» поля (на случай если когда-то добавят)
            phone = payload.get("phone") or payload.get("vcf_phone")
            if not phone:
                vcf = payload.get("vcf_info") or ""
                m = re.search(r"TEL[^:]*:(\+?[\d\s\-]+)", vcf)
                if m:
                    phone = m.group(1).strip()
            self.contact_phone = phone
            break


Handler = Callable[["MaxContext"], Awaitable[None]]


class MaxContext:
    """Всё, что нужно хендлеру для ответа пользователю."""

    def __init__(
        self,
        update: Update,
        client: MaxClient,
        state: FSMContext,
    ) -> None:
        self.update = update
        self.client = client
        self.state = state

    # ── удобные свойства ──
    @property
    def user_id(self) -> int:
        return self.update.user_id

    @property
    def chat_id(self) -> int:
        return self.update.chat_id

    @property
    def text(self) -> str:
        return self.update.text

    @property
    def payload(self) -> str:
        return self.update.callback_payload

    # ── отправка / редактирование / удаление ──

    async def send(self, text: str, kb: dict | None = None, fmt: str | None = "html") -> dict:
        """
        Отправить новое сообщение. По умолчанию формат HTML — для поддержки
        тегов <b>, <i>, <u>, <a href> в текстах (как в Telegram-боте).

        Автоматически запоминает mid в FSM state как `_last_bot_mid`, чтобы
        потом редактировать из text-хендлеров.
        """
        atts = [kb] if kb else None
        resp = await self.client.send_message(self.chat_id, text, attachments=atts, fmt=fmt)
        mid = MaxClient.extract_mid(resp)
        if mid:
            await self.state.update_data(_last_bot_mid=mid)
        return resp

    async def edit(self, text: str, kb: dict | None = None, fmt: str | None = "html") -> dict:
        """
        Редактирует сообщение.
          1. Если это callback — редактируем сообщение с кнопкой (update.message_id)
          2. Иначе — редактируем последнее отправленное ботом (из FSM state)
          3. Если и это недоступно — fallback на send()
        Формат по умолчанию — HTML.
        """
        atts = [kb] if kb else None

        target_mid: str | None = None
        if self.update.type == EVENT_CALLBACK and self.update.message_id:
            target_mid = self.update.message_id
        else:
            data = await self.state.get_data()
            target_mid = data.get("_last_bot_mid")

        if not target_mid:
            return await self.send(text, kb, fmt=fmt)

        try:
            resp = await self.client.edit_message(target_mid, text, attachments=atts, fmt=fmt)
            await self.state.update_data(_last_bot_mid=target_mid)
            return resp
        except Exception as e:
            _log.warning(f"edit_message failed, falling back to send: {e}")
            return await self.send(text, kb, fmt=fmt)

    async def delete_prev(self) -> None:
        """Удаляет сообщение, к которому прикреплён callback (если возможно)."""
        mid = self.update.message_id
        if not mid:
            return
        try:
            await self.client.delete_message(mid)
        except Exception:
            pass

    async def answer_callback(self, notification: str | None = None) -> None:
        if self.update.callback_id:
            try:
                await self.client.answer_callback(
                    self.update.callback_id, notification=notification
                )
            except Exception as e:
                _log.warning(f"answer_callback failed: {e}")


class Dispatcher:
    """Роутинг апдейтов на пользовательские хендлеры."""

    def __init__(self, client: MaxClient, storage: FSMStorage) -> None:
        self.client = client
        self.storage = storage

        # Список (matcher, handler). Matcher возвращает True, если подходит.
        self._routes: list[tuple[Callable[[Update, str | None], bool], Handler]] = []
        self._start_handler: Handler | None = None

    # ─────────── регистрация ───────────

    def start(self) -> Callable[[Handler], Handler]:
        """Декоратор для обработчика /start (событие bot_started или user_added)."""
        def decorator(fn: Handler) -> Handler:
            self._start_handler = fn
            return fn
        return decorator

    def callback(
        self,
        prefix: str,
        *,
        state: str | None = None,
    ) -> Callable[[Handler], Handler]:
        """Обработчик callback-кнопки по префиксу payload."""
        def decorator(fn: Handler) -> Handler:
            def match(upd: Update, st: str | None) -> bool:
                if upd.type != EVENT_CALLBACK:
                    return False
                if not upd.callback_payload.startswith(prefix):
                    return False
                if state is not None and st != state:
                    return False
                return True
            self._routes.append((match, fn))
            return fn
        return decorator

    def command(self, cmd: str) -> Callable[[Handler], Handler]:
        """Обработчик текстовой команды /cmd."""
        target = cmd if cmd.startswith("/") else f"/{cmd}"
        def decorator(fn: Handler) -> Handler:
            def match(upd: Update, st: str | None) -> bool:
                if upd.type != EVENT_MESSAGE:
                    return False
                return upd.text.strip().split()[0:1] == [target]
            self._routes.append((match, fn))
            return fn
        return decorator

    def state_message(self, state: str) -> Callable[[Handler], Handler]:
        """Обработчик текстового сообщения в определённом FSM-состоянии."""
        def decorator(fn: Handler) -> Handler:
            def match(upd: Update, st: str | None) -> bool:
                return upd.type == EVENT_MESSAGE and st == state
            self._routes.append((match, fn))
            return fn
        return decorator

    def message(self) -> Callable[[Handler], Handler]:
        """Общий обработчик любого сообщения (fallback, последний в цепочке)."""
        def decorator(fn: Handler) -> Handler:
            def match(upd: Update, st: str | None) -> bool:
                return upd.type == EVENT_MESSAGE
            self._routes.append((match, fn))
            return fn
        return decorator

    # ─────────── обработка одного апдейта ───────────

    async def process(self, upd: Update) -> None:
        if not upd.user_id:
            return

        ctx_state = self.storage.context(upd.user_id, upd.chat_id)
        current_state = ctx_state.state

        # 1) Событие старта
        if upd.type in (EVENT_START, EVENT_USER_ADDED):
            if self._start_handler:
                ctx = MaxContext(upd, self.client, ctx_state)
                await self._start_handler(ctx)
            return

        # 2) Пройтись по роутам
        for matcher, handler in self._routes:
            try:
                if matcher(upd, current_state):
                    ctx = MaxContext(upd, self.client, ctx_state)
                    await handler(ctx)
                    return
            except Exception:
                _log.exception("handler failed")
                return
