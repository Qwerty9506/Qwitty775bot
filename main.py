import asyncio
import os
import re
import random
import string
from dotenv import load_dotenv

from supabase import create_client, Client as SupabaseClient
from aiogram import Bot, Dispatcher, types, F, BaseMiddleware
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Локализация
LANG_DICT = {
    "RU": {
        "welcome": "Добро пожаловать в Qwitty registrator bot",
        "btn_start": "Начать",
        "btn_back": "Назад",
        "phone_req": "Для входа в Qwitty user bot введите номер, например +79991234567.",
        "code_req": "На номер {phone} отправлен код, вводите код с пробелами! Например 12 3 45.",
        "code_err": "Код введен неверно, пожалуйста, введите заново.",
        "success": "Аккаунт Qwitty User bot подключен!\n\nВаш ID код: `{qwitty_id}`\nНикому не передавайте ID код, ваша безопасность важна для нас!"
    },
    "ENG": {
        "welcome": "Welcome to Qwitty registrator bot",
        "btn_start": "Start",
        "btn_back": "Back",
        "phone_req": "To log into Qwitty user bot, enter your number, e.g., +1234567890.",
        "code_req": "Code sent to {phone}, please write the code with spaces! E.g., 12 3 45.",
        "code_err": "Invalid code, please enter again.",
        "success": "Qwitty User bot account connected!\n\nYour ID code: `{qwitty_id}`\nDo not share your ID code with anyone, your safety is important to us!"
    },
    "UZB": {
        "welcome": "Qwitty registrator botga xush kelibsiz",
        "btn_start": "Boshlash",
        "btn_back": "Orqaga",
        "phone_req": "Qwitty user bot kiritish uchun nomer yozing, masalan +998991234567.",
        "code_req": "{phone} ga kod yuborildi, kod bo'sh o'rinlar bilan yozilsin! Masalan 12 3 45.",
        "code_err": "Kod xato yozilgan, iltimos qaytadan kiriting.",
        "success": "Qwitty User bot akkauntga ulandi!\n\nSizning ID kodingiz: `{qwitty_id}`\nID kodni hech kimga bermang, sizning xavfsizligingiz biz uchun muhim!"
    },
    "KZ": {
        "welcome": "Qwitty тіркеу ботына қош келдіңіз",
        "btn_start": "Бастау",
        "btn_back": "Артқа",
        "phone_req": "Qwitty user bot-қа кіру үшін нөміріңізді жазыңыз, мысалы +77011234567.",
        "code_req": "{phone} нөміріне код жіберілді, кодты бос орындармен жазыңыз! Мысалы 12 3 45.",
        "code_err": "Код қате жазылған, қайта енгізіңіз.",
        "success": "Qwitty User bot аккаунты қосылды!\n\nСіздің ID кодыңыз: `{qwitty_id}`\nID кодты ешкімге бермеңіз, сіздің қауіпсіздігіңіз біз үшін маңызды!"
    }
}

# Хранилище состояний пользователей
USER_DATA = {}

def get_user_state(user_id):
    if user_id not in USER_DATA:
        USER_DATA[user_id] = {
            "msg_id": None, "state": "START", "lang": "RU", 
            "phone": None, "phone_code_hash": None, "client": None
        }
    return USER_DATA[user_id]

# Утилиты БД
def get_user_db(user_id):
    res = supabase.table("qwitty_users").select("*").eq("user_id", user_id).execute()
    return res.data[0] if res.data else None

def generate_qwitty_id():
    chars = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"Qwt-{chars}"

def save_user_db(user_id, lang, phone, session_string, qwitty_id):
    supabase.table("qwitty_users").upsert({
        "user_id": user_id,
        "qwitty_id": qwitty_id,
        "lang": lang,
        "phone": phone,
        "session_string": session_string
    }).execute()

# Редактор сообщений
async def edit_or_send(user_id, text, reply_markup=None, parse_mode="Markdown"):
    data = get_user_state(user_id)
    if data["msg_id"]:
        try:
            await bot.edit_message_text(chat_id=user_id, message_id=data["msg_id"], text=text, reply_markup=reply_markup, parse_mode=parse_mode)
            return
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower(): return
            data["msg_id"] = None
        except Exception:
            data["msg_id"] = None
            
    msg = await bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    data["msg_id"] = msg.message_id

# Мидлварь для удаления сообщений (и задержка 3 сек для /start)
async def delayed_delete(message: types.Message, delay: int):
    if delay > 0:
        await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass

class DeleteMessageMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, types.Message):
            if event.text == "/start":
                asyncio.create_task(delayed_delete(event, 3))
            else:
                asyncio.create_task(delayed_delete(event, 0))
        return await handler(event, data)

dp.update.middleware(DeleteMessageMiddleware())

# Обработчик /start
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    db_user = get_user_db(user_id)
    
    if db_user:
        # Сессия уже есть, показываем главное меню (успех)
        lang = db_user["lang"]
        qwitty_id = db_user["qwitty_id"]
        text = LANG_DICT[lang]["success"].format(qwitty_id=qwitty_id)
        get_user_state(user_id)["state"] = "REGISTERED"
        await edit_or_send(user_id, text)
    else:
        # Сессии нет, показываем выбор языка
        get_user_state(user_id)["state"] = "SELECT_LANG"
        builder = InlineKeyboardBuilder()
        builder.button(text="🇷🇺 RU", callback_data="lang_RU")
        builder.button(text="🇬🇧 ENG", callback_data="lang_ENG")
        builder.button(text="🇺🇿 UZB", callback_data="lang_UZB")
        builder.button(text="🇰🇿 KZ", callback_data="lang_KZ")
        builder.adjust(2, 2)
        
        await edit_or_send(user_id, "Выберите язык / Choose language / Tilni tanlang / Тілді таңдаңыз:", reply_markup=builder.as_markup())

# Выбор языка
@dp.callback_query(F.data.startswith("lang_"))
async def select_language(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    lang = cb.data.split("_")[1]
    
    data = get_user_state(user_id)
    data["lang"] = lang
    data["state"] = "START_AUTH"
    
    await show_welcome_menu(user_id)

async def show_welcome_menu(user_id):
    data = get_user_state(user_id)
    lang = data["lang"]
    
    builder = InlineKeyboardBuilder()
    builder.button(text=LANG_DICT[lang]["btn_start"], callback_data="auth_start")
    builder.button(text=LANG_DICT[lang]["btn_back"], callback_data="back_to_lang")
    builder.adjust(1)
    
    await edit_or_send(user_id, LANG_DICT[lang]["welcome"], reply_markup=builder.as_markup())

@dp.callback_query(F.data == "back_to_lang")
async def back_to_lang(cb: types.CallbackQuery):
    # Возврат к выбору языка, имитируем новый старт
    class MockMessage:
        def __init__(self, user_id):
            self.from_user = type("User", (), {"id": user_id})()
    await cmd_start(MockMessage(cb.from_user.id))

@dp.callback_query(F.data == "auth_start")
async def auth_start(cb: types.CallbackQuery):
    user_id = cb.from_user.id
    data = get_user_state(user_id)
    lang = data["lang"]
    data["state"] = "WAITING_PHONE"
    
    builder = InlineKeyboardBuilder().button(text=LANG_DICT[lang]["btn_back"], callback_data="cancel_auth")
    await edit_or_send(user_id, LANG_DICT[lang]["phone_req"], reply_markup=builder.as_markup())

@dp.callback_query(F.data == "cancel_auth")
async def cancel_auth(cb: types.CallbackQuery):
    data = get_user_state(cb.from_user.id)
    if data["client"]:
        try: await data["client"].disconnect()
        except: pass
        data["client"] = None
    await show_welcome_menu(cb.from_user.id)

# Ожидание номера
@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_PHONE")
async def process_phone(message: types.Message):
    user_id = message.from_user.id
    data = get_user_state(user_id)
    lang = data["lang"]
    
    phone = message.text.strip().replace(" ", "")
    if not phone.startswith("+"): phone = "+" + phone
    phone = re.sub(r'[^\d+]', '', phone)
    
    data["phone"] = phone
    
    # Создаем in-memory клиент Pyrogram
    client = Client(f"qwitty_{user_id}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
    data["client"] = client
    
    try:
        await client.connect()
        code_info = await client.send_code(phone)
        data["phone_code_hash"] = code_info.phone_code_hash
        data["state"] = "WAITING_CODE"
        
        masked_phone = phone[:6] + "*****"
        text = LANG_DICT[lang]["code_req"].format(phone=masked_phone)
        builder = InlineKeyboardBuilder().button(text=LANG_DICT[lang]["btn_back"], callback_data="cancel_auth")
        
        await edit_or_send(user_id, text, reply_markup=builder.as_markup())
    except Exception as e:
        await edit_or_send(user_id, f"Ошибка / Xato: {e}")

# Ожидание кода
@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_CODE")
async def process_code(message: types.Message):
    user_id = message.from_user.id
    data = get_user_state(user_id)
    lang = data["lang"]
    client = data["client"]
    
    if not client: return
    
    # Убираем пробелы, так как пользователи пишут "12 3 45"
    code = message.text.replace(" ", "")
    
    try:
        await client.sign_in(data["phone"], data["phone_code_hash"], code)
        await finalize_auth(user_id, client)
    except (PhoneCodeInvalid, PhoneCodeExpired):
        builder = InlineKeyboardBuilder().button(text=LANG_DICT[lang]["btn_back"], callback_data="cancel_auth")
        await edit_or_send(user_id, LANG_DICT[lang]["code_err"], reply_markup=builder.as_markup())
    except SessionPasswordNeeded:
        data["state"] = "WAITING_PASSWORD"
        builder = InlineKeyboardBuilder().button(text=LANG_DICT[lang]["btn_back"], callback_data="cancel_auth")
        await edit_or_send(user_id, "Аккаунт защищен 2FA паролем. Введите его в чат:", reply_markup=builder.as_markup())
    except Exception as e:
        await edit_or_send(user_id, f"Ошибка / Xato: {e}")

# Ожидание 2FA пароля
@dp.message(lambda msg: get_user_state(msg.from_user.id)["state"] == "WAITING_PASSWORD")
async def process_password(message: types.Message):
    user_id = message.from_user.id
    data = get_user_state(user_id)
    client = data["client"]
    pwd = message.text.strip()
    
    try:
        await client.check_password(pwd)
        await finalize_auth(user_id, client)
    except Exception:
        lang = data["lang"]
        builder = InlineKeyboardBuilder().button(text=LANG_DICT[lang]["btn_back"], callback_data="cancel_auth")
        await edit_or_send(user_id, "❌ Неверный пароль / Noto'g'ri parol!", reply_markup=builder.as_markup())

async def finalize_auth(user_id, client):
    data = get_user_state(user_id)
    lang = data["lang"]
    
    session_string = await client.export_session_string()
    qwitty_id = generate_qwitty_id()
    
    save_user_db(
        user_id=user_id, 
        lang=lang, 
        phone=data["phone"], 
        session_string=session_string, 
        qwitty_id=qwitty_id
    )
    
    data["state"] = "REGISTERED"
    try: await client.disconnect()
    except: pass
    data["client"] = None
    
    text = LANG_DICT[lang]["success"].format(qwitty_id=qwitty_id)
    await edit_or_send(user_id, text)


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
