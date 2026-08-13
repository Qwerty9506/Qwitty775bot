import asyncio
import logging
import random
import string
import sys
from typing import Dict, Any, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.exceptions import TelegramBadRequest
from aiohttp import web
from supabase import create_client, Client

# ================= CONFIGURATION =================
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "YOUR_SUPABASE_ANON_OR_SERVICE_KEY"
API_PORT = 8080  # Порт для Qwitty Auth API

# Инициализация Supabase и Bot
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

logging.basicConfig(level=logging.INFO)

# ================= STATES (FSM) =================
class AuthStates(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()

# ================= LOCALIZATION =================
TEXTS = {
    'ru': {
        'welcome': "Добро пожаловать в Qwitty registrator bot!",
        'btn_start': "Начать",
        'btn_back': "Назад",
        'enter_phone': "Для входа в Qwitty user bot введите номер телефона, например +998991234567.",
        'code_sent': "Код отправлен на номер {phone}, введите код через пробелы! Например 12 3 45.",
        'code_error': "Код введен неверно, пожалуйста, введите снова.",
        'success': "Подключение к аккаунту Qwitty User bot прошло успешно!\n\nВаш ID код: <code>{qwitty_id}</code>\n\nНикому не передавайте этот ID код, ваша безопасность важна для нас!",
        'main_menu': "Вы уже авторизованы в системе Qwitty!\n\nВаш ID код: <code>{qwitty_id}</code>"
    },
    'eng': {
        'welcome': "Welcome to Qwitty registrator bot!",
        'btn_start': "Start",
        'btn_back': "Back",
        'enter_phone': "To enter Qwitty user bot, please type your phone number, e.g. +998991234567.",
        'code_sent': "Code sent to {phone}, please write code with spaces! E.g. 12 3 45.",
        'code_error': "Incorrect code, please try again.",
        'success': "Connected to Qwitty User bot account successfully!\n\nYour ID code: <code>{qwitty_id}</code>\n\nDo not share your ID code with anyone, your security is important to us!",
        'main_menu': "You are already authorized in Qwitty system!\n\nYour ID code: <code>{qwitty_id}</code>"
    },
    'uzb': {
        'welcome': "Qwitty registrator botga xush kelibsiz",
        'btn_start': "Boshlash",
        'btn_back': "Orqaga",
        'enter_phone': "Qwitty user bot kiritish uchun nomer yozing, masalan +998991234567 .",
        'code_sent': "{phone}ga kod yuborildi, kod bosh orinlar bilan yozilsin! Masalan 12 3 45.",
        'code_error': "Kod xato yozilgan, iltimos qaytadan kiriting.",
        'success': "Qwitty User bot akauntka ulandi\n\nSizning ID kodingiz: <code>{qwitty_id}</code>\n\nID kodni hechkimga bermang, sizning xavfsizligingiz biz uchun muhim!",
        'main_menu': "Siz allaqachon Qwitty tizimiga ulangansiz!\n\nSizning ID kodingiz: <code>{qwitty_id}</code>"
    },
    'kz': {
        'welcome': "Qwitty registrator ботына кош келдіңіз",
        'btn_start': "Бастау",
        'btn_back': "Артқа",
        'enter_phone': "Qwitty user ботына кіру үшін телефон номерін жазыңыз, мысалы +998991234567 .",
        'code_sent': "{phone} номеріне код жіберілді, кодты бос орынмен жазыңыз! Мысалы 12 3 45.",
        'code_error': "Код қате жазылған, өтініш қайтадан енгізіңіз.",
        'success': "Qwitty User bot аккаунтына қосылдыңыз!\n\nСіздің ID кодыңыз: <code>{qwitty_id}</code>\n\nID кодты ешкімге бермеңіз, сіздің қауіпсіздігіңіз біз үшін маңызды!",
        'main_menu': "Сіз жүйеге әлдеқашан қосылғансыз!\n\nСіздің ID кодыңыз: <code>{qwitty_id}</code>"
    }
}

# ================= HELPER FUNCTIONS =================
def generate_qwitty_id() -> str:
    chars = string.ascii_uppercase + string.digits
    random_str = ''.join(random.choices(chars, k=6))
    return f"Qwt-{random_str}"

def generate_auth_code() -> str:
    # Генерирует 5-значный код (например: 12 3 45)
    digits = [str(random.randint(0, 9)) for _ in range(5)]
    return f"{digits[0]}{digits[1]} {digits[2]} {digits[3]}{digits[4]}"

async def delete_message_after(msg: Message, delay: int = 3):
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except TelegramBadRequest:
        pass

async def auto_delete_user_msg(message: Message):
    try:
        await message.delete()
    except TelegramBadRequest:
        pass

def get_lang_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 RU", callback_data="lang_ru"),
            InlineKeyboardButton(text="🇬🇧 ENG", callback_data="lang_eng"),
        ],
        [
            InlineKeyboardButton(text="🇺🇿 UZB", callback_data="lang_uzb"),
            InlineKeyboardButton(text="🇰🇿 KZ", callback_data="lang_kz")
        ]
    ])

def get_action_keyboard(lang: str, show_start: bool = True):
    buttons = []
    if show_start:
        buttons.append(InlineKeyboardButton(text=TEXTS[lang]['btn_start'], callback_data="action_start"))
    buttons.append(InlineKeyboardButton(text=TEXTS[lang]['btn_back'], callback_data="action_back"))
    
    keyboard = [[btn] for btn in buttons]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ================= BOT HANDLERS =================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    # Фоновое удаление /start через 3 секунды
    asyncio.create_task(delete_message_after(message, 3))
    
    user_id = message.from_user.id
    
    # Проверка наличия активной сессии в Supabase
    res = supabase.table("users").select("*").eq("telegram_id", user_id).execute()
    
    if res.data and res.data[0].get("is_authenticated"):
        user = res.data[0]
        lang = user.get("lang", "ru")
        await message.answer(
            TEXTS[lang]['main_menu'].format(qwitty_id=user['qwitty_id']),
            parse_mode="HTML"
        )
        return

    await state.clear()
    await message.answer(
        "Выберите язык / Select language / Tilni tanlang:",
        reply_markup=get_lang_keyboard()
    )

@router.callback_query(F.data.startswith("lang_"))
async def process_language_select(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    # Сохраняем пользователя / обновляем язык
    supabase.table("users").upsert({
        "telegram_id": user_id,
        "lang": lang
    }).execute()
    
    await state.update_data(lang=lang)
    
    await callback.message.edit_text(
        TEXTS[lang]['welcome'],
        reply_markup=get_action_keyboard(lang, show_start=True)
    )
    await callback.answer()

@router.callback_query(F.data == "action_back")
async def process_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "Выберите язык / Select language / Tilni tanlang:",
        reply_markup=get_lang_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "action_start")
async def process_start_auth(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    res = supabase.table("users").select("lang").eq("telegram_id", user_id).execute()
    lang = res.data[0]['lang'] if res.data else 'ru'
    
    await state.update_data(lang=lang, last_msg_id=callback.message.message_id)
    await state.set_state(AuthStates.waiting_for_phone)
    
    await callback.message.edit_text(
        TEXTS[lang]['enter_phone'],
        reply_markup=get_action_keyboard(lang, show_start=False)
    )
    await callback.answer()

@router.message(AuthStates.waiting_for_phone)
async def process_phone_input(message: Message, state: FSMContext):
    asyncio.create_task(auto_delete_user_msg(message))
    
    phone = message.text.strip()
    data = await state.get_data()
    lang = data.get("lang", "ru")
    last_msg_id = data.get("last_msg_id")
    
    # Генерация временного кода подтверждения
    code = generate_auth_code()
    
    supabase.table("users").update({
        "phone": phone,
        "auth_code": code
    }).eq("telegram_id", message.from_user.id).execute()
    
    await state.update_data(phone=phone, expected_code=code)
    await state.set_state(AuthStates.waiting_for_code)
    
    mask_phone = phone[:6] + "*****" if len(phone) >= 6 else phone
    
    # Имитация отправки кода и обновление inline-сообщения
    text = TEXTS[lang]['code_sent'].format(phone=mask_phone) + f"\n\n<code>[DEMO CODE]: {code}</code>"
    
    try:
        await bot.edit_message_text(
            text=text,
            chat_id=message.chat.id,
            message_id=last_msg_id,
            reply_markup=get_action_keyboard(lang, show_start=False),
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass

@router.message(AuthStates.waiting_for_code)
async def process_code_input(message: Message, state: FSMContext):
    asyncio.create_task(auto_delete_user_msg(message))
    
    user_code = message.text.strip()
    data = await state.get_data()
    lang = data.get("lang", "ru")
    last_msg_id = data.get("last_msg_id")
    expected_code = data.get("expected_code")
    
    if user_code != expected_code:
        try:
            await bot.edit_message_text(
                text=TEXTS[lang]['code_error'],
                chat_id=message.chat.id,
                message_id=last_msg_id,
                reply_markup=get_action_keyboard(lang, show_start=False)
            )
        except TelegramBadRequest:
            pass
        return
    
    # Генерация Qwitty ID и успешная авторизация
    qwitty_id = generate_qwitty_id()
    
    supabase.table("users").update({
        "qwitty_id": qwitty_id,
        "is_authenticated": True,
        "auth_code": None
    }).eq("telegram_id", message.from_user.id).execute()
    
    await state.clear()
    
    try:
        await bot.edit_message_text(
            text=TEXTS[lang]['success'].format(qwitty_id=qwitty_id),
            chat_id=message.chat.id,
            message_id=last_msg_id,
            parse_mode="HTML"
        )
    except TelegramBadRequest:
        pass

# ================= QWITTY AUTH API (FOR OTHER BOTS) =================
async def handle_api_verify(request: web.Request) -> web.Response:
    """
    Эндпоинт для внешних ботов сервиса Qwitty.
    Пример запроса: GET /api/verify?qwitty_id=Qwt-X1Y2Z3
    """
    qwitty_id = request.query.get("qwitty_id")
    if not qwitty_id:
        return web.json_response({"status": "error", "message": "Missing qwitty_id"}, status=400)
    
    res = supabase.table("users").select("*").eq("qwitty_id", qwitty_id).execute()
    
    if res.data and res.data[0].get("is_authenticated"):
        user = res.data[0]
        return web.json_response({
            "status": "success",
            "authenticated": True,
            "data": {
                "telegram_id": user["telegram_id"],
                "qwitty_id": user["qwitty_id"],
                "phone": user["phone"],
                "lang": user["lang"]
            }
        })
    
    return web.json_response({"status": "error", "authenticated": False, "message": "User not found or not authenticated"}, status=44)

async def start_api_server():
    app = web.Application()
    app.router.add_get('/api/verify', handle_api_verify)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', API_PORT)
    await site.start()
    logging.info(f"Qwitty Auth API running on port {API_PORT}")

# ================= MAIN RUNNER =================
async def main():
    # Запуск REST API вместе с телеграм ботом
    await start_api_server()
    
    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped!")
