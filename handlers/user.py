import asyncio
import time
import datetime
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder
from pyrogram.raw import functions

from config import bot, get_user_state, LANG, ZONES, supabase
from database import get_db_config, update_db_config
from utils import delayed_delete, edit_or_send, strip_time_nick, apply_custom_nick, show_main_menu
from userbot import time_nickname_loop, keep_online_loop

router = Router()

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(cb: types.CallbackQuery):
    await show_main_menu(cb.from_user.id, cb.from_user.username)

@router.callback_query(F.data == "menu_profile_settings")
async def menu_profile_settings(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_time"], callback_data="menu_timenick")
    builder.button(text=LANG["btn_custom_nick"], callback_data="menu_custom_nick")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(2, 1)
    await edit_or_send(user_id, "⚙️ **Настройки профиля**\nВыберите, что хотите настроить:", reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data == "menu_timenick")
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

@router.callback_query(F.data == "toggle_timenick")
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

@router.callback_query(F.data == "select_tz")
async def select_tz(cb: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for i, (name, offset) in enumerate(ZONES):
        builder.button(text=name, callback_data=f"tz_prev_{i}")
    builder.button(text=LANG["btn_back"], callback_data="menu_timenick")
    builder.adjust(2, 2, 2, 1)
    await edit_or_send(cb.from_user.id, "🌍 Выберите ваш часовой пояс:", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("tz_prev_"))
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

@router.callback_query(F.data.startswith("tz_save_"))
async def tz_save(cb: types.CallbackQuery):
    idx = int(cb.data.split("_")[2])
    name, offset = ZONES[idx]
    await update_db_config(cb.from_user.id, {"timezone_offset": offset, "timezone_name": name})
    await menu_timenick(cb)

@router.callback_query(F.data == "menu_custom_nick")
async def menu_custom_nick(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    builder = InlineKeyboardBuilder()
    styles = [
        ("Стиль [10:30]", 1), ("Стиль 𝟏𝟎:𝟑𝟎", 2),
        ("Стиль 𝟙𝟘:𝟛𝟘", 3), ("Стиль 𝟢𝟣:𝟤𝟥", 4), ("Стиль 𝟶𝟷:𝟸𝟹", 5)
    ]
    for s_name, idx in styles:
        builder.button(text=s_name, callback_data=f"preview_nick_{idx}")
    builder.button(text=LANG["btn_back"], callback_data="menu_profile_settings")
    builder.adjust(1)
    
    text = f"✨ **Кастомизация никнейма**\n\nВыберите вариант оформления шрифта ниже:"
    await edit_or_send(user_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data.startswith("preview_nick_"))
async def preview_nick(cb: types.CallbackQuery):
    style_idx = int(cb.data.split("_")[2])
    user_id = cb.from_user.id
    
    cfg = await get_db_config(user_id)
    offset = float(cfg.get("timezone_offset", 5))
    tz_now = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=offset)
    time_str = tz_now.strftime('%H:%M')
    
    client = get_user_state(user_id)["client"]
    base_name = "Имя"
    if client and client.is_connected:
        me = await client.get_me()
        base_name = strip_time_nick(me.first_name or "Имя")
    
    demo_name = apply_custom_nick(base_name, time_str, style_idx)
    text = f"Ваш ник выглядит примерно так:\n`{demo_name}`"
    
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG["btn_confirm"], callback_data=f"confirm_nick_{style_idx}")
    builder.button(text=LANG["btn_back"], callback_data="menu_custom_nick")
    builder.adjust(1)
    
    await edit_or_send(user_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data.startswith("confirm_nick_"))
async def confirm_nick(cb: types.CallbackQuery):
    style_idx = int(cb.data.split("_")[2])
    user_id = cb.from_user.id
    await update_db_config(user_id, {"custom_nick_style": style_idx})
    await menu_custom_nick(cb)

@router.callback_query(F.data == "menu_activity")
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

@router.callback_query(F.data == "menu_autoresponder")
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

@router.callback_query(F.data == "toggle_autoresponder")
async def toggle_autoresponder(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    await update_db_config(user_id, {"autoresponder_active": not cfg.get("autoresponder_active")})
    await menu_autoresponder(cb)

@router.callback_query(F.data == "setup_autoresp_text")
async def setup_autoresp_text(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    get_user_state(user_id)["state"] = "WAITING_AUTORESP_TEXT"
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back"], callback_data="menu_autoresponder")
    await edit_or_send(user_id, "📝 Напишите новый текст автоответчика в чат:", reply_markup=builder.as_markup())

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_AUTORESP_TEXT")
async def process_autoresp_text(message: types.Message):
    user_id = message.from_user.id
    asyncio.create_task(delayed_delete(message, 0))
    await update_db_config(user_id, {"autoresponder_greeting": message.text.strip()})
    get_user_state(user_id)["state"] = "MENU"
    
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back"], callback_data="menu_autoresponder")
    await edit_or_send(user_id, "✅ Текст автоответчика успешно сохранен!", reply_markup=builder.as_markup())

@router.callback_query(F.data == "menu_delete")
async def menu_delete(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    builder = InlineKeyboardBuilder()
    for count in [10, 25, 50, 100]:
        builder.button(text=f"🗑 {count}", callback_data=f"confirm_purge_{count}")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(2, 2, 1)
    await edit_or_send(user_id, LANG["msg_del_text"], reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data.startswith("confirm_purge_"))
async def confirm_purge(cb: types.CallbackQuery):
    count = int(cb.data.split("_")[2])
    builder = InlineKeyboardBuilder()
    builder.button(text="Да", callback_data=f"dopurge_{count}")
    builder.button(text="Нет / Назад", callback_data="menu_delete")
    builder.adjust(2)
    await edit_or_send(cb.from_user.id, f"⚠️ Вы точно хотите удалить последние {count} сообщений?", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("dopurge_"))
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

@router.callback_query(F.data == "menu_block_settings")
async def menu_block_settings(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    cfg = await get_db_config(user_id)
    locked = cfg.get("is_menu_locked", False)
    status_txt = "Заблокировано 🔒" if locked else "Разблокировано 🔓"
    
    text = f"🔒 **Блокировка меню**\n\nТекущий статус: {status_txt}"
    builder = InlineKeyboardBuilder()
    if locked:
        builder.button(text="Снять PIN-код 🔓", callback_data="unlock_pin_setup")
        builder.button(text="🔒 Заблокировать", callback_data="manual_lock")
    else:
        builder.button(text="Установить PIN-код 🔒", callback_data="set_pin_setup")
    builder.button(text=LANG["btn_back_menu"], callback_data="main_menu")
    builder.adjust(1)
    await edit_or_send(user_id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data == "set_pin_setup")
async def set_pin_setup(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    get_user_state(user_id)["state"] = "WAITING_SET_PIN"
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back"], callback_data="menu_block_settings")
    await edit_or_send(user_id, "🔒 Отправьте 4 цифры PIN-кода:", reply_markup=builder.as_markup())

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_SET_PIN")
async def process_set_pin(message: types.Message):
    user_id = message.from_user.id
    code = message.text.strip()
    asyncio.create_task(delayed_delete(message, 5))
    
    if not code.isdigit() or len(code) != 4:
        msg_err = await message.answer("❌ PIN-код должен состоять ровно из 4 цифр!")
        await asyncio.sleep(3)
        try: await msg_err.delete()
        except: pass
        return
        
    await update_db_config(user_id, {"is_menu_locked": True, "menu_lock_code": code, "last_interaction_time": time.time()})
    get_user_state(user_id)["state"] = "MENU"
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back_menu"], callback_data="main_menu")
    await edit_or_send(user_id, "✅ PIN-код установлен! Теперь при долгом простое меню блокируется.", reply_markup=builder.as_markup())

@router.callback_query(F.data == "unlock_pin_setup")
async def unlock_pin_setup(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    await update_db_config(user_id, {"is_menu_locked": False, "menu_lock_code": None})
    await menu_block_settings(cb)

@router.callback_query(F.data == "manual_lock")
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
        await cb.answer("❌ PIN-код не установлен.", show_alert=True)

@router.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_UNLOCK_CODE")
async def process_unlock_code(message: types.Message):
    user_id = message.from_user.id
    code = message.text.strip()
    asyncio.create_task(delayed_delete(message, 5))
    
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
        msg_err = await message.answer("❌ Неверный PIN-код!")
        await asyncio.sleep(3)
        try: await msg_err.delete()
        except: pass

@router.callback_query(F.data == "toggle_247")
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
