"""
Диагностический probe для MAX API.

Запустить:
    .venv/Scripts/python.exe probe_max.py

Что делает:
  1. Запрашивает /updates в long-polling
  2. Когда придёт первое сообщение от пользователя — печатает его raw-формат
  3. Пробует отправить ответное сообщение, печатает raw-ответ (там должен быть mid)
  4. Пробует отредактировать это сообщение разными вариантами параметров
  5. Печатает результат каждого варианта

Что нужно от тебя:
  - Открой MAX, найди бота "Алтай Прайм Трансфер" / @id222208315435_bot
  - Отправь ему любое текстовое сообщение, например "привет"
  - Скинь мне весь вывод этого скрипта
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
        print(repr(data))


async def main():
    if not MAX_BOT_TOKEN:
        print("MAX_BOT_TOKEN не задан в .env")
        return

    headers = {"Authorization": MAX_BOT_TOKEN}
    async with httpx.AsyncClient(timeout=35.0, headers=headers) as c:
        # 1) Получить /me (для понимания формата)
        r = await c.get(f"{BASE}/me")
        dump("GET /me", r.json())

        # 2) Long polling — ждём первое сообщение
        marker = None
        chat_id = None
        first_msg = None
        print("\n⏳ Жду входящее сообщение в MAX (открой бота и напиши 'привет')...")
        for _ in range(20):
            params = {"timeout": 30, "limit": 10}
            if marker:
                params["marker"] = marker
            r = await c.get(f"{BASE}/updates", params=params)
            data = r.json()
            updates = data.get("updates") or []
            if data.get("marker"):
                marker = data["marker"]
            if updates:
                dump("RAW UPDATES", data)
                # Ищем первое message_created или bot_started
                for upd in updates:
                    dump(f"update_type={upd.get('update_type')}", upd)
                    msg = upd.get("message") or {}
                    rec = msg.get("recipient") or {}
                    if rec.get("chat_id"):
                        chat_id = rec["chat_id"]
                        first_msg = msg
                        break
                    # bot_started тоже даёт chat_id
                    if upd.get("chat_id"):
                        chat_id = upd["chat_id"]
                        break
                if chat_id:
                    break

        if not chat_id:
            print("\n❌ Не дождался входящего сообщения. Перезапусти скрипт и напиши боту в MAX.")
            return

        print(f"\n✅ Поймал chat_id = {chat_id}")

        # 3) Отправить сообщение
        send_body = {"text": "🤖 Probe: тестовое сообщение"}
        r = await c.post(f"{BASE}/messages", params={"chat_id": chat_id}, json=send_body)
        dump(f"POST /messages?chat_id={chat_id} -> {r.status_code}", r.json() if r.status_code < 300 else r.text)

        sent = r.json() if r.status_code < 300 else {}
        # Найдём mid в ответе
        mid = None
        for keys in (
            ["message", "body", "mid"],
            ["message", "mid"],
            ["body", "mid"],
            ["mid"],
            ["message_id"],
            ["id"],
        ):
            cur = sent
            for k in keys:
                if isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    cur = None
                    break
            if cur is not None:
                mid = cur
                print(f"\n📌 Нашёл message id по пути {keys} = {mid!r}")
                break

        if not mid:
            print("\n❌ Не нашёл message id в ответе POST /messages — нужен ручной разбор")
            return

        # 4) Попробуем разные варианты edit
        edit_body = {"text": "🤖 Probe: ОТРЕДАКТИРОВАНО"}

        variants = [
            ("PUT /messages?message_id=", "PUT", "/messages", {"message_id": mid}),
            ("PUT /messages?mid=",        "PUT", "/messages", {"mid": mid}),
            ("PUT /messages/{mid}",        "PUT", f"/messages/{mid}", {}),
        ]
        for label, method, path, params in variants:
            try:
                r = await c.request(method, f"{BASE}{path}", params=params, json=edit_body)
                dump(f"{label} -> {r.status_code}", r.text[:600])
            except Exception as e:
                dump(label, f"EXCEPTION: {e}")

        # 5) Попробуем delete
        del_variants = [
            ("DELETE /messages?message_id=", {"message_id": mid}),
            ("DELETE /messages?mid=",        {"mid": mid}),
        ]
        for label, params in del_variants:
            try:
                r = await c.request("DELETE", f"{BASE}/messages", params=params)
                dump(f"{label} -> {r.status_code}", r.text[:400])
            except Exception as e:
                dump(label, f"EXCEPTION: {e}")


if __name__ == "__main__":
    asyncio.run(main())
