"""
Тонкая обёртка над REST API MAX messenger.

Base URL: https://platform-api.max.ru
Auth:     заголовок `Authorization: <token>`
Docs:     https://dev.max.ru/docs-api

Покрывает минимальный набор для нашего бота:
  • long polling /updates
  • отправка и редактирование текстовых сообщений
  • inline-клавиатуры (callback/request_contact/link)
  • ответы на нажатия кнопок (/answers)
  • загрузка фото и отправка вложений
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

import httpx

_log = logging.getLogger(__name__)

_BASE_URL = "https://platform-api.max.ru"
_DEFAULT_TIMEOUT = 35.0   # long polling живёт до 30 сек + запас
_POLL_TIMEOUT = 30        # таймаут long-polling на стороне сервера (сек)


class MaxApiError(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"MAX API error {status}: {body[:200]}")


class MaxClient:
    """Асинхронный клиент платформы MAX."""

    def __init__(self, token: str, base_url: str = _BASE_URL) -> None:
        if not token:
            raise ValueError("MAX token is empty")
        self._token = token
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT,
            headers={"Authorization": token},
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ─────────────────── базовый request ───────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
    ) -> dict:
        url = f"{self._base}{path}"
        try:
            r = await self._client.request(method, url, params=params, json=json)
        except httpx.RequestError as e:
            raise MaxApiError(0, f"network: {e}")

        if r.status_code >= 400:
            raise MaxApiError(r.status_code, r.text)

        if r.status_code == 204 or not r.content:
            return {}
        try:
            return r.json()
        except ValueError:
            return {}

    # ─────────────────── bot info ───────────────────

    async def get_me(self) -> dict:
        return await self._request("GET", "/me")

    async def set_commands(self, commands: list[dict]) -> dict:
        """
        Регистрирует список команд бота, чтобы они появлялись в меню команд
        у пользователя (эквивалент Telegram setMyCommands).

        Формат элемента: {"name": "start", "description": "Запустить бота"}

        Под капотом — PATCH /me с полем commands.
        """
        return await self._request("PATCH", "/me", json={"commands": commands})

    # ─────────────────── updates / long polling ───────────────────

    async def get_updates(self, marker: int | None = None, timeout: int = _POLL_TIMEOUT) -> dict:
        """
        Одиночный long-polling запрос за обновлениями.
        Возвращает {"updates": [...], "marker": int} (формат приблизительный,
        подстроится на практике; если marker отсутствует — берём максимальный
        update_time из updates).
        """
        params: dict[str, Any] = {"timeout": timeout, "limit": 100}
        if marker is not None:
            params["marker"] = marker
        return await self._request("GET", "/updates", params=params)

    async def poll_updates(self) -> AsyncIterator[dict]:
        """
        Бесконечный генератор апдейтов. Автоматически хранит marker,
        восстанавливается после сетевых ошибок с бэкоффом.
        """
        marker: int | None = None
        backoff = 1.0
        while True:
            try:
                data = await self.get_updates(marker=marker)
                updates = data.get("updates") or []
                new_marker = data.get("marker")
                if new_marker is not None:
                    marker = new_marker
                for upd in updates:
                    yield upd
                backoff = 1.0
            except MaxApiError as e:
                _log.warning("MAX /updates error: %s", e)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
            except Exception:
                _log.exception("Unexpected error in poll_updates")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    # ─────────────────── сообщения ───────────────────

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        attachments: list[dict] | None = None,
        reply_to_message_id: str | None = None,
        notify: bool = True,
        fmt: str | None = None,  # "markdown" | "html" | None
    ) -> dict:
        params = {"chat_id": chat_id}
        if not notify:
            params["disable_notification"] = "true"
        body: dict[str, Any] = {"text": text}
        if attachments:
            body["attachments"] = attachments
        if reply_to_message_id:
            body["link"] = {"type": "reply", "mid": reply_to_message_id}
        if fmt:
            body["format"] = fmt
        return await self._request("POST", "/messages", params=params, json=body)

    async def edit_message(
        self,
        message_id: str,
        text: str,
        *,
        attachments: list[dict] | None = None,
        fmt: str | None = None,
    ) -> dict:
        params = {"message_id": message_id}
        body: dict[str, Any] = {"text": text}
        if attachments:
            body["attachments"] = attachments
        if fmt:
            body["format"] = fmt
        return await self._request("PUT", "/messages", params=params, json=body)

    async def delete_message(self, message_id: str) -> dict:
        return await self._request("DELETE", "/messages", params={"message_id": message_id})

    @staticmethod
    def extract_mid(send_response: dict) -> str | None:
        """
        Достаёт message id из ответа send_message / edit_message.
        Формат ответа MAX:
            {"message": {"body": {"mid": "mid.xxx"}, ...}, ...}
        Edit возвращает {"success": true} — в этом случае mid не вытащишь,
        и нужно использовать тот, что мы сами знаем.
        """
        if not isinstance(send_response, dict):
            return None
        msg = send_response.get("message") or {}
        body = msg.get("body") or {}
        return body.get("mid")

    # ─────────────────── callback answers ───────────────────

    async def answer_callback(
        self,
        callback_id: str,
        *,
        notification: str | None = None,
    ) -> dict:
        """
        Подтверждает обработку нажатия inline-кнопки.

            POST /answers?callback_id=<id>
            body: { message?: NewMessageBody, notification?: string }

        ВАЖНО: MAX требует, чтобы в теле было хотя бы одно поле — иначе 400
        с текстом "Invalid request. `message` or `notification` required".
        Поэтому если notification не передан, шлём пробел " " — он визуально
        не виден, но удовлетворяет валидатор и снимает «крутилку» у клиента.

        Если callback всё же истёк (старая очередь, рестарт бота) — MAX вернёт
        400, мы это глотаем: само нажатие уже обработано выше.
        """
        params = {"callback_id": callback_id}
        body: dict[str, Any] = {"notification": notification if notification else " "}
        try:
            return await self._request("POST", "/answers", params=params, json=body)
        except MaxApiError as e:
            if e.status == 400:
                _log.debug(f"answer_callback ignored ({e.status}): {e.body[:120]}")
                return {}
            raise

    # ─────────────────── файлы ───────────────────

    async def get_upload_url(self, kind: str = "image") -> dict:
        """Получить временный URL для загрузки файла."""
        return await self._request("POST", "/uploads", params={"type": kind})
