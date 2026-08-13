import asyncio
import re
from aiogram import Router, types, F
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded

from config import get_user_state, is_admin, LANG, API_ID, API_HASH
from database import get_db_config, update_daily_stats, save_db_session, update_db_config, get_db_session
from utils import delayed_delete, edit_or_send, show_main_menu
from userbot import ensure_client_connected

router = Router()

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    # Удаляем сообщение /start через 4 секунды
    asyncio.create_task(delayed_delete(message, 4))
    
    await update_daily_stats('incoming')
    cfg = await get_db_config(user_id, username=message.from_user.username, first_name=message.from_user.first_name)
    
    # ЯВНАЯ ПРОВЕРКА СЕССИИ В SUPABASE
    session_str = await get_db_session(user_id)
    
    if session_str:
        # Если сессия в БД есть, страхуемся и ставим logged_in = True, 
        # чтобы ensure_client_connected не отбросил нас просто так
        if not cfg.get("logged_in"):
            await update_db_config(user_id, {"logged_in": True})
            
        is_connected = await ensure_client_connected(user_id)
        if is_connected:
            if cfg.get("is_menu_locked") and get_user_state(user_id)["state"] == "WAITING_UNLOCK_CODE": 
                return
            # Сессия рабочая, кидаем в Главное меню
            await show_main_menu(user_id, message.from_user.username)
            return

    # Если сессии нет в Supabase или она умерла — кидаем в меню регистрации
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_rules"], callback_data="rules_view")
    builder.button(text=LANG["btn_start"], callback_data="start_login")
    if is_admin(user_id, message.from_user.username):
        builder.button(text=LANG["btn_admin"], callback_data="admin_menu")
    builder.adjust(1)
    await edit_or_send(user_id, LANG["msg_start"], reply_markup=builder.as_markup())

# Ниже в этом же файле нужно заменить все delayed_delete(message, 5) на 4
@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_PHONE")
async def process_phone(message: types.Message):
    user_id = message.from_user.id
    phone = message.text.strip().replace(" ", "")
    asyncio.create_task(delayed_delete(message, 4)) 
    # ... (остальной код функции без изменений)

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_CODE")
async def process_code(message: types.Message):
    user_id = message.from_user.id
    code = re.sub(r'\D', '', message.text.strip())
    asyncio.create_task(delayed_delete(message, 4))
    # ... (остальной код функции без изменений)

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_PASSWORD")
async def process_password(message: types.Message):
    user_id = message.from_user.id
    pwd = message.text.strip()
    asyncio.create_task(delayed_delete(message, 4))
    # ... (остальной код функции без изменений)
