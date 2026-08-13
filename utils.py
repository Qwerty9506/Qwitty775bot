import asyncio
import re
import datetime
from aiogram import types
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from config import bot, get_user_state, is_admin, LANG, supabase

async def delayed_delete(message: types.Message, delay: int):
    if delay > 0:
        await asyncio.sleep(delay)
    try:
        await message.delete()
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
            try: await bot.delete_message(chat_id=user_id, message_id=data["msg_id"])
            except Exception: pass
    
    msg = await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    data["msg_id"] = msg.message_id

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

def strip_time_nick(name):
    name = re.sub(r'\s*(\[.*?\]|⌚.*|⏳.*|★.*|[\d𝟎-𝟗𝟘-𝟡𝟢-𝟫𝟶-𝟿]+[:∶][\d𝟎-𝟗𝟘-𝟡𝟢-𝟫𝟶-𝟿]+)$', '', name)
    name = name.replace("꧁ ", "").replace(" ꧂", "").replace("★ ", "")
    return name.strip()

def apply_custom_nick(base_name, time_str, style_idx):
    bold = str.maketrans("0123456789", "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗")
    double = str.maketrans("0123456789", "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡")
    sans = str.maketrans("0123456789", "𝟢𝟣𝟤𝟥𝟦𝟧𝟨𝟩𝟪𝟫")
    mono = str.maketrans("0123456789", "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿")
    
    if style_idx == 1: return f"{base_name} [{time_str}]"
    if style_idx == 2: return f"{base_name} {time_str.translate(bold)}"
    if style_idx == 3: return f"{base_name} {time_str.translate(double)}"
    if style_idx == 4: return f"{base_name} {time_str.translate(sans)}"
    if style_idx == 5: return f"{base_name} {time_str.translate(mono)}"
    return f"{base_name} [{time_str}]"

async def refresh_admin_pm_view(admin_id, uid, cid, page):
    limit = 5
    offset = (page - 1) * limit
    
    res = supabase.table("messages_log").select("*").eq("user_id", uid).eq("chat_id", cid).order("date", desc=True).range(offset, offset+limit-1).execute()
    res_count = supabase.table("messages_log").select("id", count="exact").eq("user_id", uid).eq("chat_id", cid).execute()
    
    msgs = res.data[::-1]
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
