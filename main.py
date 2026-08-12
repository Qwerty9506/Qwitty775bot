import asyncio
import sys
import os
import datetime
import re
import psutil
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

# === НАСТРОЙКИ (БЕРУТСЯ ИЗ ENVIRONMENT RENDER) ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = int(os.getenv("API_ID", ""))
API_HASH = os.getenv("API_HASH", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
ADMIN_USERNAMES = ["Qwtyf05920Real", "VG9sdWJhZXYgTWl5aXJiZWso"]
TEMP_ADMINS = set()

# === ЛОКАЛИЗАЦИЯ (ТОЛЬКО РУССКИЙ) ===
LANG = {
    "btn_start": "Начинаем 🚀", "btn_rules": "Правила 📜", "btn_admin": "👑 АДМИН ПАНЕЛЬ 👑",
    "btn_back": "Назад 🔙", "btn_back_menu": "Назад в меню 🔙", "btn_confirm": "Подтвердить ✅", 
    "btn_activity": "Активность 📊", "btn_autoresp": "Автоответчик 🤖", "btn_timenick": "Время в профиль 🕒", 
    "btn_247": "Режим 24/7 ⚡️", "btn_delete": "Очистить историю 🧹",
    "btn_turn_on": "Активировать ▶️", "btn_turn_off": "Выключить ❌", "btn_tz_select": "Часовой пояс 🕒", 
    "btn_refresh": "Обновить 🔄", "btn_autoresp_setup": "Текст Приветствия 📝", "btn_block_menu": "Блокировать Меню 🔒",
    "btn_register": "Регистрироваться 📝", "status_on": "Включен 🟢", "status_off": "Выключен 🔴",
    "msg_start": "Здравствуйте!\nДобро пожаловать в бота управления аккаунтом.\nОзнакомьтесь с правилами.",
    "msg_menu": "Что умеет этот бот?\nВыбирайте доступные функции управления вашим аккаунтом снизу:",
    "msg_rules_text": "📜 **Правила использования бота:**\n\n1. Бот работает через юзербота.\n2. Все данные хранятся в защищенной области.\n3. Бот работает 24/7 без ограничений.\nСтрого не рекомендуем частично спамить, часто удалять сообщения, а также надолго оставлять режим 24/7 включённым.\n\n_СТАТУС: UNLIMITED._",
    "msg_phone_req": "Отправьте номер телефона в международном формате (например, +998901234567).",
    "msg_code_req": "Код авторизации отправлен.\n⚠️ Напишите код из сообщения Telegram!",
    "msg_pwd_req": "Аккаунт защищен облачным паролем.\nВведите его в чат:",
    "msg_success_login": "Бот успешно авторизовался!\nНажмите кнопку ниже для продолжения.",
    "msg_btn_go": "Поехали ➡️",
    "msg_autoresp_default": "👋 Здравствуйте! Я сейчас не в сети, отвечу позже.",
    "msg_timenick_text": "Вывод времени в имя профиля.\nТекущий статус: {0}\nСмещение часового пояса: UTC+{1}",
    "msg_247_text": "⚡️ Режим 24/7\n\nСтатус: {0}\nБот поддерживает ваш аккаунт онлайн постоянно.",
    "msg_del_text": "🗑 **Зачистка истории**\nВыберите, сколько последних сообщений удалить из всех чатов:",
    "msg_session_revoked": "⚠️ Юзербот отключен.\nНажмите кнопку ниже, чтобы зарегистрироваться заново.",
    "msg_block_setup": "Введите 4-значный PIN-код для блокировки меню:",
    "msg_unlock_req": "🔒 Меню заблокировано. Введите PIN-код для входа:"
}

# === IN-MEMORY КЭШ (Для сокетов и фоновых тасков) ===
USER_DATA = {}

def get_user_state(user_id):
    if user_id not in USER_DATA:
        USER_DATA[user_id] = {
            "msg_id": None, "phone": None, "password": None, "phone_code_hash": None,
            "client": None, "state": "START", "time_nick_active": False, "time_nick_task": None,
            "status_24_7": False, "task_24_7": None, "activity_task": None
        }
    return USER_DATA[user_id]

def is_admin(user_id, username):
    clean = username.replace("@", "") if username else ""
    return clean in ADMIN_USERNAMES or user_id in TEMP_ADMINS

# === РАБОТА С СУПЕР-БАЗОЙ (SUPABASE) ===
async def get_db_config(user_id):
    res = supabase.table("user_configs").select("*").eq("user_id", user_id).execute()
    if not res.data:
        default = {
            "user_id": user_id, "status_24_7": False, "time_nick_active": False, 
            "autoresponder_active": False, "autoresponder_greeting": LANG["msg_autoresp_default"],
            "timezone_offset": 5, "replied_users": [], "is_menu_locked": False, 
            "menu_lock_code": None, "logged_in": False
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

# === ЮЗЕРБОТ ФУНКЦИОНАЛ ===
async def autoresponder_func(client, message):
    if not message.chat or message.chat.type != enums.ChatType.PRIVATE: return
    if message.from_user and (message.from_user.is_self or message.from_user.is_bot): return
    
    user_id = client.owner_id
    cfg = await get_db_config(user_id)
    if not cfg.get("autoresponder_active"): return
    
    sender_id = message.from_user.id
    replied = cfg.get("replied_users", [])
    if sender_id in replied: return

    # Проверка переписки
    async for msg in client.get_chat_history(sender_id, limit=5):
        if msg.from_user and msg.from_user.is_self:
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
            await data["client"].invoke(functions.account.UpdateStatus(offline=False))
        except Unauthorized:
            await handle_revoked_session(user_id)
            break
        except Exception:
            pass
        await asyncio.sleep(30)

async def time_nickname_loop(user_id):
    data = get_user_state(user_id)
    while data["time_nick_active"]:
        if not data["client"] or not data["client"].is_connected: break
        try:
            me = await data["client"].get_me()
            cfg = await get_db_config(user_id)
            offset = cfg.get("timezone_offset", 5)
            tz_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=offset, seconds=30)
            
            base_name = me.first_name or "User"
            base_name = re.sub(r'\s*\[.*?\]', '', base_name).strip()
            final_name = f"{base_name} [{tz_now.strftime('%H:%M')}]"
            
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
            await data["client"].get_me()
            today = datetime.datetime.now().strftime("%d.%m.%Y")
            res = supabase.table("user_activity").select("activity_data").eq("user_id", user_id).execute()
            act_data = res.data[0]["activity_data"] if res.data else {}
            
            act_data[today] = act_data.get(today, 0) + 1  # Записываем минуты активности
            
            # Храним только за последние 5 дней
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
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_register"], callback_data="start_login")
    await edit_or_send(user_id, LANG["msg_session_revoked"], reply_markup=builder.as_markup())

# === TELEGRAM BOT LOKALIZACIA ===
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class Middleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, types.CallbackQuery) and event.message:
            user_id = event.from_user.id
            get_user_state(user_id)["msg_id"] = event.message.message_id
        return await handler(event, data)

dp.callback_query.middleware(Middleware())

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
    await cmd_start(cb.message)

@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_PHONE")
async def process_phone(message: types.Message):
    user_id = message.from_user.id
    phone = message.text.strip().replace(" ", "")
    try: await message.delete()
    except Exception: pass
    
    if not phone.startswith("+"): return
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

# === МЕНЮ ОЧИСТКИ ===
@dp.callback_query(F.data == "menu_delete")
async def menu_delete(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    builder = InlineKeyboardBuilder()
    for count in [10, 50, 100, 200]:
        builder.button(text=f"🗑 Последние {count}", callback_data=f"purge_{count}")
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
            msgs = [m.id async for m in data["client"].get_chat_history(dialog.chat.id, limit=count) if m.from_user and m.from_user.is_self]
            if msgs:
                await data["client"].delete_messages(dialog.chat.id, msgs)
                deleted += len(msgs)
        text = f"✅ Успешно очищено {deleted} ваших сообщений!"
    except Exception as e:
        text = f"⚠️ Ошибка при очистке: {e}"
        
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back_menu"], callback_data="main_menu")
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
        await edit_or_send(user_id, "❌ PIN-код должен состоять ровно из 4 цифр!")
        return
        
    await update_db_config(user_id, {"is_menu_locked": True, "menu_lock_code": code})
    get_user_state(user_id)["state"] = "MENU"
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back_menu"], callback_data="main_menu")
    await edit_or_send(user_id, "✅ PIN-код установлен! Теперь при входе меню заблокировано.", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "unlock_pin_setup")
async def unlock_pin_setup(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    await update_db_config(user_id, {"is_menu_locked": False, "menu_lock_code": None})
    await menu_block_settings(cb)

@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_UNLOCK_CODE")
async def process_unlock_code(message: types.Message):
    user_id = message.from_user.id
    code = message.text.strip()
    try: await message.delete()
    except Exception: pass
    
    cfg = await get_db_config(user_id)
    if cfg.get("menu_lock_code") == code:
        get_user_state(user_id)["state"] = "MENU"
        await show_main_menu(user_id, message.from_user.username)
    else:
        await edit_or_send(user_id, "❌ Неверный PIN-код! Попробуйте еще раз:")

# === 24/7 И ВРЕМЯ В ПРОФИЛЕ ===
@dp.callback_query(F.data == "toggle_247")
async def toggle_247(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    new_status = not cfg.get("status_24_7")
    await update_db_config(user_id, {"status_24_7": new_status})
    
    data = get_user_state(user_id)
    data["status_24_7"] = new_status
    if new_status and not data.get("task_24_7"):
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

@dp.callback_query(F.data == "menu_timenick")
async def menu_timenick(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    status_txt = LANG["status_on"] if cfg.get("time_nick_active") else LANG["status_off"]
    
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_turn_off"] if cfg.get("time_nick_active") else LANG["btn_turn_on"], callback_data="toggle_timenick")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(1)
    
    await edit_or_send(user_id, LANG["msg_timenick_text"].format(status_txt, cfg.get("timezone_offset")), reply_markup=builder.as_markup())

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
    elif not new_status and data.get("time_nick_task"):
        data["time_nick_task"].cancel()
        data["time_nick_task"] = None
        
    await menu_timenick(cb)

# === МЕНЮ АДМИНА С ИНФОЙ РЕНДЕРА ===
@dp.callback_query(F.data == "admin_menu")
async def admin_menu(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    cpu = psutil.cpu_percent(interval=0.5)
    ram = psutil.virtual_memory()
    ssd = psutil.disk_usage('/')
    
    text = (
        "💻 **Серверная статистика Render**\n\n"
        f"⚙️ **CPU:** {cpu}%\n"
        f"🧠 **RAM:** {ram.percent}% ({ram.used // 1048576}MB / {ram.total // 1048576}MB)\n"
        f"💽 **SSD:** {ssd.percent}% ({ssd.used // 1048576}MB / {ssd.total // 1048576}MB)\n"
    )
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_refresh"], callback_data="admin_menu")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(1)
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

# === АВТОМАТИЧЕСКИЙ ВОССТАНОВИТЕЛЬ ПРИ РЕСТАРТЕ RENDER ===
async def on_startup():
    print("🚀 Бот запущен. Восстановление активных сессий из Supabase...")
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
