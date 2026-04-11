"""
Probe №2 — проверка callback flow в MAX API.

Запустить:
    .venv/Scripts/python.exe probe_max_cb.py

Что делает:
  1. Ждёт от тебя любое сообщение боту в MAX (просто открой бота, напиши "тест")
  2. Получает chat_id из этого сообщения
  3. Отправляет тебе обратно сообщение с одной inline-кнопкой
  4. Ждёт пока ты нажмёшь на эту кнопку
  5. ПОЛНОСТЬЮ распечатывает raw-формат callback события
  6. Пробует разные варианты ответа на callback и edit карточки

Что нужно от тебя:
  - Запусти скрипт
  - Открой MAX, найди бота "Алтай Прайм Трансфер"
  - Напиши "тест" — придёт сообщение с кнопкой
  - Нажми на кнопку
  - Скинь весь вывод
"""

import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
from shared.config import MAX_BOT_TOKEN

BASE = "https://platform-api.max.ru"


def dump(label: str, data) -> None:
    print(f"\n========== {label} ==========")
    if isinstance(data, (dict, list)):
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(repr(data) if not isinstance(data, str) else data)


async def get_one_update(c, marker, want_type=None):
    """Долгая поллинг до тех пор пока не получим update нужного типа."""
    while True:
        params = {"timeout": 30, "limit": 10}
        if marker:
            params["marker"] = marker
        r = await c.get(f"{BASE}/updates", params=params)
        data = r.json()
        if data.get("marker"):
            marker = data["marker"]
        for upd in data.get("updates") or []:
            if want_type is None or upd.get("update_type") == want_type:
                return upd, marker


async def main():
    if not MAX_BOT_TOKEN:
        print("MAX_BOT_TOKEN не задан в .env")
        return

    headers = {"Authorization": MAX_BOT_TOKEN}
    async with httpx.AsyncClient(timeout=35.0, headers=headers) as c:
        marker = None

        # 1) Ждём первое сообщение, чтобы узнать chat_id
        print("\n⏳ Жду сообщение от тебя в MAX (открой бота и напиши 'тест')...")
        upd, marker = await get_one_update(c, marker, want_type="message_created")
        msg = upd.get("message") or {}
        chat_id = (msg.get("recipient") or {}).get("chat_id")
        print(f"\n✅ Поймал chat_id={chat_id}")

        # 2) Отправляем сообщение с inline-кнопкой
        kb = {
            "type": "inline_keyboard",
            "payload": {
                "buttons": [
                    [{"type": "callback", "text": "🔘 НАЖМИ МЕНЯ", "payload": "test:click"}]
                ]
            }
        }
        send_body = {
            "text": "👉 Нажми на кнопку ниже:",
            "attachments": [kb],
        }
        r = await c.post(f"{BASE}/messages", params={"chat_id": chat_id}, json=send_body)
        sent = r.json()
        dump(f"POST /messages -> {r.status_code}", sent)

        sent_mid = ((sent.get("message") or {}).get("body") or {}).get("mid")
        print(f"\n📌 mid отправленного сообщения: {sent_mid}")

        # 3) Ждём callback
        print("\n⏳ Жду нажатия на кнопку...")
        upd, marker = await get_one_update(c, marker, want_type="message_callback")
        dump("RAW CALLBACK UPDATE", upd)

        # 4) Извлекаем callback_id из update
        cb = upd.get("callback") or {}
        callback_id = cb.get("callback_id") or cb.get("id")
        payload = cb.get("payload") or cb.get("data")
        print(f"\n📌 callback_id = {callback_id}")
        print(f"📌 payload     = {payload}")

        # Где сейчас message_id и user_id?
        cb_msg = upd.get("message") or {}
        cb_body = cb_msg.get("body") or {}
        cb_mid = cb_body.get("mid")
        cb_sender = cb_msg.get("sender") or upd.get("user") or (upd.get("callback") or {}).get("user") or {}
        cb_user_id = cb_sender.get("user_id") or cb_sender.get("id")
        print(f"📌 message.body.mid = {cb_mid}")
        print(f"📌 user_id           = {cb_user_id}")

        # 5) Пробуем разные варианты POST /answers
        if not callback_id:
            print("\n❌ callback_id не найден — больше ничего не пробую")
            return

        print("\n--- Пробуем разные варианты POST /answers ---")
        variants = [
            ("body={}", {}),
            ("body={notification:'OK'}", {"notification": "OK"}),
            ("body={message:{text:'updated'}}", {"message": {"text": "updated"}}),
        ]
        for label, body in variants:
            try:
                r = await c.post(f"{BASE}/answers", params={"callback_id": callback_id}, json=body)
                dump(f"POST /answers {label} -> {r.status_code}", r.text[:400])
            except Exception as e:
                dump(label, f"EXCEPTION: {e}")

        # 6) Пробуем PUT /messages чтобы отредактировать карточку
        if cb_mid:
            edit_body = {
                "text": "✅ Сообщение отредактировано из probe!",
                "attachments": [kb],
            }
            r = await c.put(f"{BASE}/messages", params={"message_id": cb_mid}, json=edit_body)
            dump(f"PUT /messages?message_id={cb_mid[:30]}... -> {r.status_code}", r.text[:400])

            # И ещё раз — без attachments
            r = await c.put(f"{BASE}/messages", params={"message_id": cb_mid}, json={"text": "✅✅ И ещё раз отредактировано (без кнопок)"})
            dump(f"PUT /messages (text only) -> {r.status_code}", r.text[:400])


if __name__ == "__main__":
    asyncio.run(main())
