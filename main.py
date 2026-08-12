import asyncio
import sys
import os
import datetime
import re
import psutil
import time
from aiohttp import web
from supabase import create_client, Client as SupabaseClient

if sys.platform != "win32":
    try:
        import uvloop
        uvloop.install()
        print("🔥 [Движок]: uvloop успешно активирован")
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

# === НАСТРОЙКИ (БЕРУТСЯ ИЗ ENVIRONMENT RENDER) ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
ADMIN_USERNAMES = ["Qwtyf05920Real", "VG9sdWJhZXYgTWl5aXJiZWso"]
TEMP_ADMINS = set()

# === ЛОКАЛИЗАЦИЯ ===
LANG = {
    "btn_start": "Начинаем 🚀", "btn_rules": "Правила 📜", "btn_admin": "👑 АДМИН ПАНЕЛЬ 👑",
    "btn_back": "Назад 🔙", "btn_back_menu": "Назад в меню 🔙", "btn_confirm": "Подтвердить ✅", 
    "btn_activity": "Активность 📊", "btn_autoresp": "Автоответчик 🤖", "btn_timenick": "Время в профиль 🕒", 
    "btn_247": "Режим 24/7 ⚡️", "btn_delete": "Очистить историю 🧹",
    "btn_turn_on": "Активировать ▶️", "btn_turn_off": "Выключить ❌", "btn_tz_select": "Часовой пояс 🕒", 
    "btn_refresh": "Обновить 🔄", "btn_autoresp_setup": "Текст Приветствия 📝", "btn_block_menu": "Блокировать Меню 🔒",
    "btn_register": "Регистрироваться 📝", "status_on": "Включен 🟢", "status_off": "Выключен 🔴",
    "btn_custom_nick": "Кастомизация ✨", "btn_time": "Время 🕒",
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

# === IN-MEMORY КЭШ ===
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

# === БАЗА ДАННЫХ (SUPABASE) ===
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
        # Обновляем базовые данные о юзере при активности
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

# === ЮЗЕРБОТ ФУНКЦИОНАЛ ===
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
    # Обновление экрана админа в реальном времени при новом/удаленном ЛС
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
            await trigger_pm_update(client.owner_id, msg.chat.id)

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
    # Очистка имени от времени и украшений для возврата к дефолту
    name = re.sub(r'\s*(\[.*?\]|⌚.*|⏳.*|★.*|[\d𝟎-𝟗𝟘-𝟡𝟢-𝟫𝟶-𝟿]+[:∶][\d𝟎-𝟗𝟘-𝟡𝟢-𝟫𝟶-𝟿]+)$', '', name)
    name = name.replace("꧁ ", "").replace(" ꧂", "").replace("★ ", "")
    return name.strip()

def apply_custom_nick(base_name, time_str, style_idx):
    bold = str.maketrans("0123456789:", "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗:")
    double = str.maketrans("0123456789:", "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡:")
    sans = str.maketrans("0123456789:", "𝟢𝟣𝟤𝟥𝟤𝟧𝟨𝟩𝟪𝟫:")
    mono = str.maketrans("0123456789:", "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿:")
    
    if style_idx == 1: return f"{base_name} [{time_str}]"
    if style_idx == 2: return f"{base_name} ⌚ {time_str.translate(bold)}"
    if style_idx == 3: return f"{base_name} ⏳ {time_str.translate(double)}"
    if style_idx == 4: return f"꧁ {base_name} ꧂ {time_str.translate(sans)}"
    if style_idx == 5: return f"★ {base_name} ★ {time_str.translate(mono)}"
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
    
    if not cfg.get("logged_in"): return False
    if data["client"] and data["client"].is_connected: return True

    session_str = await get_db_session(user_id)
    if session_str:
        client = Client(f"user_{user_id}", session_string=session_str, api_id=API_ID, api_hash=API_HASH, ipv6=False)
        client.owner_id = user_id
        client.add_handler(MessageHandler(on_new_message, filters.private))
        client.add_handler(DeletedMessagesHandler(on_deleted_message, filters.private))
        data["client"] = client
        try:
            await client.connect()
            await client.get_me()
            
            if not data.get("activity_task"):
                data["activity_task"] = asyncio.create_task(activity_tracker_loop(user_id))
            if cfg.get("status_24_7") and not data.get("task_24_7"):
                data["status_24_7"] = True
                data["task_24_7"] = asyncio.create_task(keep_online_loop(user_id))
            if cfg.get("time_nick_active") and not data.get("time_nick_task"):
                data["time_nick_active"] = True
                data["time_nick_task"] = asyncio.create_task(time_nickname_loop(user_id))
            return True
        except Exception as e:
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

# === TELEGRAM BOT LOKALIZACIA ===
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

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

dp.update.middleware(LockMiddleware())

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

async def edit_or_send(user_id, text, reply_markup=None, parse_mode=None):
    data = get_user_state(user_id)
    if data["msg_id"]:
        try:
            await bot.edit_message_text(chat_id=user_id, message_id=data["msg_id"], text=text, reply_markup=reply_markup, parse_mode=parse_mode)
            return
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower(): return
            try: await bot.delete_message(chat_id=user_id, message_id=data["msg_id"])
            except Exception: pass
    
    msg = await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    data["msg_id"] = msg.message_id

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    try: await message.delete() 
    except Exception: pass
    
    await update_daily_stats('incoming')
    cfg = await get_db_config(user_id, username=message.from_user.username, first_name=message.from_user.first_name)
    
    if await ensure_client_connected(user_id):
        if cfg.get("is_menu_locked") and get_user_state(user_id)["state"] == "WAITING_UNLOCK_CODE": return
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
    try: await message.delete()
    except Exception: pass
    
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
    try: await message.delete()
    except Exception: pass
    
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
    try: await message.delete()
    except Exception: pass
    
    client = get_user_state(user_id)["client"]
    try:
        await client.check_password(pwd)
        await finish_login(user_id, client)
    except Exception:
        msg = await message.answer("❌ Неверный пароль!")
        await asyncio.sleep(3)
        try: await msg.delete()
        except: pass

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
    builder.button(text="🔒 Заблокировать", callback_data="manual_lock")
    
    if is_admin(user_id, username):
        builder.button(text=LANG["btn_admin"], callback_data="admin_menu")
        builder.adjust(2, 2, 2, 2)
    else:
        builder.adjust(2, 2, 2, 1)
        
    await edit_or_send(user_id, LANG["msg_menu"], reply_markup=builder.as_markup())

@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(cb: types.CallbackQuery):
    await show_main_menu(cb.from_user.id, cb.from_user.username)

# === МЕНЮ ПРОФИЛЯ (ВРЕМЯ + КАСТОМИЗАЦИЯ) ===
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
        # Моментальный сброс ника
        if data["client"] and data["client"].is_connected:
            try:
                me = await data["client"].get_me()
                clean_name = strip_time_nick(me.first_name or "User")
                await data["client"].update_profile(first_name=clean_name)
            except Exception: pass
        
    await menu_timenick(cb)

@dp.callback_query(F.data == "select_tz")
async def select_tz(cb: types.CallbackQuery):
    zones = [
        ("Европа / UTC+1", 1), ("Киев / UTC+2", 2), ("МСК / UTC+3", 3), 
        ("Самара / UTC+4", 4), ("Ташкент / UTC+5", 5), ("Омск / UTC+6", 6)
    ]
    builder = InlineKeyboardBuilder()
    for name, offset in zones:
        builder.button(text=name, callback_data=f"set_tz_{offset}_{name}")
    builder.button(text=LANG["btn_back"], callback_data="menu_timenick")
    builder.adjust(2, 2, 2, 1)
    await edit_or_send(cb.from_user.id, "🌍 Выберите ваш часовой пояс:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("set_tz_"))
async def confirm_tz(cb: types.CallbackQuery):
    parts = cb.data.split("_", 3)
    offset = float(parts[2])
    name = parts[3]
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="select_tz")
    builder.button(text="Подтвердить", callback_data=f"save_tz_{offset}_{name}")
    builder.adjust(2)
    
    tz_now = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=offset)).strftime('%H:%M')
    text = f"Вы выбрали {name}.\nВремя сейчас — {tz_now}\nВерно?"
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("save_tz_"))
async def save_tz(cb: types.CallbackQuery):
    parts = cb.data.split("_", 3)
    offset = float(parts[2])
    name = parts[3]
    await update_db_config(cb.from_user.id, {"timezone_offset": offset, "timezone_name": name})
    await menu_timenick(cb)

@dp.callback_query(F.data == "menu_custom_nick")
async def menu_custom_nick(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    client = get_user_state(user_id)["client"]
    base_name = "Имя"
    if client and client.is_connected:
        me = await client.get_me()
        base_name = strip_time_nick(me.first_name or "Имя")
        
    builder = InlineKeyboardBuilder()
    styles = [
        ("Стиль [10:30]", 1),
        ("Стиль 𝟏𝟎:𝟑𝟎", 2),
        ("Стиль ⏳ 𝟙𝟘:𝟛𝟘", 3),
        ("Стиль ꧁ Имя ꧂", 4),
        ("Стиль ★ Имя ★", 5)
    ]
    for s_name, idx in styles:
        builder.button(text=s_name, callback_data=f"set_nick_style_{idx}")
    builder.button(text=LANG["btn_back"], callback_data="menu_profile_settings")
    builder.adjust(1)
    
    cfg = await get_db_config(user_id)
    current_style = cfg.get("custom_nick_style", 1)
    demo_name = apply_custom_nick(base_name, "17:30", current_style)
    
    text = f"✨ **Кастомизация никнейма**\n\nВаш ник сейчас выглядит примерно так:\n`{demo_name}`\n\nВыберите вариант оформления ниже:"
    await edit_or_send(user_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("set_nick_style_"))
async def set_nick_style(cb: types.CallbackQuery):
    style_idx = int(cb.data.split("_")[3])
    user_id = cb.from_user.id
    await update_db_config(user_id, {"custom_nick_style": style_idx})
    
    client = get_user_state(user_id)["client"]
    base_name = "Имя"
    if client and client.is_connected:
        me = await client.get_me()
        base_name = strip_time_nick(me.first_name or "Имя")
    
    demo_name = apply_custom_nick(base_name, "10:30", style_idx)
    builder = InlineKeyboardBuilder().button(text="Назад к главному меню", callback_data="main_menu")
    await edit_or_send(user_id, f"✅ Оформление обновлено!\nВаш ник: `{demo_name}`", reply_markup=builder.as_markup(), parse_mode="Markdown")

# === МЕНЮ АКТИВНОСТИ ===
@dp.callback_query(F.data == "menu_activity")
async def menu_activity(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    res = supabase.table("user_activity").select("activity_data").eq("user_id", user_id).execute()
    act_data = res.data[0]["activity_data"] if res.data else {}
    
    if not act_data:
        text = "📊 История активности пуста. Бот начинает отслеживание!"
    else:
        lines = []
        for day, mins in sorted(act_data.items()):
            hrs = mins // 60
            m = mins % 60
            lines.append(f"📅 **{day}**: {hrs}ч {m}мин")
        text = "📊 **Ваша активность в сети (за 5 дней):**\n\n" + "\n".join(lines)
        
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back_menu"], callback_data="main_menu")
    await edit_or_send(user_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

# === МЕНЮ АВТООТВЕТЧИКА ===
@dp.callback_query(F.data == "menu_autoresponder")
async def menu_autoresponder(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    status_txt = LANG["status_on"] if cfg.get("autoresponder_active") else LANG["status_off"]
    greeting = cfg.get("autoresponder_greeting", LANG["msg_autoresp_default"])
    
    text = f"🤖 **Настройка автоответчика**\n\nСтатус: {status_txt}\n\n**Текст приветствия:**\n_{greeting}_"
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
    await update_db_config(user_id, {"autoresponder_active": not cfg.get("autoresponder_active")})
    await menu_autoresponder(cb)

@dp.callback_query(F.data == "setup_autoresp_text")
async def setup_autoresp_text(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    get_user_state(user_id)["state"] = "WAITING_AUTORESP_TEXT"
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back"], callback_data="menu_autoresponder")
    await edit_or_send(user_id, "📝 Напишите новый текст автоответчика в чат:", reply_markup=builder.as_markup())

@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_AUTORESP_TEXT")
async def process_autoresp_text(message: types.Message):
    user_id = message.from_user.id
    try: await message.delete()
    except Exception: pass
    await update_db_config(user_id, {"autoresponder_greeting": message.text.strip()})
    get_user_state(user_id)["state"] = "MENU"
    
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back"], callback_data="menu_autoresponder")
    await edit_or_send(user_id, "✅ Текст автоответчика успешно сохранен!", reply_markup=builder.as_markup())

# === МЕНЮ ОЧИСТКИ ИСТОРИИ ===
@dp.callback_query(F.data == "menu_delete")
async def menu_delete(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    builder = InlineKeyboardBuilder()
    for count in [10, 25, 50, 100]:
        builder.button(text=f"🗑 {count}", callback_data=f"confirm_purge_{count}")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(2, 2, 1)
    await edit_or_send(user_id, LANG["msg_del_text"], reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("confirm_purge_"))
async def confirm_purge(cb: types.CallbackQuery):
    count = int(cb.data.split("_")[2])
    builder = InlineKeyboardBuilder()
    builder.button(text="Да", callback_data=f"dopurge_{count}")
    builder.button(text="Нет / Назад", callback_data="menu_delete")
    builder.adjust(2)
    await edit_or_send(cb.from_user.id, f"⚠️ Вы точно хотите удалить последние {count} сообщений?", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("dopurge_"))
async def do_purge(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    count = int(cb.data.split("_")[1])
    data = get_user_state(user_id)
    
    if not data["client"] or not data["client"].is_connected:
        await edit_or_send(user_id, "❌ Юзербот не активен.")
        return

    await edit_or_send(user_id, "⏳ Подождите... Идёт удаление...")

    deleted = 0
    try:
        async for dialog in data["client"].get_dialogs(limit=20):
            my_msgs = []
            async for m in data["client"].get_chat_history(dialog.chat.id):
                if m.from_user and m.from_user.is_self:
                    my_msgs.append(m.id)
                    if len(my_msgs) == count: break
            if my_msgs:
                await data["client"].delete_messages(dialog.chat.id, my_msgs)
                deleted += len(my_msgs)
        text = f"✅ Успешно удалено: {deleted} сообщений!"
    except Exception as e:
        text = f"⚠️ Ошибка при очистке: {e}"
        
    builder = InlineKeyboardBuilder().button(text="Назад", callback_data="menu_delete")
    await edit_or_send(user_id, text, reply_markup=builder.as_markup())

# === БЛОКИРОВКА МЕНЮ PIN-КОДОМ ===
@dp.callback_query(F.data == "menu_block_settings")
async def menu_block_settings(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    locked = cfg.get("is_menu_locked", False)
    status_txt = "Заблокировано 🔒" if locked else "Разблокировано 🔓"
    
    text = f"🔒 **Блокировка меню**\n\nТекущий статус: {status_txt}"
    builder = InlineKeyboardBuilder()
    if locked:
        builder.button(text="Снять PIN-код 🔓", callback_data="unlock_pin_setup")
    else:
        builder.button(text="Установить PIN-код 🔒", callback_data="set_pin_setup")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(1)
    await edit_or_send(user_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "set_pin_setup")
async def set_pin_setup(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    get_user_state(user_id)["state"] = "WAITING_SET_PIN"
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back"], callback_data="menu_block_settings")
    await edit_or_send(user_id, "🔒 Отправьте 4 цифры PIN-кода:", reply_markup=builder.as_markup())

@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_SET_PIN")
async def process_set_pin(message: types.Message):
    user_id = message.from_user.id
    code = message.text.strip()
    try: await message.delete()
    except Exception: pass
    
    if not code.isdigit() or len(code) != 4:
        msg = await message.answer("❌ PIN-код должен состоять ровно из 4 цифр!")
        await asyncio.sleep(3)
        try: await msg.delete()
        except: pass
        return
        
    await update_db_config(user_id, {"is_menu_locked": True, "menu_lock_code": code, "last_interaction_time": time.time()})
    get_user_state(user_id)["state"] = "MENU"
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back_menu"], callback_data="main_menu")
    await edit_or_send(user_id, "✅ PIN-код установлен! Теперь при долгом простое меню блокируется.", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "unlock_pin_setup")
async def unlock_pin_setup(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    await update_db_config(user_id, {"is_menu_locked": False, "menu_lock_code": None})
    await menu_block_settings(cb)

@dp.callback_query(F.data == "manual_lock")
async def manual_lock(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    if cfg.get("is_menu_locked"):
        get_user_state(user_id)["state"] = "WAITING_UNLOCK_CODE"
        if get_user_state(user_id)["msg_id"]:
            try: await bot.delete_message(user_id, get_user_state(user_id)["msg_id"])
            except: pass
        msg = await bot.send_message(user_id, LANG["msg_unlock_req"])
        get_user_state(user_id)["msg_id"] = msg.message_id
    else:
        await cb.answer("❌ PIN-код не установлен. Настройте его в блокировке меню.", show_alert=True)

@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_UNLOCK_CODE")
async def process_unlock_code(message: types.Message):
    user_id = message.from_user.id
    code = message.text.strip()
    try: await message.delete()
    except Exception: pass
    
    cfg = await get_db_config(user_id)
    if cfg.get("menu_lock_code") == code:
        data = get_user_state(user_id)
        data["state"] = "MENU"
        await update_db_config(user_id, {"last_interaction_time": time.time()})
        try:
            if data["msg_id"]: await bot.delete_message(user_id, data["msg_id"])
        except: pass
        data["msg_id"] = None 
        await show_main_menu(user_id, message.from_user.username)
    else:
        msg = await message.answer("❌ Неверный PIN-код!")
        await asyncio.sleep(3)
        try: await msg.delete()
        except: pass

# === 24/7 РЕЖИМ ===
@dp.callback_query(F.data == "toggle_247")
async def toggle_247(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    new_status = not cfg.get("status_24_7")
    await update_db_config(user_id, {"status_24_7": new_status})
    
    data = get_user_state(user_id)
    data["status_24_7"] = new_status
    if new_status:
        if data["client"] and data["client"].is_connected:
            try: await data["client"].invoke(functions.account.UpdateStatus(offline=False))
            except: pass
        if not data.get("task_24_7"):
            data["task_24_7"] = asyncio.create_task(keep_online_loop(user_id))
    elif not new_status and data.get("task_24_7"):
        data["task_24_7"].cancel()
        data["task_24_7"] = None

    status_txt = LANG["status_on"] if new_status else LANG["status_off"]
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_turn_off"] if new_status else LANG["btn_turn_on"], callback_data="toggle_247")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(1)
    await edit_or_send(user_id, LANG["msg_247_text"].format(status_txt), reply_markup=builder.as_markup())

# === АДМИН ПАНЕЛЬ ===
@dp.callback_query(F.data == "admin_menu")
async def admin_menu(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    get_user_state(cb.from_user.id)["current_menu"] = "admin_main"
    text = "👑 **Меню Администрации:**"
    builder = InlineKeyboardBuilder()
    builder.button(text="Статус 📊", callback_data="admin_status")
    builder.button(text="Юзеры 👥", callback_data="admin_users")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(2, 1)
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

async def refresh_admin_status(admin_id):
    today = datetime.datetime.now().date()
    text = "📊 **Статус актива (За 7 дней):**\n\n"
    for i in range(6, -1, -1):
        dt = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
        res = supabase.table("daily_stats").select("*").eq("date", dt).execute()
        inc = res.data[0]["incoming"] if res.data else 0
        act = res.data[0]["active"] if res.data else 0
        text += f"📅 {dt} — {inc} входящих | {act} активных\n"
        
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_refresh"], callback_data="admin_status")
    builder.button(text=LANG["btn_back"], callback_data="admin_menu")
    builder.adjust(1)
    await edit_or_send(admin_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

async def admin_status_loop():
    while True:
        await asyncio.sleep(60)
        for uid, data in list(USER_DATA.items()):
            if data.get("current_menu") == "admin_status":
                await refresh_admin_status(uid)

@dp.callback_query(F.data == "admin_status")
async def admin_status(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    get_user_state(cb.from_user.id)["current_menu"] = "admin_status"
    await refresh_admin_status(cb.from_user.id)

@dp.callback_query(F.data == "admin_users")
async def admin_users(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    get_user_state(cb.from_user.id)["current_menu"] = "admin_users"
    
    res_a = supabase.table("user_configs").select("user_id", count="exact").eq("logged_in", True).execute()
    c_active = res_a.count
    
    res_s = supabase.table("user_sessions").select("user_id").execute()
    all_session_uids = [r["user_id"] for r in res_s.data]
    res_c = supabase.table("user_configs").select("user_id").eq("logged_in", True).execute()
    active_uids = [r["user_id"] for r in res_c.data]
    c_outgoing = len(list(set(all_session_uids) - set(active_uids)))
    
    res_all = supabase.table("user_configs").select("user_id", count="exact").execute()
    c_inc = max(res_all.count - len(all_session_uids), 0)
    
    text = "👥 **Пользователи бота:**"
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Активные ({c_active})", callback_data="admin_ulist_active_1")
    builder.button(text=f"Входящие ({c_inc})", callback_data="admin_ulist_incoming_1")
    builder.button(text=f"Выходящие ({c_outgoing})", callback_data="admin_ulist_outgoing_1")
    builder.button(text=LANG["btn_back"], callback_data="admin_menu")
    builder.adjust(1)
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

def build_pagination(prefix, current_page, total_items, limit=5):
    total_pages = (total_items + limit - 1) // limit
    if total_pages <= 1: return []
    buttons = []
    if current_page > 1:
        buttons.append(types.InlineKeyboardButton(text="Назад", callback_data=f"{prefix}_{current_page-1}"))
    buttons.append(types.InlineKeyboardButton(text=str(current_page), callback_data="ignore"))
    if current_page < total_pages:
        buttons.append(types.InlineKeyboardButton(text="Вперед", callback_data=f"{prefix}_{current_page+1}"))
    return buttons

@dp.callback_query(F.data.startswith("admin_ulist_"))
async def admin_ulist(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    get_user_state(cb.from_user.id)["current_menu"] = "admin_ulist"
    parts = cb.data.split("_")
    cat = parts[2]
    page = int(parts[3])
    limit = 5
    offset = (page - 1) * limit
    builder = InlineKeyboardBuilder()
    
    if cat == "active":
        title = "🟢 **Активные пользователи:**"
        res = supabase.table("user_configs").select("user_id, first_name").eq("logged_in", True).range(offset, offset+limit-1).execute()
        res_count = supabase.table("user_configs").select("user_id", count="exact").eq("logged_in", True).execute()
        for row in res.data:
            uid = row["user_id"]
            name = row.get("first_name", f"User {uid}")
            builder.button(text=name, callback_data=f"admin_ucard_{uid}")
        builder.adjust(1)
            
    elif cat == "outgoing":
        title = "🔴 **Выходящие пользователи:**"
        res_s = supabase.table("user_sessions").select("user_id").execute()
        all_session_uids = [r["user_id"] for r in res_s.data]
        res_a = supabase.table("user_configs").select("user_id").eq("logged_in", True).execute()
        active_uids = [r["user_id"] for r in res_a.data]
        out_uids = list(set(all_session_uids) - set(active_uids))
        
        res_count = type('obj', (object,), {'count': len(out_uids)})
        chunk = out_uids[offset:offset+limit]
        for uid in chunk:
            res_conf = supabase.table("user_configs").select("first_name").eq("user_id", uid).execute()
            name = res_conf.data[0]["first_name"] if res_conf.data else f"User {uid}"
            builder.button(text=name, callback_data=f"admin_ucard_{uid}")
        builder.adjust(1)
            
    elif cat == "incoming":
        title = "📩 **Входящие:**"
        res_all = supabase.table("user_configs").select("*").order("last_interaction_time", desc=True).execute()
        res_s = supabase.table("user_sessions").select("user_id").execute()
        session_uids = [r["user_id"] for r in res_s.data]
        inc_data = [r for r in res_all.data if r["user_id"] not in session_uids]
        
        res_count = type('obj', (object,), {'count': len(inc_data)})
        chunk = inc_data[offset:offset+limit]
        text = f"{title}\n\n"
        
        for r in chunk:
            uid = r["user_id"]
            dt = datetime.datetime.fromtimestamp(r.get("last_interaction_time", time.time())).strftime("%d.%m %H:%M")
            name = r.get("first_name", "Без имени")
            uname = f"@{r['username']}" if r.get("username") else ""
            text += f"🕒 `{dt}`: {name} {uname} (ID: {uid})\n"
        
        pag_btns = build_pagination(f"admin_ulist_{cat}", page, res_count.count, limit)
        if pag_btns: builder.row(*pag_btns)
        builder.row(types.InlineKeyboardButton(text="Назад", callback_data="admin_users"))
        await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        return

    pag_btns = build_pagination(f"admin_ulist_{cat}", page, res_count.count, limit)
    if pag_btns: builder.row(*pag_btns)
    builder.row(types.InlineKeyboardButton(text="Назад", callback_data="admin_users"))
    await edit_or_send(cb.from_user.id, title, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("admin_ucard_"))
async def admin_ucard(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    uid = int(cb.data.split("_")[2])
    get_user_state(cb.from_user.id)["current_menu"] = "admin_ucard"
    
    res = supabase.table("user_sessions").select("phone").eq("user_id", uid).execute()
    phone = res.data[0]["phone"] if res.data else "Неизвестно"
    
    act_res = supabase.table("user_activity").select("activity_data").eq("user_id", uid).execute()
    hrs = 0
    if act_res.data:
        today = datetime.datetime.now().strftime("%d.%m.%Y")
        mins = act_res.data[0]["activity_data"].get(today, 0)
        hrs = mins // 60
        
    del_res = supabase.table("messages_log").select("id", count="exact").eq("user_id", uid).eq("is_deleted", True).execute()
    del_count = del_res.count if del_res else 0
    
    res_c = supabase.table("user_configs").select("first_name").eq("user_id", uid).execute()
    name = res_c.data[0].get("first_name", f"Пользователь {uid}") if res_c.data else f"Пользователь {uid}"
    
    text = f"👤 **{name}**\n\nНомер: `{phone}`\nОблачный пароль: [Не сохраняется]\nВ сети сегодня: {hrs} часов\nУдалил сообщений: {del_count}"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Лички", callback_data=f"admin_upms_{uid}_1")
    builder.button(text="Назад", callback_data="admin_users")
    builder.adjust(1)
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("admin_upms_"))
async def admin_upms(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    get_user_state(cb.from_user.id)["current_menu"] = "admin_upms"
    parts = cb.data.split("_")
    uid = int(parts[2])
    page = int(parts[3])
    limit = 5
    offset = (page - 1) * limit
    
    res = supabase.table("messages_log").select("chat_id, sender_name, date").eq("user_id", uid).order("date", desc=True).execute()
    chats = {}
    for r in res.data:
        cid = r["chat_id"]
        if cid not in chats: chats[cid] = r["sender_name"]
        if len(chats) >= 25: break
        
    chat_list = list(chats.items())
    chunk = chat_list[offset:offset+limit]
    
    # Пытаемся получить непрочитанные безопасно, если клиент онлайн
    unread_counts = {}
    if uid in USER_DATA and USER_DATA[uid].get("client") and USER_DATA[uid]["client"].is_connected:
        try:
            async for d in USER_DATA[uid]["client"].get_dialogs(limit=30):
                unread_counts[d.chat.id] = d.unread_messages_count
        except: pass
    
    text = f"💬 **Личные диалоги:**"
    builder = InlineKeyboardBuilder()
    for cid, name in chunk:
        unread = unread_counts.get(cid, 0)
        unread_str = f" ({unread})" if unread > 0 else ""
        builder.button(text=f"{name}{unread_str}", callback_data=f"admin_viewpm_{uid}_{cid}_1")
    builder.adjust(1)
    
    pag_btns = build_pagination(f"admin_upms_{uid}", page, len(chat_list), limit)
    if pag_btns: builder.row(*pag_btns)
    builder.row(types.InlineKeyboardButton(text="Назад", callback_data=f"admin_ucard_{uid}"))
    
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

async def refresh_admin_pm_view(admin_id, uid, cid, page):
    limit = 5
    offset = (page - 1) * limit
    
    res = supabase.table("messages_log").select("*").eq("user_id", uid).eq("chat_id", cid).order("date", desc=True).range(offset, offset+limit-1).execute()
    res_count = supabase.table("messages_log").select("id", count="exact").eq("user_id", uid).eq("chat_id", cid).execute()
    
    msgs = res.data[::-1] # Хронологический порядок снизу
    text = f"📜 **История диалога:**\n\n"
    for r in msgs:
        dt = datetime.datetime.fromisoformat(r["date"]).strftime("%H:%M")
        name = r["sender_name"]
        content = r["text"]
        if r["is_media"]: content += f" {r['media_type']}"
        if r["is_deleted"]: content += " |УДАЛЕНО|"
        text += f"`{dt}` | **{name}**: {content}\n"
        
    builder = InlineKeyboardBuilder()
    pag_btns = build_pagination(f"admin_viewpm_{uid}_{cid}", page, min(res_count.count, 50), limit)
    if pag_btns: builder.row(*pag_btns)
    builder.row(types.InlineKeyboardButton(text="Назад", callback_data=f"admin_upms_{uid}_1"))
    
    await edit_or_send(admin_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("admin_viewpm_"))
async def admin_viewpm(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    parts = cb.data.split("_")
    uid = int(parts[2])
    cid = int(parts[3])
    page = int(parts[4])
    
    u_state = get_user_state(cb.from_user.id)
    u_state["current_menu"] = "admin_viewpm"
    u_state["admin_view_user"] = uid
    u_state["admin_view_chat"] = cid
    u_state["admin_view_page"] = page
    
    await refresh_admin_pm_view(cb.from_user.id, uid, cid, page)

# === ЗАПУСК И ВОССТАНОВЛЕНИЕ ===
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
    print(f"🌐 Web server listening on 0.0.0.0:{port}")

async def on_startup():
    print("🚀 Бот запущен. Восстановление активных сессий...")
    try:
        res = supabase.table("user_configs").select("*").eq("logged_in", True).execute()
        if res.data:
            for row in res.data:
                uid = row["user_id"]
                data = get_user_state(uid)
                data["is_menu_locked"] = row.get("is_menu_locked", False)
                data["last_interaction_time"] = row.get("last_interaction_time", time.time())
                await ensure_client_connected(uid)
    except Exception as e:
        print(f"⚠️ Ошибка при авто-восстановлении: {e}")
        
    asyncio.create_task(start_web_server())
    asyncio.create_task(background_lock_monitor())
    asyncio.create_task(admin_status_loop())

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(on_startup())
    loop.run_until_complete(dp.start_polling(bot))
