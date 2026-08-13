import os
import asyncio
import secrets
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.exceptions import TelegramBadRequest
from pyrogram import Client
from pyrogram.errors import PhoneCodeInvalid, PhoneCodeExpired, SessionPasswordNeeded
from supabase import create_client, Client as SupabaseClient

# --- Конфигурация ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "ТВОЙ_ТОКЕН")
API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "ТВОЙ_ХЭШ")
SUPABASE_URL = os.getenv("SUPABASE_URL", "ТВОЙ_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "ТВОЙ_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

supabase: SupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)

# Временное хранилище MTProto клиентов для авторизации (tg_id -> client)
auth_clients = {}

# --- FSM Состояния ---
class AuthState(StatesGroup):
    lang = State()
    phone = State()
    code = State()

# --- Словари языков ---
TEXTS = {
    "ru": {
        "welcome": "Добро пожаловать в Qwitty registrator bot",
        "btn_start": "Начать",
        "btn_back": "Назад",
        "enter_phone": "Введите номер для входа в Qwitty user bot, например +79123456789.",
        "code_sent": "На {phone} отправлен код, вводите код с пробелами! Например 12 3 45.",
        "code_error": "Код введен неверно, пожалуйста, введите заново.",
        "success": "Аккаунт Qwitty User bot успешно подключен!\n\nВаш ID код: `{qwt_id}`\nНикому не передавайте ID код, ваша безопасность важна для нас!",
        "already_auth": "Вы уже авторизованы. Ваш ID: `{qwt_id}`"
    },
    "en": {
        "welcome": "Welcome to Qwitty registrator bot",
        "btn_start": "Start",
        "btn_back": "Back",
        "enter_phone": "Enter your number to log into Qwitty user bot, e.g. +123456789.",
        "code_sent": "Code sent to {phone}. Please write it with spaces! E.g. 12 3 45.",
        "code_error": "Invalid code, please try again.",
        "success": "Qwitty User bot account connected!\n\nYour ID code: `{qwt_id}`\nDo not share your ID code with anyone, your safety is important to us!",
        "already_auth": "You are already authorized. Your ID: `{qwt_id}`"
    },
    "uz": {
        "welcome": "Qwitty registrator botiga xush kelibsiz",
        "btn_start": "Boshlash",
        "btn_back": "Orqaga",
        "enter_phone": "Qwitty user bot kiritish uchun nomer yozing, masalan +998991234567.",
        "code_sent": "{phone} ga kod yuborildi, kod bo'sh o'rinlar bilan yozilsin! Masalan 12 3 45.",
        "code_error": "Kod xato yozilgan, iltimos qaytadan kiriting.",
        "success": "Qwitty User bot akkauntga ulandi!\n\nSizning ID kodingiz: `{qwt_id}`\nID kodni hech kimga bermang, sizning xavfsizligingiz biz uchun muhim!",
        "already_auth": "Siz allaqachon ro'yxatdan o'tgansiz. Sizning ID: `{qwt_id}`"
    },
    "kz": {
        "welcome": "Qwitty registrator botқа қош келдіңіз",
        "btn_start": "Бастау",
        "btn_back": "Артқа",
        "enter_phone": "Qwitty user bot-қа кіру үшін нөміріңізді жазыңыз, мысалы +7123456789.",
        "code_sent": "Код {phone}-ға жіберілді, кодты бос орындармен жазыңыз! Мысалы 12 3 45.",
        "code_error": "Код қате, қайтадан енгізіңіз.",
        "success": "Qwitty User bot аккаунты қосылды!\n\nСіздің ID кодыңыз: `{qwt_id}`\nID кодты ешкімге бермеңіз, сіздің қауіпсіздігіңіз біз үшін маңызды!",
        "already_auth": "Сіз тіркелгенсіз. Сіздің ID: `{qwt_id}`"
    }
}

# --- Вспомогательные функции ---
def get_lang_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 RU", callback_data="lang_ru"),
            InlineKeyboardButton(text="🇬🇧 ENG", callback_data="lang_en")
        ],
        [
            InlineKeyboardButton(text="🇺🇿 UZB", callback_data="lang_uz"),
            InlineKeyboardButton(text="🇰🇿 KZ", callback_data="lang_kz")
        ]
    ])

def get_start_kb(lang):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]["btn_start"], callback_data="action_start")],
        [InlineKeyboardButton(text=TEXTS[lang]["btn_back"], callback_data="action_back_lang")]
    ])

def get_back_kb(lang):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXTS[lang]["btn_back"], callback_data="action_back_start")]
    ])

async def delayed_delete(message: Message, delay: int = 3):
    """Удаляет сообщение через заданное время."""
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

# --- Хэндлеры ---

@router.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    # Удаляем /start через 3 секунды
    asyncio.create_task(delayed_delete(message, 3))
    
    user_id = message.from_user.id
    
    # Проверка сессии в Supabase
    res = supabase.table("qwitty_users").select("*").eq("tg_id", user_id).execute()
    if res.data:
        lang = res.data[0].get("lang", "ru")
        qwt_id = res.data[0].get("qwt_id")
        msg = await message.answer(TEXTS[lang]["already_auth"].format(qwt_id=qwt_id), parse_mode="Markdown")
        # Удаляем сообщение бота тоже через время? Оставим висеть или можно добавить таск
        return

    await state.clear()
    await message.answer("🇷🇺 Выберите язык / 🇬🇧 Choose language / 🇺🇿 Tilni tanlang / 🇰🇿 Тілді таңдаңыз:", reply_markup=get_lang_kb())

@router.callback_query(F.data.startswith("lang_"))
async def process_language(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[1]
    await state.update_data(lang=lang)
    
    text = TEXTS[lang]["welcome"]
    await callback.message.edit_text(text, reply_markup=get_start_kb(lang))

@router.callback_query(F.data == "action_back_lang")
async def process_back_lang(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🇷🇺 Выберите язык / 🇬🇧 Choose language / 🇺🇿 Tilni tanlang / 🇰🇿 Тілді таңдаңыз:", reply_markup=get_lang_kb())

@router.callback_query(F.data == "action_start")
async def process_action_start(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ru")
    
    await state.set_state(AuthState.phone)
    await callback.message.edit_text(TEXTS[lang]["enter_phone"], reply_markup=get_back_kb(lang))

@router.callback_query(F.data == "action_back_start")
async def process_back_start(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "ru")
    await state.set_state(AuthState.lang)
    await callback.message.edit_text(TEXTS[lang]["welcome"], reply_markup=get_start_kb(lang))

@router.message(AuthState.phone)
async def process_phone(message: Message, state: FSMContext):
    # Удаляем сообщение пользователя с номером
    try: await message.delete()
    except: pass

    data = await state.get_data()
    lang = data.get("lang", "ru")
    phone = message.text.strip().replace(" ", "").replace("+", "")
    
    # Находим сообщение с ботом, чтобы обновить инлайн (достаем из истории или просто отправляем новое, 
    # но лучше перехватить предыдущее. Для простоты отправим новое и сохраним его ID)
    
    bot_msg = await message.answer("🔄 Processing...")
    user_id = message.from_user.id
    masked_phone = f"+{phone[:5]}*****"

    try:
        # Создаем MTProto клиент в памяти
        client = Client(f"session_{user_id}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await client.connect()
        
        sent_code = await client.send_code(phone)
        
        # Сохраняем клиента и хэш кода, чтобы использовать при проверке
        auth_clients[user_id] = {
            "client": client,
            "phone_code_hash": sent_code.phone_code_hash,
            "phone": phone
        }
        
        await state.update_data(bot_msg_id=bot_msg.message_id)
        await state.set_state(AuthState.code)
        await bot_msg.edit_text(TEXTS[lang]["code_sent"].format(phone=masked_phone), reply_markup=get_back_kb(lang))

    except Exception as e:
        await bot_msg.edit_text(f"Error: {str(e)}", reply_markup=get_back_kb(lang))

@router.message(AuthState.code)
async def process_code(message: Message, state: FSMContext):
    # Всегда удаляем сообщение пользователя
    try: await message.delete()
    except: pass

    data = await state.get_data()
    lang = data.get("lang", "ru")
    bot_msg_id = data.get("bot_msg_id")
    user_id = message.from_user.id
    
    # Код формата "12 3 45" убираем пробелы
    code = message.text.replace(" ", "").strip()
    
    auth_data = auth_clients.get(user_id)
    if not auth_data:
        # Сессия сбросилась
        await bot.edit_message_text(chat_id=user_id, message_id=bot_msg_id, text="Session expired. /start")
        return

    client: Client = auth_data["client"]
    phone_code_hash = auth_data["phone_code_hash"]
    phone = auth_data["phone"]

    try:
        await client.sign_in(phone, phone_code_hash, code)
        
        # Успешная авторизация
        session_string = await client.export_session_string()
        await client.disconnect()
        del auth_clients[user_id]
        
        # Генерируем Qwt ID
        qwt_id = f"Qwt-{secrets.token_hex(4).upper()}"
        
        # Записываем в Supabase
        supabase.table("qwitty_users").insert({
            "tg_id": user_id,
            "lang": lang,
            "phone": phone,
            "session_string": session_string,
            "qwt_id": qwt_id
        }).execute()

        await state.clear()
        
        # Обновляем сообщение успехом (ID можно будет скопировать по клику благодаря Markdown)
        await bot.edit_message_text(
            chat_id=user_id, 
            message_id=bot_msg_id, 
            text=TEXTS[lang]["success"].format(qwt_id=qwt_id), 
            parse_mode="Markdown"
        )

    except (PhoneCodeInvalid, PhoneCodeExpired):
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=bot_msg_id,
            text=TEXTS[lang]["code_error"],
            reply_markup=get_back_kb(lang)
        )
    except SessionPasswordNeeded:
        # Если включена двухфакторка (2FA) - можно добавить обработку по необходимости
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=bot_msg_id,
            text="2FA Password Required (Not implemented in this snippet)",
            reply_markup=get_back_kb(lang)
        )
    except Exception as e:
        await bot.edit_message_text(
            chat_id=user_id,
            message_id=bot_msg_id,
            text=f"Error: {e}",
            reply_markup=get_back_kb(lang)
        )

# Глобальный перехватчик, чтобы удалять ЛЮБОЕ левое сообщение во время регистрации
@router.message()
async def delete_unwanted_messages(message: Message):
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


async def main():
    print("Bot is starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
