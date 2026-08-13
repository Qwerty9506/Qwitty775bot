import datetime
import time
from config import supabase, LANG, get_user_state

async def get_db_config(user_id, username=None, first_name=None):
    res = supabase.table("user_configs").select("*").eq("user_id", user_id).execute()
    if not res.data:
        default = {
            "user_id": user_id, "status_24_7": False, "time_nick_active": False, 
            "autoresponder_active": False, "autoresponder_greeting": LANG["msg_autoresp_default"],
            "timezone_offset": 5, "replied_users": [], "is_menu_locked": False, 
            "menu_lock_code": None, "logged_in": False, "last_interaction_time": time.time(),
            "custom_nick_style": 1, "timezone_name": "Ташкент / UTC+5"
        }
        try:
            default["username"] = username or ""
            default["first_name"] = first_name or "Без имени"
            supabase.table("user_configs").insert(default).execute()
        except Exception: 
            pass
        return default
    else:
        if username is not None or first_name is not None:
            updates = {}
            if username is not None: updates["username"] = username
            if first_name is not None: updates["first_name"] = first_name
            try: supabase.table("user_configs").update(updates).eq("user_id", user_id).execute()
            except Exception: pass
        return res.data[0]

async def update_db_config(user_id, updates):
    supabase.table("user_configs").update(updates).eq("user_id", user_id).execute()
    if "is_menu_locked" in updates:
        get_user_state(user_id)["is_menu_locked"] = updates["is_menu_locked"]
    if "last_interaction_time" in updates:
        get_user_state(user_id)["last_interaction_time"] = updates["last_interaction_time"]

async def get_db_session(user_id):
    res = supabase.table("user_sessions").select("session_string").eq("user_id", user_id).execute()
    return res.data[0]["session_string"] if res.data else None

async def save_db_session(user_id, session_string, phone):
    res = supabase.table("user_sessions").select("user_id").eq("user_id", user_id).execute()
    if res.data:
        supabase.table("user_sessions").update({"session_string": session_string, "phone": phone}).eq("user_id", user_id).execute()
    else:
        supabase.table("user_sessions").insert({"user_id": user_id, "session_string": session_string, "phone": phone}).execute()

async def drop_db_session(user_id):
    supabase.table("user_sessions").delete().eq("user_id", user_id).execute()
    await update_db_config(user_id, {"logged_in": False})

async def update_daily_stats(stat_type):
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    res = supabase.table("daily_stats").select("*").eq("date", today).execute()
    if res.data:
        val = res.data[0][stat_type] + 1
        supabase.table("daily_stats").update({stat_type: val}).eq("date", today).execute()
    else:
        supabase.table("daily_stats").insert({
            "date": today, 
            "incoming": 1 if stat_type=='incoming' else 0, 
            "active": 1 if stat_type=='active' else 0
        }).execute()
