import asyncio
import re
from aiogram import Router, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded

from config import get_user_state, is_admin, LANG, API_ID, API_HASH
from database import get_db_config, update_daily_stats, save_db_session, update_db_config
from utils import delayed_delete, edit_or_send, show_main_menu
from userbot import ensure_client_connected

router = Router()

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    asyncio.create_task(delayed_delete(message, 5))
    
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

@router.callback_query(F.data == "rules_view")
async def rules_view(cb: types.CallbackQuery):
    builder = InlineKeyboardBuilder().button(text="Я ознакомился 👍", callback_data="rules_accepted")
    await edit_or_send(cb.from_user.id, LANG["msg_rules_text"], reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data == "rules_accepted")
async def rules_accepted(cb: types.CallbackQuery):
    await show_main_menu(cb.from_user.id, cb.from_user.username) if await ensure_client_connected(cb.from_user.id) else await cmd_start(cb.message)

@router.callback_query(F.data == "start_login")
async def start_login(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    if await ensure_client_connected(user_id):
        await show_main_menu(user_id, cb.from_user.username)
        return
    get_user_state(user_id)["state"] = "WAITING_PHONE"
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back"], callback_data="cancel_auth")
    await edit_or_send(user_id, LANG["msg_phone_req"], reply_markup=builder.as_markup())

@router.callback_query(F.data == "cancel_auth")
async def cancel_auth(cb: types.CallbackQuery):
    data = get_user_state(cb.from_user.id)
    data["state"] = "START"
    if data["client"]:
        try: await data["client"].disconnect()
        except: pass
        data["client"] = None
    await cmd_start(cb.message)

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_PHONE")
async def process_phone(message: types.Message):
    user_id = message.from_user.id
    phone = message.text.strip().replace(" ", "")
    asyncio.create_task(delayed_delete(message, 5))
    
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

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_CODE")
async def process_code(message: types.Message):
    user_id = message.from_user.id
    code = re.sub(r'\D', '', message.text.strip())
    asyncio.create_task(delayed_delete(message, 5))
    
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

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_PASSWORD")
async def process_password(message: types.Message):
    user_id = message.from_user.id
    pwd = message.text.strip()
    asyncio.create_task(delayed_delete(message, 5))
    
    client = get_user_state(user_id)["client"]
    try:
        await client.check_password(pwd)
        await finish_login(user_id, client)
    except Exception:
        msg_err = await message.answer("❌ Неверный пароль!")
        await asyncio.sleep(3)
        try: await msg_err.delete()
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
