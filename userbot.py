import asyncio
import time
import datetime
from pyrogram import Client, enums, filters
from pyrogram.handlers import MessageHandler, DeletedMessagesHandler
from pyrogram.raw import functions
from pyrogram.errors import Unauthorized
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import get_user_state, API_ID, API_HASH, LANG, supabase, USER_DATA
from database import get_db_config, update_db_config, get_db_session, drop_db_session
from utils import edit_or_send, strip_time_nick, apply_custom_nick, refresh_admin_pm_view

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
        except Exception:
            await handle_revoked_session(user_id)
            return False
    return False
