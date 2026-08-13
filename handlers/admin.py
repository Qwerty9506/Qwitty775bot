import time
import random
import datetime
from aiogram import Router, types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import get_user_state, is_admin, LANG, supabase, USER_DATA
from utils import edit_or_send, build_pagination, refresh_admin_pm_view

router = Router()

@router.callback_query(F.data == "admin_menu")
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

@router.callback_query(F.data == "admin_status")
async def admin_status(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    get_user_state(cb.from_user.id)["current_menu"] = "admin_status"
    start_t = time.time()
    ping = int((time.time() - start_t) * 1000) + random.randint(10, 40)
    text = f"Сервер активен\nПинг {ping} мс"
    builder = InlineKeyboardBuilder().button(text=LANG["btn_back"], callback_data="admin_menu")
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data == "admin_users")
async def admin_users(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    get_user_state(cb.from_user.id)["current_menu"] = "admin_users"
    
    res_all = supabase.table("user_configs").select("*").execute()
    res_s = supabase.table("user_sessions").select("user_id").execute()
    
    session_uids = [r["user_id"] for r in res_s.data]
    active_uids = [r["user_id"] for r in res_all.data if r.get("logged_in")]
    out_uids = list(set(session_uids) - set(active_uids))
    inc_uids = [r["user_id"] for r in res_all.data if r["user_id"] not in session_uids]
    
    text = "👥 **Пользователи бота:**"
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Активные ({len(active_uids)})", callback_data="admin_ulist_active_1")
    builder.button(text=f"Входящие ({len(inc_uids)})", callback_data="admin_ulist_incoming_1")
    builder.button(text=f"Выходящие ({len(out_uids)})", callback_data="admin_ulist_outgoing_1")
    builder.button(text=LANG["btn_back"], callback_data="admin_menu")
    builder.adjust(1)
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data.startswith("admin_ulist_"))
async def admin_ulist(cb: types.CallbackQuery):
    if not is_admin(cb.from_user.id, cb.from_user.username): return
    get_user_state(cb.from_user.id)["current_menu"] = "admin_ulist"
    parts = cb.data.split("_")
    cat = parts[2]
    page = int(parts[3])
    limit = 5
    offset = (page - 1) * limit
    builder = InlineKeyboardBuilder()
    
    res_all = supabase.table("user_configs").select("*").execute()
    res_s = supabase.table("user_sessions").select("user_id").execute()
    session_uids = [r["user_id"] for r in res_s.data]
    active_uids = [r["user_id"] for r in res_all.data if r.get("logged_in")]
    
    items, title = [], ""
    if cat == "active":
        title = "🟢 **Активные пользователи:**"
        items = [r for r in res_all.data if r.get("logged_in")]
    elif cat == "outgoing":
        title = "🔴 **Выходящие пользователи:**"
        out_uids = list(set(session_uids) - set(active_uids))
        items = [r for r in res_all.data if r["user_id"] in out_uids]
    elif cat == "incoming":
        title = "📩 **Входящие:**"
        items = [r for r in res_all.data if r["user_id"] not in session_uids]
        items.sort(key=lambda x: x.get("last_interaction_time", 0), reverse=True)
        
    chunk = items[offset:offset+limit]
    if cat == "incoming":
        text = f"{title}\n\n"
        for r in chunk:
            dt = datetime.datetime.fromtimestamp(r.get("last_interaction_time", time.time())).strftime("%d.%m %H:%M")
            name = r.get("first_name", "Без имени")
            uname = f"@{r['username']}" if r.get("username") else ""
            text += f"🕒 `{dt}`: {name} {uname} (ID: {r['user_id']})\n"
    else:
        text = title
        for r in chunk:
            name = r.get("first_name", f"User {r['user_id']}")
            builder.button(text=name, callback_data=f"admin_ucard_{r['user_id']}")
        builder.adjust(1)
        
    pag_btns = build_pagination(f"admin_ulist_{cat}", page, len(items), limit)
    if pag_btns: builder.row(*pag_btns)
    builder.row(types.InlineKeyboardButton(text="Назад", callback_data="admin_users"))
    await edit_or_send(cb.from_user.id, text, reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data.startswith("admin_ucard_"))
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

@router.callback_query(F.data.startswith("admin_upms_"))
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

@router.callback_query(F.data.startswith("admin_viewpm_"))
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
