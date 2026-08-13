import asyncio
import re
from aiogram import Router, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PasswordHashInvalid

from config import get_user_state, is_admin, LANG, API_ID, API_HASH
from database import get_db_config, update_daily_stats, save_db_session, update_db_config, get_db_session
from utils import delayed_delete, edit_or_send, show_main_menu
from userbot import ensure_client_connected

router = Router()

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    asyncio.create_task(delayed_delete(message, 4))
    
    await update_daily_stats('incoming')
    cfg = await get_db_config(user_id, username=message.from_user.username, first_name=message.from_user.first_name)
    
    session_str = await get_db_session(user_id)
    if session_str:
        if not cfg.get("logged_in"):
            await update_db_config(user_id, {"logged_in": True})
            
        is_connected = await ensure_client_connected(user_id)
        if is_connected:
            if cfg.get("is_menu_locked") and get_user_state(user_id)["state"] == "WAITING_UNLOCK_CODE": 
                return
            await show_main_menu(user_id, message.from_user.username)
            return

    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_rules"], callback_data="rules_view")
    builder.button(text=LANG["btn_start"], callback_data="start_login")
    if is_admin(user_id, message.from_user.username):
        builder.button(text=LANG["btn_admin"], callback_data="admin_menu")
    builder.adjust(1)
    await edit_or_send(user_id, LANG["msg_start"], reply_markup=builder.as_markup())

@router.callback_query(F.data == "start_login")
async def start_login(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    get_user_state(user_id)["state"] = "WAITING_PHONE"
    await edit_or_send(user_id, LANG["msg_phone_req"])

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_PHONE")
async def process_phone(message: types.Message):
    user_id = message.from_user.id
    phone = message.text.strip().replace(" ", "")
    asyncio.create_task(delayed_delete(message, 4))
    
    data = get_user_state(user_id)
    data["phone"] = phone
    client = Client(f"session_{user_id}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
    await client.connect()
    
    try:
        sent_code = await client.send_code(phone)
        data["client"] = client
        data["phone_code_hash"] = sent_code.phone_code_hash
        data["state"] = "WAITING_CODE"
        await edit_or_send(user_id, LANG["msg_code_req"])
    except Exception as e:
        await client.disconnect()
        await edit_or_send(user_id, f"❌ Ошибка отправки кода: {e}")

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_CODE")
async def process_code(message: types.Message):
    user_id = message.from_user.id
    code = re.sub(r'\D', '', message.text.strip())
    asyncio.create_task(delayed_delete(message, 4))
    
    data = get_user_state(user_id)
    client: Client = data.get("client")
    if not client:
        await edit_or_send(user_id, "⚠️ Сессия не найдена. Попробуйте сначала.")
        return

    try:
        await client.sign_in(phone_number=data["phone"], phone_code_hash=data["phone_code_hash"], phone_code=code)
        session_str = await client.export_session_string()
        await save_db_session(user_id, session_str, data["phone"])
        await update_db_config(user_id, {"logged_in": True})
        
        data["state"] = "LOGGED_IN"
        await ensure_client_connected(user_id)
        await show_main_menu(user_id, message.from_user.username)
    except SessionPasswordNeeded:
        data["state"] = "WAITING_PASSWORD"
        await edit_or_send(user_id, LANG["msg_pwd_req"])
    except PhoneCodeInvalid:
        await edit_or_send(user_id, "❌ Неверный код из Telegram. Попробуйте ещё раз:")
    except Exception as e:
        await edit_or_send(user_id, f"❌ Ошибка авторизации: {e}")

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_PASSWORD")
async def process_password(message: types.Message):
    user_id = message.from_user.id
    pwd = message.text.strip()
    asyncio.create_task(delayed_delete(message, 4))
    
    data = get_user_state(user_id)
    client: Client = data.get("client")
    if not client:
        await edit_or_send(user_id, "⚠️ Сессия не найдена. Попробуйте заново.")
        return

    try:
        await client.check_password(pwd)
        session_str = await client.export_session_string()
        await save_db_session(user_id, session_str, data["phone"])
        await update_db_config(user_id, {"logged_in": True})
        
        data["state"] = "LOGGED_IN"
        await ensure_client_connected(user_id)
        await show_main_menu(user_id, message.from_user.username)
    except PasswordHashInvalid:
        await edit_or_send(user_id, "❌ Неверный облачный пароль. Введите еще раз:")
    except Exception as e:
        await edit_or_send(user_id, f"❌ Ошибка 2FA: {e}")
