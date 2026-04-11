import os
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext

from tg_bot.keyboards import main_menu_kb
from shared.database import save_user
from shared import settings_store

router = Router()

# Корень проекта: .../transfer_bot/  (поднимаемся на 3 уровня:
# handlers → tg_bot → transfer_bot)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PHOTO_PATH = str(_PROJECT_ROOT / "46232fe1-436d-4c42-820a-3eb79654df13.webp")


async def send_menu(bot: Bot, chat_id: int) -> None:
    """Send main menu as photo+caption or plain text, depending on settings."""
    text = settings_store.get_text("text_welcome")
    kb = main_menu_kb()
    photo_fid = settings_store.get_menu_photo()

    if photo_fid:
        try:
            await bot.send_photo(chat_id, photo=photo_fid, caption=text, reply_markup=kb)
            return
        except Exception:
            pass

    if os.path.isfile(_PHOTO_PATH):
        try:
            msg = await bot.send_photo(
                chat_id,
                photo=FSInputFile(_PHOTO_PATH),
                caption=text,
                reply_markup=kb,
            )
            fid = msg.photo[-1].file_id
            await settings_store.save_setting("menu_photo_file_id", fid)
            return
        except Exception:
            pass

    await bot.send_message(chat_id, text, reply_markup=kb)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    await save_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name,
        platform="telegram",
    )
    await send_menu(bot, message.chat.id)


@router.callback_query(F.data == "action:menu")
async def go_to_menu(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await send_menu(bot, callback.message.chat.id)
    await callback.answer()


@router.message(F.text == "/help")
async def cmd_help(message: Message) -> None:
    await message.answer(
        settings_store.get_text("text_help"),
        reply_markup=main_menu_kb(),
    )
