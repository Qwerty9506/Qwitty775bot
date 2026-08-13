import sys
import os
import asyncio
import time
from aiohttp import web
from aiogram import Dispatcher, BaseMiddleware, types

from config import bot, get_user_state, USER_DATA, LANG, supabase
from database import update_db_config
from userbot import ensure_client_connected

from handlers import auth, user, admin

if sys.platform != "win32":
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass

# Lock Middleware
class LockMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = None
        if isinstance(event, types.CallbackQuery):
            user_id = event.from_user.id
            if event.message: get_user_state(user_id)["msg_id"] = event.message.message_id
        elif isinstance(event, types.Message):
            user_id = event.from_user.id
            
        if user_id:
            now = time.time()
            u_state = get_user_state(user_id)
            locked = u_state.get("is_menu_locked", False)
            last_active = u_state.get("last_interaction_time", now)
            
            if locked and (now - last_active > 300):
                if u_state.get("state") != "WAITING_UNLOCK_CODE":
                    u_state["state"] = "WAITING_UNLOCK_CODE"
                    try:
                        if isinstance(event, types.CallbackQuery) and event.message:
                            await event.message.delete()
                    except: pass
                    msg = await bot.send_message(user_id, LANG["msg_unlock_req"])
                    u_state["msg_id"] = msg.message_id
                    return
            
            await update_db_config(user_id, {"last_interaction_time": now})
        return await handler(event, data)

async def background_lock_monitor():
    while True:
        await asyncio.sleep(10)
        now = time.time()
        for uid, data in list(USER_DATA.items()):
            if data.get("is_menu_locked") and data.get("state") != "WAITING_UNLOCK_CODE":
                last_active = data.get("last_interaction_time", now)
                if now - last_active > 300:
                    data["state"] = "WAITING_UNLOCK_CODE"
                    try:
                        if data.get("msg_id"):
                            await bot.edit_message_text(LANG["msg_unlock_req"], chat_id=uid, message_id=data["msg_id"])
                        else:
                            msg = await bot.send_message(uid, LANG["msg_unlock_req"])
                            data["msg_id"] = msg.message_id
                    except Exception: pass

# Catch-all для мусора
async def catch_all_messages(message: types.Message):
    from utils import delayed_delete
    asyncio.create_task(delayed_delete(message, 0))

# Web Server
async def render_web_handler(request):
    return web.Response(text="Сервер работает 🚀")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', render_web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def on_startup():
    try:
        res = supabase.table("user_configs").select("*").eq("logged_in", True).execute()
        if res.data:
            for row in res.data:
                uid = row["user_id"]
                data = get_user_state(uid)
                data["is_menu_locked"] = row.get("is_menu_locked", False)
                data["last_interaction_time"] = row.get("last_interaction_time", time.time())
                await ensure_client_connected(uid)
    except Exception:
        pass
        
    asyncio.create_task(start_web_server())
    asyncio.create_task(background_lock_monitor())

async def main():
    dp = Dispatcher()
    
    # Middleware
    dp.update.middleware(LockMiddleware())
    
    # Регистрация роутеров
    dp.include_router(auth.router)
    dp.include_router(user.router)
    dp.include_router(admin.router)
    
    # Перехват мусорных сообщений
    dp.message.register(catch_all_messages)
    
    loop = asyncio.get_event_loop()
    loop.create_task(on_startup())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
