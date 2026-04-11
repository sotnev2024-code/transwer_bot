"""
/start для MAX-бота.
"""

from shared import settings_store
from shared.database import save_user
from max_bot.dispatcher import Dispatcher, MaxContext
from max_bot.keyboards import main_menu_kb


async def _send_menu(ctx: MaxContext) -> None:
    await save_user(
        telegram_id=ctx.user_id,
        username=ctx.update.username,
        first_name=ctx.update.first_name,
        last_name=ctx.update.last_name,
        platform="max",
    )
    text = settings_store.get_text("text_welcome")
    await ctx.edit(text, kb=main_menu_kb())


async def on_start(ctx: MaxContext) -> None:
    await ctx.state.clear()
    await _send_menu(ctx)


async def on_start_cmd(ctx: MaxContext) -> None:
    """Пользователь ввёл /start текстом."""
    await ctx.state.clear()
    await _send_menu(ctx)


async def on_menu(ctx: MaxContext) -> None:
    await ctx.state.clear()
    await ctx.answer_callback()
    await _send_menu(ctx)


async def on_help(ctx: MaxContext) -> None:
    text = settings_store.get_text("text_help")
    await ctx.edit(text, kb=main_menu_kb())


def register(dp: Dispatcher) -> None:
    dp.start()(on_start)
    dp.command("start")(on_start_cmd)
    dp.command("help")(on_help)
    dp.callback("action:menu")(on_menu)
