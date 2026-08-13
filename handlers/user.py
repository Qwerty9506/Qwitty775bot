import asyncio
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import get_user_state, LANG
from database import get_db_config, update_db_config
from utils import delayed_delete, edit_or_send, show_main_menu

router = Router()

@router.callback_query(F.data == "main_menu")
async def back_to_main(cb: types.CallbackQuery):
    await show_main_menu(cb.from_user.id, cb.from_user.username)

@router.callback_query(F.data == "menu_autoresponder")
async def menu_autoresponder(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    active = cfg.get("autoresponder_active", False)
    status = LANG["status_on"] if active else LANG["status_off"]
    
    text = f"🤖 **Автоответчик**\nТекущий статус: {status}\n\nПриветственный текст:\n_{cfg.get('autoresponder_greeting', LANG['msg_autoresp_default'])}_"
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_turn_off"] if active else LANG["btn_turn_on"], callback_data="toggle_autoresp")
    builder.button(text=LANG["btn_autoresp_setup"], callback_data="setup_autoresp")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(1)
    await edit_or_send(user_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data == "toggle_autoresp")
async def toggle_autoresp(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    new_val = not cfg.get("autoresponder_active", False)
    await update_db_config(user_id, {"autoresponder_active": new_val})
    await menu_autoresponder(cb)

@router.callback_query(F.data == "setup_autoresp")
async def setup_autoresp(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    get_user_state(user_id)["state"] = "WAITING_AUTORESP_TEXT"
    await edit_or_send(user_id, "📝 Введите новый текст приветствия для автоответчика:")

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_AUTORESP_TEXT")
async def process_autoresp_text(message: types.Message):
    user_id = message.from_user.id
    asyncio.create_task(delayed_delete(message, 4))
    
    new_text = message.text.strip()
    await update_db_config(user_id, {"autoresponder_greeting": new_text})
    get_user_state(user_id)["state"] = "MENU"
    await show_main_menu(user_id, message.from_user.username)

@router.callback_query(F.data == "menu_block_settings")
async def menu_block_settings(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    locked = cfg.get("is_menu_locked", False)
    
    text = f"🔒 **Блокировка меню**\nСтатус: {LANG['status_on'] if locked else LANG['status_off']}"
    builder = InlineKeyboardBuilder()
    if locked:
        builder.button(text="Снять блокировку", callback_data="disable_pin")
    else:
        builder.button(text="Установить PIN-код", callback_data="setup_pin")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(1)
    await edit_or_send(user_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data == "setup_pin")
async def setup_pin(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    get_user_state(user_id)["state"] = "WAITING_SET_PIN"
    await edit_or_send(user_id, LANG["msg_block_setup"])

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_SET_PIN")
async def process_set_pin(message: types.Message):
    user_id = message.from_user.id
    code = message.text.strip()
    asyncio.create_task(delayed_delete(message, 4))
    
    if len(code) == 4 and code.isdigit():
        await update_db_config(user_id, {"is_menu_locked": True, "menu_lock_code": code})
        get_user_state(user_id)["is_menu_locked"] = True
        get_user_state(user_id)["state"] = "MENU"
        await edit_or_send(user_id, "✅ PIN-код успешно установлен!")
        await asyncio.sleep(1)
        await show_main_menu(user_id, message.from_user.username)
    else:
        await edit_or_send(user_id, "❌ Код должен состоять ровно из 4 цифр! Введите заново:")

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_UNLOCK_CODE")
async def process_unlock_code(message: types.Message):
    user_id = message.from_user.id
    code = message.text.strip()
    asyncio.create_task(delayed_delete(message, 4))
    
    cfg = await get_db_config(user_id)
    if code == cfg.get("menu_lock_code"):
        get_user_state(user_id)["state"] = "MENU"
        await show_main_menu(user_id, message.from_user.username)
    else:
        await edit_or_send(user_id, "❌ Неверный PIN-код. Введите еще раз:")

@router.callback_query(F.data == "disable_pin")
async def disable_pin(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    await update_db_config(user_id, {"is_menu_locked": False, "menu_lock_code": None})
    get_user_state(user_id)["is_menu_locked"] = False
    await menu_block_settings(cb)
