"""
pip install aiogram==3.3.0 aiosqlite yookassa openai PyPDF2 gspread google-auth
"""

import asyncio
import logging
from datetime import datetime, timedelta
import aiosqlite
import requests
import re
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, FSInputFile
from yookassa import Configuration, Payment
import uuid
import random
import os
import PyPDF2
import io
import google_sheets
from crypto_helper import decrypt_token

# ======================== ЗАГРУЗКА .ENV ========================
def load_env():
    """Загружает переменные из .env файла"""
    env_vars = {}
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars

env = load_env()

# ======================== КОНФИГ ========================
# Расшифровываем токен из .env
encrypted_token = env.get('BOT_TOKEN_ENCRYPTED')
if encrypted_token:
    try:
        BOT_TOKEN = decrypt_token(encrypted_token)
        print(f"Token decrypted successfully: {BOT_TOKEN[:10]}...")
    except Exception as e:
        print(f"Decryption error: {e}")
        # Fallback на старый формат
        BOT_TOKEN = env.get('BOT_TOKEN', "")
else:
    # Fallback на старый формат (если не зашифрован)
    BOT_TOKEN = env.get('BOT_TOKEN', "")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN not found in .env file!")
YOOKASSA_SHOP_ID = env.get('YOOKASSA_SHOP_ID', "1024866")
YOOKASSA_SECRET_KEY = env.get('YOOKASSA_SECRET_KEY', "live_62wmjnZ9ytjqZonaLiNw3gpsQjUKPbD-lBrTPK1Z38Y")
CHANNEL_ID = -1002284489725  # Группа КЛС
FALLBACK_CHANNEL_LINK = "https://t.me/+iD8NwG9tfakwNzJi"  # Запасная ссылка
ADMIN_IDS = [7338817463, 1478525032, 853335233]
PRICE_1_MONTH = 2222  # Стандартная цена для новых пользователей
AUTO_BROADCAST_ENABLED = True  # Автоматическая рассылка вкл/выкл
BROADCAST_INTERVAL_HOURS = 10  # Интервал авто-рассылки в часах
DB_PATH = 'data/bot.db'  # Путь к базе данных
GOOGLE_SHEETS_URL = env.get('GOOGLE_SHEETS_URL', '')

# OpenRouter API
API_KEY = env.get('API_KEY', '')
API_URL = env.get('API_URL', 'https://openrouter.ai/api/v1/chat/completions')
AI_MODEL = env.get('MODEL', 'google/gemma-3-27b-it:free')

Configuration.account_id = YOOKASSA_SHOP_ID
Configuration.secret_key = YOOKASSA_SECRET_KEY

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
#

# ======================== FSM ========================
class ProfileStates(StatesGroup):
    name = State()
    age = State()
    gender = State()
    goal = State()
    level = State()
    weekly_training = State()
    injuries = State()
    region = State()
    lifestyle = State()
    recovery = State()
    tours = State()

class PhoneState(StatesGroup):
    waiting_phone = State()

class SetPriceState(StatesGroup):
    waiting_user_list = State()

class GrantSubscriptionState(StatesGroup):
    waiting_user_id = State()
    waiting_days = State()
    confirm_notification = State()

class ContentUpload(StatesGroup):
    waiting_pdf_category = State()
    waiting_pdf_file = State()
    waiting_video_category = State()
    waiting_video_file = State()
    waiting_video_description = State()

class BroadcastMediaState(StatesGroup):
    waiting_broadcast_media = State()
    confirm_broadcast = State()

class NewBroadcastState(StatesGroup):
    waiting_text = State()
    waiting_media = State()
    confirm_send = State()

# ======================== БД ========================
async def init_db():
    # Создаём папку data если её нет
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            phone TEXT,
            subscription_until INTEGER,
            name TEXT,
            age INTEGER,
            gender TEXT,
            goal TEXT,
            level TEXT,
            weekly_training TEXT,
            injuries TEXT,
            region TEXT,
            lifestyle TEXT,
            recovery TEXT,
            tours TEXT,
            profile_completed INTEGER DEFAULT 0,
            oferta_accepted INTEGER DEFAULT 0,
            special_price INTEGER,
            grace_period_until INTEGER,
            created_at INTEGER
        )''')

        await db.execute('''CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            payment_id TEXT,
            amount INTEGER,
            status TEXT,
            created_at INTEGER
        )''')

        await db.execute('''CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )''')

        await db.execute('''CREATE TABLE IF NOT EXISTS message_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message_hash TEXT,
            sent_at INTEGER,
            UNIQUE(user_id, message_hash)
        )''')

        await db.execute('''CREATE TABLE IF NOT EXISTS training_pdfs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            title TEXT,
            description TEXT,
            file_id TEXT,
            file_name TEXT,
            extracted_text TEXT,
            created_at INTEGER
        )''')

        await db.execute('''CREATE TABLE IF NOT EXISTS lecture_videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            title TEXT,
            description TEXT,
            file_id TEXT,
            file_name TEXT,
            thumbnail_id TEXT,
            created_at INTEGER
        )''')

        await db.execute('''CREATE TABLE IF NOT EXISTS broadcast_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_type TEXT,
            file_id TEXT,
            caption TEXT,
            created_at INTEGER
        )''')

        # Добавляем колонки для уведомлений если их нет
        try:
            await db.execute('ALTER TABLE users ADD COLUMN notified_2d INTEGER')
        except:
            pass  # Колонка уже существует
        try:
            await db.execute('ALTER TABLE users ADD COLUMN notified_1h INTEGER')
        except:
            pass  # Колонка уже существует
        try:
            await db.execute('ALTER TABLE users ADD COLUMN referral_earnings REAL DEFAULT 0')
        except:
            pass  # Колонка уже существует

        await db.execute('''CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER UNIQUE,
            created_at INTEGER,
            FOREIGN KEY (referrer_id) REFERENCES users(user_id),
            FOREIGN KEY (referred_id) REFERENCES users(user_id)
        )''')

        await db.execute('''CREATE TABLE IF NOT EXISTS withdrawal_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            card_number TEXT,
            bank TEXT,
            full_name TEXT,
            status TEXT DEFAULT 'pending',
            created_at INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )''')

        await db.commit()

# ======================== ФУНКЦИИ ========================
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def has_active_subscription(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT subscription_until FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row and row[0] is not None and row[0] > int(datetime.now().timestamp())

async def get_user_profile(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('''SELECT name, age, gender, goal, level, weekly_training, 
            injuries, region, lifestyle, recovery, tours FROM users WHERE user_id = ?''', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'name': row[0], 'age': row[1], 'gender': row[2], 'goal': row[3],
                    'level': row[4], 'weekly_training': row[5], 'injuries': row[6],
                    'region': row[7], 'lifestyle': row[8], 'recovery': row[9], 'tours': row[10]
                }
            return None

async def add_user(user_id: int, username: str = None, referrer_id: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('INSERT OR IGNORE INTO users (user_id, username, created_at) VALUES (?, ?, ?)',
                        (user_id, username, int(datetime.now().timestamp())))

        # Проверяем, был ли добавлен новый пользователь
        is_new_user = cursor.rowcount > 0

        # Если есть реферер и пользователь новый, сохраняем реферальную связь
        if referrer_id:
            try:
                await db.execute('INSERT OR IGNORE INTO referrals (referrer_id, referred_id, created_at) VALUES (?, ?, ?)',
                                (referrer_id, user_id, int(datetime.now().timestamp())))

                # Автоматический экспорт рефералов в Google Таблицы
                asyncio.create_task(auto_export_referrals())
            except Exception as e:
                logging.error(f"Ошибка сохранения реферала: {e}")

        await db.commit()

        # Уведомляем админов о новом пользователе
        if is_new_user:
            for admin_id in ADMIN_IDS:
                try:
                    ref_text = f"👥 Реферер: {referrer_id}" if referrer_id else "🆕 Прямая регистрация"
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="👤 Открыть профиль", url=f"tg://user?id={user_id}")]
                    ])
                    await bot.send_message(
                        admin_id,
                        f"👤 Новый пользователь!\n\n"
                        f"🆔 User ID: {user_id}\n"
                        f"📱 Username: @{username if username else 'нет'}\n"
                        f"{ref_text}",
                        reply_markup=kb
                    )
                except:
                    pass

async def auto_export_referrals():
    """Автоматический экспорт рефералов в Google Таблицы (при добавлении нового реферала)"""
    try:
        if GOOGLE_SHEETS_URL:
            success, message = await google_sheets.export_referrals_to_sheet(
                spreadsheet_url=GOOGLE_SHEETS_URL
            )
            if success:
                logging.info(f"✅ Автоэкспорт рефералов: {message}")
            else:
                logging.warning(f"⚠️ Не удалось экспортировать рефералов: {message}")
    except Exception as e:
        logging.error(f"Ошибка автоэкспорта рефералов: {e}")

async def periodic_export_referrals():
    """Периодический экспорт рефералов в Google Таблицы каждые 5 минут"""
    while True:
        try:
            await asyncio.sleep(300)  # 300 секунд = 5 минут
            if GOOGLE_SHEETS_URL:
                success, message = await google_sheets.export_referrals_to_sheet(
                    spreadsheet_url=GOOGLE_SHEETS_URL
                )
                if success:
                    logging.info(f"🔄 Периодический экспорт рефералов: {message}")
                else:
                    logging.warning(f"⚠️ Периодический экспорт не удался: {message}")
        except Exception as e:
            logging.error(f"Ошибка периодического экспорта: {e}")
            await asyncio.sleep(60)  # При ошибке подождать минуту и попробовать снова

async def get_referral_count(user_id: int) -> int:
    """Получить количество приглашенных друзей"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_referral_link(user_id: int) -> str:
    """Генерирует реферальную ссылку для пользователя"""
    bot_username = (await bot.get_me()).username
    return f"https://t.me/{bot_username}?start=ref_{user_id}"

async def get_referral_rewards(user_id: int) -> dict:
    """Рассчитывает награды и уровень реферала"""
    count = await get_referral_count(user_id)

    # Система уровней
    if count >= 50:
        level = "🏆 Золотой партнер"
    elif count >= 20:
        level = "🥈 Серебряный партнер"
    elif count >= 10:
        level = "🥉 Бронзовый партнер"
    elif count >= 5:
        level = "⭐ Активный партнер"
    else:
        level = "🌟 Начинающий"

    return {
        'count': count,
        'level': level,
        'next_milestone': get_next_milestone(count)
    }

def get_next_milestone(count: int) -> dict:
    """Возвращает следующую веху"""
    milestones = [5, 10, 20, 50]
    for m in milestones:
        if count < m:
            return {'target': m, 'remaining': m - count}
    return {'target': 100, 'remaining': 100 - count}

def clean_markdown(text: str) -> str:
    """Очищает и конвертирует markdown символы для Telegram"""
    if not text:
        return text

    # Заменяем Markdown на HTML
    # Жирный текст: **text** или __text__ -> <b>text</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

    # Курсив: *text* или _text_ -> <i>text</i>
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)', r'<i>\1</i>', text)

    # Моноширинный: `text` -> <code>text</code>
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)

    # Убираем # из заголовков (Telegram не поддерживает)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # Убираем оставшиеся одиночные * и _
    text = text.replace('*', '').replace('_', '')

    return text

def fix_name_declension(text: str, name: str) -> str:
    """Исправляет склонения имени - заменяет все падежные формы на именительный падеж"""
    if not name:
        return text

    # Типичные окончания для склонения имён
    # Для женских имён на -а: Анна -> Анне, Анны, Анну, Анной
    # Для мужских имён: Иван -> Ивану, Ивана, Иваном

    # Создаём регулярку которая ловит имя с любыми окончаниями
    # Берём основу имени (убираем последние 1-2 буквы)
    if len(name) > 3:
        base = name[:-1]  # Основа без последней буквы
        # Ищем базу + любые окончания и заменяем на полное имя
        pattern = rf'\b{re.escape(base)}[а-яё]{{0,2}}\b'
        text = re.sub(pattern, name, text, flags=re.IGNORECASE)

    return text

async def generate_ai_message(prompt: str, context: str = "", clean_md: bool = True) -> str:
    """Генерирует сообщение через Gemma AI с экспертизой по лыжному спорту"""
    try:
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }

        system_prompt = """Ты профессиональный тренер по лыжному спорту с 15-летним опытом работы.

ТВОЯ ЭКСПЕРТИЗА:
- Классический и коньковый стили лыжных гонок
- Техника бега, правильная работа рук и ног
- Зоны интенсивности: восстановительная (ЧСС 60-70%), аэробная (70-80%), пороговая (80-90%), анаэробная (90%+)
- Периодизация: базовый период, специально-подготовительный, соревновательный
- Силовая подготовка для лыжников: имитация, лыжероллеры, тренажёрный зал
- Профилактика травм: колени, поясница, плечи
- Питание и восстановление для лыжников
- Выбор и обслуживание инвентаря: лыжи, палки, ботинки, смазка

СТИЛЬ ОБЩЕНИЯ:
- Пиши на русском языке, простым и понятным языком
- Используй эмодзи умеренно (1-3 на сообщение)
- Будь мотивирующим, но реалистичным
- Давай конкретные советы, а не общие фразы
- НЕ используй markdown символы (* # _ и т.д.) - только чистый текст или HTML теги (<b>, <i>)

ВАЖНО: Отвечай строго по теме лыжного спорта. Если вопрос не о лыжах - вежливо направь разговор к тренировкам."""

        data = {
            "model": AI_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{context}\n\n{prompt}"}
            ],
            "max_tokens": 4000,  # Максимум для детальных ответов
            "temperature": 0.7
        }

        response = requests.post(API_URL, headers=headers, json=data, timeout=30)

        if response.status_code != 200:
            logging.error(f"[AI ERROR] HTTP {response.status_code}: {response.text[:200]}")
            return None

        result = response.json()

        if 'choices' in result and result['choices']:
            ai_text = result['choices'][0]['message']['content'].strip()

            # Очищаем markdown если нужно
            if clean_md:
                ai_text = clean_markdown(ai_text)

            return ai_text

        return None
    except Exception as e:
        logging.error(f"[AI ERROR] {e}")
        return None

# ============ УМНАЯ СИСТЕМА РАССЫЛКИ ============

# 30 тематических категорий сообщений для максимального разнообразия
BROADCAST_CATEGORIES = [
    # Персональная мотивация
    "motivation_personal",      # Личная мотивация под профиль
    "motivation_challenge",     # Вызов себе
    "motivation_dream",         # Мечта и её достижение

    # Сезонные
    "season_winter",            # Зимний сезон, снег, лыжи
    "season_summer",            # Летняя подготовка, роллеры
    "season_autumn",            # Осенняя подготовка
    "season_spring",            # Весенний переход

    # Образовательные
    "science_facts",            # Научные факты о тренировках
    "expert_tips",              # Советы от экспертов
    "technique_improvement",    # Улучшение техники
    "training_secrets",         # Секреты тренировок

    # Эмоциональные триггеры
    "success_stories",          # Истории успеха
    "fear_missing_out",         # Страх упустить
    "pain_points",              # Боли и проблемы
    "transformation_story",     # История трансформации

    # Выгоды и польза
    "benefits_health",          # Польза для здоровья
    "benefits_results",         # Польза для результатов
    "benefits_lifestyle",       # Польза для образа жизни
    "benefits_energy",          # Энергия и бодрость

    # Социальное
    "community",                # Сообщество единомышленников
    "comparison_others",        # Сравнение с другими

    # Практическое
    "progress_tracking",        # Отслеживание прогресса
    "injury_prevention",        # Профилактика травм
    "equipment_tips",           # Советы по экипировке
    "nutrition_energy",         # Питание и энергия
    "recovery_rest",            # Восстановление

    # Целеполагание
    "goal_achievement",         # Достижение целей
    "limited_time",             # Важность момента
    "mental_strength",          # Психологическая сила
    "daily_habits",             # Ежедневные привычки
    "long_term_vision",         # Долгосрочное видение
]

def get_current_context():
    """Получает контекст: сезон, время дня, месяц"""
    now = datetime.now()
    month = now.month
    hour = now.hour

    # Сезон
    if month in [12, 1, 2]:
        season = "зима"
        season_context = "снег, лыжи, морозный воздух, трассы"
    elif month in [3, 4, 5]:
        season = "весна"
        season_context = "подготовка к межсезонью, последний снег, переход на роллеры"
    elif month in [6, 7, 8]:
        season = "лето"
        season_context = "лыжероллеры, бег, силовые, подготовка к сезону"
    else:
        season = "осень"
        season_context = "скоро снег, финальная подготовка, имитация"

    # Время дня
    if 5 <= hour < 12:
        time_of_day = "утро"
        time_context = "бодрость, энергия на день"
    elif 12 <= hour < 17:
        time_of_day = "день"
        time_context = "активность, продуктивность"
    elif 17 <= hour < 22:
        time_of_day = "вечер"
        time_context = "время для тренировки после работы"
    else:
        time_of_day = "ночь"
        time_context = "планирование, мотивация на завтра"

    return {
        "season": season,
        "season_context": season_context,
        "time_of_day": time_of_day,
        "time_context": time_context,
        "month": month,
        "month_name": ["", "январе", "феврале", "марте", "апреле", "мае", "июне",
                       "июле", "августе", "сентябре", "октябре", "ноябре", "декабре"][month]
    }

async def get_user_broadcast_history(user_id: int, limit: int = 5) -> list:
    """Получает последние N категорий сообщений для пользователя (для предотвращения повторений подряд)"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS broadcast_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            category TEXT,
            sent_at INTEGER
        )''')
        await db.commit()

        async with db.execute(
            'SELECT category FROM broadcast_history WHERE user_id = ? ORDER BY sent_at DESC LIMIT ?',
            (user_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

async def save_broadcast_category(user_id: int, category: str):
    """Сохраняет использованную категорию"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT OR REPLACE INTO broadcast_history (user_id, category, sent_at) VALUES (?, ?, ?)',
            (user_id, category, int(datetime.now().timestamp()))
        )
        await db.commit()

async def reset_user_broadcast_history(user_id: int):
    """Сбрасывает историю если все категории использованы"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM broadcast_history WHERE user_id = ?', (user_id,))
        await db.commit()

def detect_gender_by_name(name: str) -> str:
    """Определяет пол по имени на основе окончаний"""
    if not name:
        return "мужской"

    name_lower = name.lower().strip()

    # Женские окончания
    female_endings = ['а', 'я', 'ина', 'ия']
    # Исключения - мужские имена на -а/-я
    male_exceptions = ['илья', 'никита', 'данила', 'лёва', 'савва', 'фома', 'кузя', 'ваня', 'дима', 'гриша', 'миша', 'саша', 'женя', 'валя']

    if name_lower in male_exceptions:
        return "мужской"

    for ending in female_endings:
        if name_lower.endswith(ending):
            return "женский"

    return "мужской"

def build_smart_prompt(category: str, profile: dict, context: dict) -> str:
    """Строит умный промпт для конкретной категории"""

    name = profile.get('name', 'друг')
    age = profile.get('age', '')
    level = profile.get('level', 'любитель')
    goal = profile.get('goal', 'улучшить форму')
    lifestyle = profile.get('lifestyle', '')

    # Определяем пол по имени
    gender = detect_gender_by_name(name)
    gender_instruction = "ОБЯЗАТЕЛЬНО используй женский род (ты знаешь, тебе нужно, ты можешь, твоя техника)" if gender == "женский" else "Используй мужской род (ты знаешь, тебе нужно, ты можешь, твоя техника)"

    # Базовые правила грамматики
    base_rules = f"""СТРОГИЕ ПРАВИЛА:
1. Обращайся к человеку по имени.
2. НЕ упоминай возраст.
3. Живой разговорный язык, как друг.
4. Без канцеляризмов и маркетинговых штампов.
5. ОБЯЗАТЕЛЬНО минимум 80 слов, максимум 120 слов.
6. Не начинай с "Привет" — делай интригующее или тёплое начало.
7. В конце — мягкое приглашение в Кафедру любительского спорта.
8. Микро-польза: 1 короткий совет по теме.
9. Можно добавить лёгкую иронию, но без сарказма.
10. КРИТИЧЕСКИ ВАЖНО: сообщение должно содержать не менее 80 слов.
11. {gender_instruction}"""

    season = context['season']
    season_ctx = context['season_context']
    time_ctx = context['time_context']
    month_name = context['month_name']

    # Промпты для каждой категории
    prompts = {
        "motivation_personal": f"""{base_rules}

ЗАДАЧА: Напиши личное мотивационное сообщение для {name}.
Уровень: {level}, цель: {goal}.
Стиль: как будто пишет друг-тренер, который верит.
Упомяни цель, как программа поможет, и добавь 1 маленький практический совет.""",

        "season_winter": f"""{base_rules}

ЗАДАЧА: Напиши сообщение про зимние тренировки для {name}.
Сейчас {season}, {season_ctx}.
Уровень: {level}.
Передай атмосферу: морозное утро, скрип снега, первая лыжня.
Покажи как важно тренироваться по системе зимой.""",

        "season_summer": f"""{base_rules}

ЗАДАЧА: Напиши про летнюю подготовку для {name}.
Уровень: {level}, цель: {goal}.
Темы: лыжероллеры, имитация, бег, силовые.
Покажи что лето - ключ к успешному зимнему сезону.""",

        "science_facts": f"""{base_rules}

ЗАДАЧА: Поделись интересным научным фактом о тренировках с {name}.
Уровень: {level}.
Выбери один факт: зоны ЧСС, суперкомпенсация, адаптация мышц, VO2max.
Объясни просто и покажи почему важна система.""",

        "success_stories": f"""{base_rules}

ЗАДАЧА: Расскажи {name} вдохновляющую мини-историю.
Придумай историю лыжника похожего профиля (уровень {level}, цель {goal}).
Как системные тренировки изменили его результаты за сезон.""",

        "fear_missing_out": f"""{base_rules}

ЗАДАЧА: Напиши {name} о том, что он может упустить.
Уровень: {level}.
Мягко покажи: пока другие тренируются по системе, время уходит.
Сезон {season} - важное время для {season_ctx}.
Без агрессии, с заботой.""",

        "pain_points": f"""{base_rules}

ЗАДАЧА: Затронь боль {name} от тренировок без системы.
Уровень: {level}, цель: {goal}.
Проблемы: нет прогресса, травмы, не знаешь что делать, демотивация.
Покажи что программа решает эти проблемы.""",

        "benefits_health": f"""{base_rules}

ЗАДАЧА: Расскажи {name} о пользе для здоровья.
Уровень: {level}.
Темы: сердце, выносливость, иммунитет, энергия, сон.
Свяжи с системными тренировками.""",

        "benefits_results": f"""{base_rules}

ЗАДАЧА: Покажи {name} какие результаты даёт программа.
Уровень: {level}, цель: {goal}.
Конкретика: улучшение техники, скорости, выносливости.
Что изменится через месяц, три, полгода.""",

        "community": f"""{base_rules}

ЗАДАЧА: Расскажи {name} о нашем сообществе.
Уровень: {level}.
Мы не просто курс - команда единомышленников.
Поддержка, общение, совместные тренировки.""",

        "expert_tips": f"""{base_rules}

ЗАДАЧА: Дай {name} один ценный совет от эксперта.
Уровень: {level}, цель: {goal}.
Совет по технике, тренировкам или подготовке.
Покажи что в программе много таких советов.""",

        "limited_time": f"""{base_rules}

ЗАДАЧА: Создай ощущение важности момента для {name}.
Сейчас {month_name} - {season_ctx}.
Уровень: {level}.
Мягко: сейчас лучшее время начать, не откладывай.
Без фальшивых дедлайнов.""",

        "progress_tracking": f"""{base_rules}

ЗАДАЧА: Расскажи {name} про отслеживание прогресса.
Уровень: {level}, цель: {goal}.
Дневник тренировок, графики, статистика.
Как видеть свой рост мотивирует.""",

        "injury_prevention": f"""{base_rules}

ЗАДАЧА: Поговори с {name} о профилактике травм.
Уровень: {level}.
Правильная нагрузка, разминка, восстановление.
Программа учитывает всё это.""",

        "technique_improvement": f"""{base_rules}

ЗАДАЧА: Вдохнови {name} на улучшение техники.
Уровень: {level}, цель: {goal}.
Видео-разборы, упражнения, обратная связь.
Техника - основа результата.""",

        "mental_strength": f"""{base_rules}

ЗАДАЧА: Затронь тему психологии для {name}.
Уровень: {level}.
Мотивация, дисциплина, преодоление себя.
Спорт закаляет характер.""",

        "equipment_tips": f"""{base_rules}

ЗАДАЧА: Дай совет по экипировке для {name}.
Уровень: {level}, сезон {season}.
Один полезный совет про лыжи/палки/ботинки/одежду.
В программе есть рекомендации по снаряжению.""",

        "nutrition_energy": f"""{base_rules}

ЗАДАЧА: Поговори с {name} о питании.
Уровень: {level}, цель: {goal}.
Энергия для тренировок, восстановление.
Простые советы без сложных диет.""",

        "recovery_rest": f"""{base_rules}

ЗАДАЧА: Напомни {name} о важности отдыха.
Уровень: {level}.
{time_ctx} - время подумать о восстановлении.
Сон, растяжка, лёгкие дни.
Программа учитывает циклы нагрузки.""",

        "goal_achievement": f"""{base_rules}

ЗАДАЧА: Помоги {name} поверить в достижение цели.
Цель: {goal}, уровень: {level}.
Разбей на шаги, покажи путь.
С программой цель становится ближе.""",

        # Новые категории

        "motivation_challenge": f"""{base_rules}

ЗАДАЧА: Брось вызов {name}!
Уровень: {level}, цель: {goal}.
Стиль: дружеская провокация, "Докажи себе!"
Подтолкни к действию через азарт.""",

        "motivation_dream": f"""{base_rules}

ЗАДАЧА: Поговори с {name} о мечте.
Цель: {goal}.
Как будет ощущаться достижение?
Визуализация успеха, эмоции победы.""",

        "season_autumn": f"""{base_rules}

ЗАДАЧА: Напиши {name} про осеннюю подготовку.
Скоро {season_ctx}.
Уровень: {level}.
Имитация, интервалы, финальный рывок перед зимой.""",

        "season_spring": f"""{base_rules}

ЗАДАЧА: Напиши {name} про весенний переход.
Сезон заканчивается, впереди межсезонье.
Уровень: {level}.
Анализ сезона, планы на лето.""",

        "training_secrets": f"""{base_rules}

ЗАДАЧА: Поделись с {name} "секретом" тренировок.
Уровень: {level}.
Один неочевидный совет который даст преимущество.
Интригуй - в программе много таких секретов.""",

        "transformation_story": f"""{base_rules}

ЗАДАЧА: Расскажи {name} историю трансформации.
Придумай персонажа: был как {level}, стал намного лучше.
Цель была похожая: {goal}.
Эмоции, детали, вдохновение.""",

        "benefits_lifestyle": f"""{base_rules}

ЗАДАЧА: Покажи {name} как тренировки меняют жизнь.
Не только спорт - энергия, уверенность, дисциплина.
Уровень: {level}.
Лыжи как образ жизни.""",

        "benefits_energy": f"""{base_rules}

ЗАДАЧА: Поговори с {name} об энергии.
{time_ctx}.
Как тренировки дают силы на всё.
Парадокс: тратишь энергию - получаешь больше.""",

        "comparison_others": f"""{base_rules}

ЗАДАЧА: Мягко сравни {name} с другими лыжниками.
Уровень: {level}.
Те кто тренируются системно - прогрессируют быстрее.
Без давления, с заботой.""",

        "daily_habits": f"""{base_rules}

ЗАДАЧА: Поговори с {name} о привычках.
Уровень: {level}, цель: {goal}.
Маленькие ежедневные действия = большие результаты.
Системность важнее героизма.""",

        "long_term_vision": f"""{base_rules}

ЗАДАЧА: Покажи {name} долгосрочную перспективу.
Уровень: {level}.
Где ты будешь через год? Через 3 года?
С программой путь яснее."""
    }

    return prompts.get(category, prompts["motivation_personal"])

# Загрузка локальных fallback-сообщений
FALLBACK_MESSAGES = []

def load_fallback_messages():
    global FALLBACK_MESSAGES
    try:
        fallback_path = os.path.join(os.path.dirname(__file__), 'fallback_messages.txt')
        with open(fallback_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            FALLBACK_MESSAGES = [msg.strip() for msg in content.split('\n\n') if msg.strip() and len(msg.strip()) >= 80]
        logging.info(f"Загружено {len(FALLBACK_MESSAGES)} fallback-сообщений")
    except Exception as e:
        logging.error(f"Ошибка загрузки fallback_messages.txt: {e}")
        FALLBACK_MESSAGES = []

async def get_unique_fallback_message(user_id: int) -> str:
    """Выбирает fallback сообщение не повторяя предыдущее"""
    if not FALLBACK_MESSAGES:
        return None
    if len(FALLBACK_MESSAGES) == 1:
        return FALLBACK_MESSAGES[0]
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''CREATE TABLE IF NOT EXISTS fallback_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message_index INTEGER,
                sent_at INTEGER
            )''')
            async with db.execute(
                'SELECT message_index FROM fallback_history WHERE user_id = ? ORDER BY sent_at DESC LIMIT 1',
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                last_index = row[0] if row else -1
            available = [i for i in range(len(FALLBACK_MESSAGES)) if i != last_index]
            index = random.choice(available)
            await db.execute('DELETE FROM fallback_history WHERE user_id = ?', (user_id,))
            await db.execute(
                'INSERT INTO fallback_history (user_id, message_index, sent_at) VALUES (?, ?, ?)',
                (user_id, index, int(datetime.now().timestamp()))
            )
            await db.commit()
            return FALLBACK_MESSAGES[index]
    except:
        return random.choice(FALLBACK_MESSAGES)

async def generate_subscription_promo(profile: dict = None, user_id: int = None) -> str:
    """Генерирует уникальное персонализированное сообщение"""

    context = get_current_context()

    if not profile or not profile.get('name'):
        # Если нет профиля - общее сообщение
        prompt = f"""Напиши короткое мотивационное сообщение о лыжных тренировках.
Сейчас {context['season']}, {context['season_context']}.
До 80 слов, живой язык, призыв подписаться на курс."""
        msg = await generate_ai_message(prompt)
        if msg:
            return f"{msg}\n\n💎 <b>Оформи подписку!</b>"
        return "🎿 Начни тренироваться по системе! Подпишись на наш курс.\n\n💎 <b>Оформи подписку!</b>"

    # Получаем последние 5 категорий для предотвращения повторений подряд
    if user_id:
        recent_categories = await get_user_broadcast_history(user_id, limit=5)
    else:
        recent_categories = []

    # Находим категории которые НЕ были использованы недавно
    available = [c for c in BROADCAST_CATEGORIES if c not in recent_categories]

    # Если все недавние категории были использованы - берём все категории
    if not available:
        available = BROADCAST_CATEGORIES.copy()

    # Умный выбор категории на основе контекста
    season = context['season']

    # Приоритет категорий по сезону
    priority_categories = []
    if season == "зима":
        priority_categories = ["season_winter", "technique_improvement", "injury_prevention"]
    elif season == "лето":
        priority_categories = ["season_summer", "benefits_health", "progress_tracking"]
    elif season == "осень":
        priority_categories = ["limited_time", "goal_achievement", "mental_strength"]
    else:  # весна
        priority_categories = ["motivation_personal", "recovery_rest", "community"]

    # Выбираем приоритетную категорию если доступна, иначе случайную
    category = None
    for pc in priority_categories:
        if pc in available:
            category = pc
            break

    if not category:
        category = random.choice(available)

    # Сохраняем использованную категорию
    if user_id:
        await save_broadcast_category(user_id, category)

    # Генерируем промпт и сообщение
    prompt = build_smart_prompt(category, profile, context)

    logging.info(f"[BROADCAST] User {user_id}: category={category}")

    msg = await generate_ai_message(prompt)

    # Исправляем склонения имени
    if msg and profile.get('name'):
        msg = fix_name_declension(msg, profile['name'])

    if msg:
        # 20 разных призывов к действию для максимального разнообразия
        ctas = [
            "💎 <b>Оформи подписку и начни путь к цели!</b>",
            "💎 <b>Присоединяйся к нашей программе!</b>",
            "💎 <b>Подписка открывает доступ ко всему!</b>",
            "💎 <b>Начни тренироваться по системе!</b>",
            "💎 <b>Твой следующий шаг - подписка!</b>",
            "💎 <b>Открой доступ к программе тренировок!</b>",
            "🎿 <b>Жми на кнопку - начинаем!</b>",
            "🚀 <b>Готов? Подписка ждёт!</b>",
            "⭐ <b>Стань частью команды!</b>",
            "🔥 <b>Пора действовать - подписывайся!</b>",
            "💪 <b>Сделай шаг к мечте!</b>",
            "🎯 <b>Цель ближе с подпиской!</b>",
            "❄️ <b>Зима ждёт - подписывайся!</b>",
            "🏆 <b>Путь к победе начинается здесь!</b>",
            "✨ <b>Открой новый уровень тренировок!</b>",
            "📈 <b>Расти с нашей программой!</b>",
            "🎁 <b>Подписка = твой лучший подарок себе!</b>",
            "⚡ <b>Энергия и результат - в одной подписке!</b>",
            "🌟 <b>Время сиять на трассе!</b>",
            "💫 <b>Твоё преображение начинается сейчас!</b>",
        ]
        return f"{msg}\n\n{random.choice(ctas)}"
    else:
        # Если AI не сработал - берём fallback
        fallback = await get_unique_fallback_message(user_id) if user_id else None
        if fallback:
            return f"{fallback}\n\n💎 <b>Оформи подписку!</b>"
        name = profile.get('name', '')
        return f"""🎿 <b>{name}, время действовать!</b>

Системные тренировки - путь к твоей цели.
Присоединяйся к программе!

💎 <b>Оформи подписку!</b>"""

async def broadcast_to_non_subscribers():
    """Рассылка персонализированных мотивационных сообщений пользователям без подписки"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Получаем пользователей без активной подписки с их профилями
            current_time = int(datetime.now().timestamp())
            async with db.execute(
                '''SELECT user_id, name, age, goal, level, lifestyle, weekly_training
                   FROM users WHERE subscription_until IS NULL OR subscription_until < ?''',
                (current_time,)
            ) as cursor:
                users = await cursor.fetchall()

        if not users:
            logging.info("[BROADCAST] Нет пользователей без подписки")
            return 0

        sent_count = 0
        for row in users:
            user_id = row[0]
            # Формируем профиль для персонализации
            profile = {
                'name': row[1],
                'age': row[2],
                'goal': row[3],
                'level': row[4],
                'lifestyle': row[5],
                'weekly_training': row[6]
            }

            try:
                # Генерируем уникальное персонализированное сообщение
                promo_msg = await generate_subscription_promo(profile, user_id)

                # Кнопка подписки
                subscribe_kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💎 Оформить подписку", callback_data="pay_subscription")]
                ])

                await bot.send_message(
                    user_id,
                    promo_msg,
                    parse_mode="HTML",
                    reply_markup=subscribe_kb
                )
                sent_count += 1
                logging.info(f"[BROADCAST] Отправлено пользователю {profile.get('name', user_id)}")
                await asyncio.sleep(1.0)  # Задержка для API лимитов
            except Exception as e:
                logging.error(f"[BROADCAST ERROR] User {user_id}: {e}")
                continue

        logging.info(f"[BROADCAST] Отправлено {sent_count} персонализированных сообщений")
        return sent_count
    except Exception as e:
        logging.error(f"[BROADCAST ERROR] {e}")
        return 0

async def subscription_reminder_scheduler():
    """Планировщик рассылки: первая через 30 мин, далее каждые N часов"""
    global AUTO_BROADCAST_ENABLED, BROADCAST_INTERVAL_HOURS
    first_run = True
    while True:
        try:
            if first_run:
                logging.info("[SCHEDULER] Первая рассылка через 30 минут...")
                await asyncio.sleep(30 * 60)  # 30 минут
                first_run = False
            else:
                await asyncio.sleep(BROADCAST_INTERVAL_HOURS * 3600)  # N часов

            if not AUTO_BROADCAST_ENABLED:
                logging.info("[SCHEDULER] Авто-рассылка отключена, пропускаем...")
                continue

            logging.info("[SCHEDULER] Запуск персонализированной рассылки...")
            sent = await broadcast_to_non_subscribers()
            logging.info(f"[SCHEDULER] Рассылка завершена: {sent} персональных сообщений")

        except Exception as e:
            logging.error(f"[SCHEDULER ERROR] {e}")
            await asyncio.sleep(3600)  # При ошибке подождать 1 час

async def send_subscription_reminders():
    """Отправляет уведомления за 2 дня и 1 час до окончания подписки"""
    now = int(datetime.now().timestamp())
    two_days = now + 2 * 24 * 3600  # +2 дня
    one_hour = now + 3600  # +1 час

    async with aiosqlite.connect(DB_PATH) as db:
        # Уведомление за 2 дня
        async with db.execute(
            '''SELECT user_id, name, subscription_until FROM users
               WHERE subscription_until BETWEEN ? AND ?
               AND notified_2d IS NULL''',
            (now, two_days)
        ) as cursor:
            users_2d = await cursor.fetchall()

        # Уведомление за 1 час
        async with db.execute(
            '''SELECT user_id, name, subscription_until FROM users
               WHERE subscription_until BETWEEN ? AND ?
               AND notified_1h IS NULL''',
            (now, one_hour)
        ) as cursor:
            users_1h = await cursor.fetchall()

        # Отправляем уведомления за 2 дня
        for user_id, name, sub_until in users_2d:
            try:
                await bot.send_message(
                    user_id,
                    "⏰ <b>До окончания действия тарифа осталось 2 дня</b>\n\n"
                    "Не забудьте продлить подписку, чтобы не потерять доступ к каналу!",
                    parse_mode="HTML"
                )
                await db.execute('UPDATE users SET notified_2d = ? WHERE user_id = ?', (now, user_id))
                logging.info(f"[REMINDER] Отправлено уведомление за 2 дня: {name}")
            except Exception as e:
                logging.error(f"[REMINDER] Ошибка отправки за 2 дня: {e}")

        # Отправляем уведомления за 1 час
        for user_id, name, sub_until in users_1h:
            try:
                await bot.send_message(
                    user_id,
                    "⚠️ <b>До окончания тарифа осталось совсем немного!</b>\n\n"
                    "Не забудьте продлить подписку, чтобы не потерять доступ к каналу!",
                    parse_mode="HTML"
                )
                await db.execute('UPDATE users SET notified_1h = ? WHERE user_id = ?', (now, user_id))
                logging.info(f"[REMINDER] Отправлено уведомление за 1 час: {name}")
            except Exception as e:
                logging.error(f"[REMINDER] Ошибка отправки за 1 час: {e}")

        await db.commit()

async def subscription_notification_scheduler():
    """Планировщик уведомлений о скором истечении подписки - каждый час"""
    while True:
        try:
            await asyncio.sleep(3600)  # Проверка каждый час
            await send_subscription_reminders()
        except Exception as e:
            logging.error(f"[NOTIFICATION ERROR] {e}")
            await asyncio.sleep(3600)

async def check_and_kick_expired_users():
    """Проверяет истёкшие подписки и кикает из канала"""
    now = int(datetime.now().timestamp())
    logging.info(f"[CHECKER] Проверка истёкших подписок... (now={now})")

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            '''SELECT user_id, name, subscription_until FROM users
               WHERE subscription_until IS NOT NULL
               AND subscription_until < ?
               AND subscription_until > 0''',
            (now,)
        ) as cursor:
            expired_users = await cursor.fetchall()

    logging.info(f"[CHECKER] Найдено {len(expired_users)} истёкших подписок")

    kicked = 0
    for user_id, name, sub_until in expired_users:
        logging.info(f"[CHECKER] Обрабатываю {name} (ID: {user_id}), подписка до {sub_until}")
        try:
            # Проверяем статус в канале
            try:
                member = await bot.get_chat_member(CHANNEL_ID, user_id)
                status = member.status
                logging.info(f"[CHECKER] {name} статус в канале: {status}")

                if status in ['administrator', 'creator']:
                    logging.info(f"[KICK] Пропускаем {name} - админ канала")
                    continue
                if status in ['left', 'kicked', 'restricted']:
                    logging.info(f"[KICK] Пропускаем {name} - уже не в канале ({status})")
                    # Обнуляем subscription_until чтобы не проверять повторно
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute('UPDATE users SET subscription_until = 0 WHERE user_id = ?', (user_id,))
                        await db.commit()
                    continue
            except Exception as e:
                logging.info(f"[KICK] {name} не найден в канале: {e}")
                continue

            # Кикаем из канала
            logging.info(f"[KICK] Кикаю {name} из канала...")
            try:
                await bot.ban_chat_member(
                    chat_id=CHANNEL_ID,
                    user_id=user_id,
                    until_date=timedelta(seconds=60)
                )
                kicked += 1
                logging.info(f"[KICK] Успешно кикнут {name} (ID: {user_id})")
            except Exception as ban_err:
                logging.warning(f"[KICK] Не удалось кикнуть {name}: {ban_err}")
                # Уведомляем админов что нужно кикнуть вручную
                for admin_id in ADMIN_IDS:
                    try:
                        await bot.send_message(
                            admin_id,
                            f"⚠️ <b>Требуется ручной кик!</b>\n\n"
                            f"Подписка истекла у: {name}\n"
                            f"ID: <code>{user_id}</code>\n\n"
                            f"Бот не смог удалить из канала автоматически.",
                            parse_mode="HTML"
                        )
                    except:
                        pass

            # Обнуляем подписку и устанавливаем grace period для пользователей со special_price
            async with aiosqlite.connect(DB_PATH) as db:
                # Проверяем, есть ли special_price
                async with db.execute('SELECT special_price FROM users WHERE user_id = ?', (user_id,)) as cursor:
                    row = await cursor.fetchone()
                    has_special_price = row and row[0] is not None

                if has_special_price:
                    # Устанавливаем grace period на 7 дней
                    grace_until = int((datetime.now() + timedelta(days=7)).timestamp())
                    await db.execute(
                        'UPDATE users SET subscription_until = 0, grace_period_until = ? WHERE user_id = ?',
                        (grace_until, user_id)
                    )
                    logging.info(f"[GRACE] Установлен льготный период для {name} до {grace_until}")
                else:
                    await db.execute('UPDATE users SET subscription_until = 0 WHERE user_id = ?', (user_id,))

                await db.commit()

            # Уведомляем пользователя
            try:
                # Проверяем снова, есть ли у пользователя special_price для персонализации сообщения
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute('SELECT special_price, grace_period_until FROM users WHERE user_id = ?', (user_id,)) as cursor:
                        row = await cursor.fetchone()
                        special_price = row[0] if row else None
                        grace_period_until = row[1] if row else None

                if special_price and grace_period_until and grace_period_until > now:
                    # Пользователь со special_price - льготное сообщение
                    grace_date = datetime.fromtimestamp(grace_period_until).strftime('%d.%m.%Y')
                    await bot.send_message(
                        user_id,
                        f"⏰ <b>Ваша подписка истекла!</b>\n\n"
                        f"🎁 Для вас сохранена специальная цена <b>{special_price} ₽</b> до <b>{grace_date}</b>\n\n"
                        f"Продлите подписку по выгодной цене, пока действует предложение!",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="💎 Продлить по спец.цене", callback_data="pay_subscription")]
                        ])
                    )
                else:
                    await bot.send_message(
                        user_id,
                        "⏰ <b>Ваша подписка истекла!</b>\n\n"
                        "Доступ к закрытому каналу ограничен.\n"
                        "Чтобы продлить подписку, нажмите кнопку ниже:",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text="💎 Продлить подписку", callback_data="pay_subscription")]
                        ])
                    )
            except:
                pass
        except Exception as e:
            logging.error(f"[KICK ERROR] Не удалось кикнуть {user_id}: {e}")

    return kicked

async def subscription_checker_scheduler():
    """Проверка истёкших подписок каждую минуту"""
    logging.info("[CHECKER] Планировщик запущен, первая проверка через 30 сек...")
    await asyncio.sleep(30)  # Первая проверка через 30 сек
    while True:
        try:
            kicked = await check_and_kick_expired_users()
            if kicked > 0:
                logging.info(f"[CHECKER] Кикнуто {kicked} пользователей")
        except Exception as e:
            logging.error(f"[CHECKER ERROR] {e}")
        await asyncio.sleep(60)  # Каждую минуту

async def update_phone(user_id: int, phone: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE users SET phone = ? WHERE user_id = ?', (phone, user_id))
        await db.commit()

async def activate_subscription(user_id: int, days: int = 30, amount: int = 0):
    sub_until = int((datetime.now() + timedelta(days=days)).timestamp())
    grace_until = sub_until + 7 * 24 * 3600  # +7 дней для сохранения цены
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'UPDATE users SET subscription_until = ?, grace_period_until = ?, notified_2d = NULL, notified_1h = NULL WHERE user_id = ?',
            (sub_until, grace_until, user_id)
        )

        # Начисление 10% рефереру
        if amount > 0:
            async with db.execute('SELECT referrer_id FROM referrals WHERE referred_id = ?', (user_id,)) as cursor:
                ref_row = await cursor.fetchone()
                if ref_row:
                    referrer_id = ref_row[0]
                    commission = amount * 0.1
                    await db.execute(
                        'UPDATE users SET referral_earnings = referral_earnings + ? WHERE user_id = ?',
                        (commission, referrer_id)
                    )
                    # Уведомляем реферера о начислении
                    try:
                        await bot.send_message(
                            referrer_id,
                            f"💰 Вам начислено {commission:.2f}₽ за приглашенного друга!\n\n"
                            f"Ваш реферал оформил подписку."
                        )
                    except:
                        pass

        await db.commit()

        # Уведомляем админов о новом подписчике
        async with db.execute('SELECT name, username FROM users WHERE user_id = ?', (user_id,)) as cursor:
            user_row = await cursor.fetchone()
            name = user_row[0] if user_row else "Неизвестно"
            username = user_row[1] if user_row and user_row[1] else "нет"

        for admin_id in ADMIN_IDS:
            try:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="👤 Открыть профиль", url=f"tg://user?id={user_id}")]
                ])
                await bot.send_message(
                    admin_id,
                    f"🎉 Новый подписчик!\n\n"
                    f"👤 Имя: {name}\n"
                    f"🆔 User ID: {user_id}\n"
                    f"📱 Username: @{username}\n"
                    f"💰 Сумма: {amount}₽",
                    reply_markup=kb
                )
            except:
                pass

    try:
        await bot.unban_chat_member(CHANNEL_ID, user_id)
        invite_link = await bot.create_chat_invite_link(CHANNEL_ID, member_limit=1)
        return invite_link.invite_link
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        return None

async def get_welcome_photo() -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT value FROM settings WHERE key = ?', ('welcome_photo',)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def set_welcome_photo(file_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', ('welcome_photo', file_id))
        await db.commit()

async def get_welcome_video() -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT value FROM settings WHERE key = ?', ('welcome_video',)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def set_welcome_video(file_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', ('welcome_video', file_id))
        await db.commit()

async def get_welcome_media_type() -> str:
    """Возвращает тип приветственного медиа: 'video', 'photo' или None"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT value FROM settings WHERE key = ?', ('welcome_media_type',)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def set_welcome_media_type(media_type: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', ('welcome_media_type', media_type))
        await db.commit()

async def get_price() -> int:
    """Получить текущую цену подписки"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT value FROM settings WHERE key = ?', ('price',)) as cursor:
            row = await cursor.fetchone()
            return int(row[0]) if row else PRICE_1_MONTH

async def set_price(price: int):
    """Установить цену подписки"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', ('price', str(price)))
        await db.commit()

async def get_user_price(user_id: int) -> int:
    """
    Получить цену для конкретного пользователя
    Проверяет special_price и grace_period
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT special_price, grace_period_until FROM users WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()

            if row:
                special_price = row[0]
                grace_period_until = row[1]
                current_time = int(datetime.now().timestamp())

                # Если есть специальная цена и пользователь в льготном периоде
                if special_price and grace_period_until and grace_period_until > current_time:
                    return special_price

    # Иначе возвращаем обычную цену
    return await get_price()

async def get_channel_link() -> str:
    """Получить ссылку на канал"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT value FROM settings WHERE key = ?', ('channel_link',)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def set_channel_link(link: str):
    """Установить ссылку на канал"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', ('channel_link', link))
        await db.commit()

async def get_paid_video() -> str:
    """Получить file_id видео для оплативших"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT value FROM settings WHERE key = ?', ('paid_video',)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def set_paid_video(file_id: str):
    """Установить видео для оплативших"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', ('paid_video', file_id))
        await db.commit()

async def get_secret_word() -> str:
    """Получить кодовое слово"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT value FROM settings WHERE key = ?', ('secret_word',)) as cursor:
            row = await cursor.fetchone()
            return row[0].lower() if row else "толчок"

async def set_secret_word(word: str):
    """Установить кодовое слово"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', ('secret_word', word.lower()))
        await db.commit()

async def generate_one_time_invite() -> str:
    """Генерирует одноразовую ссылку-приглашение в канал"""
    try:
        logging.info(f"Создаю invite для канала {CHANNEL_ID}")
        invite = await bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1,  # Одноразовая ссылка
            name=f"Invite {datetime.now().strftime('%H:%M')}"
        )
        logging.info(f"Invite создан: {invite.invite_link}")
        return invite.invite_link
    except Exception as e:
        logging.error(f"Ошибка создания инвайт-ссылки для {CHANNEL_ID}: {e}")
        # Пробуем альтернативный способ - экспорт основной ссылки
        try:
            link = await bot.export_chat_invite_link(chat_id=CHANNEL_ID)
            logging.info(f"Экспортирована основная ссылка: {link}")
            return link
        except Exception as e2:
            logging.error(f"Альтернативный способ тоже не сработал: {e2}")
            return None

async def save_message_to_history(user_id: int, message: str):
    """Сохраняет хеш сообщения в историю"""
    msg_hash = str(hash(message) % 100000)
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                'INSERT INTO message_history (user_id, message_hash, sent_at) VALUES (?, ?, ?)',
                (user_id, msg_hash, int(datetime.now().timestamp()))
            )
            await db.commit()
        except:
            pass  # Дубликат - игнорируем

async def was_message_sent(user_id: int, message: str) -> bool:
    """Проверяет, было ли отправлено такое сообщение пользователю"""
    msg_hash = str(hash(message) % 100000)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT 1 FROM message_history WHERE user_id = ? AND message_hash = ?',
            (user_id, msg_hash)
        ) as cursor:
            return await cursor.fetchone() is not None

async def generate_personalized_message(profile: dict) -> str:
    """Мощный автономный ИИ-генератор персонализированных сообщений"""
    name = profile['name']
    age = profile['age']
    goal = profile['goal']
    level = profile['level']
    training = profile['weekly_training']
    lifestyle = profile['lifestyle']
    recovery = profile['recovery']
    region = profile.get('region', '')
    injuries = profile.get('injuries', '')
    tours = profile.get('tours', '')

    # Хеш для уникальности
    profile_hash = hash(str(profile)) % 1000

    # === ПРИВЕТСТВИЯ (30+ вариантов) ===
    greetings_novice = [
        f"🎿 {name}, ты делаешь первые шаги в лыжном мире!",
        f"🌱 {name}, каждый профи когда-то начинал с нуля!",
        f"⛷ {name}, отличное время начать — впереди столько открытий!",
        f"❄️ {name}, твой путь только начинается, и это круто!",
        f"🚀 {name}, новички прогрессируют быстрее всех!",
        f"✨ {name}, ты в начале пути, где каждый шаг — победа!",
        f"🎯 {name}, правильное решение стартовать системно!",
        f"💪 {name}, у новичков самый быстрый прогресс!",
        f"🏔 {name}, горы начинаются с первого шага!",
        f"⚡ {name}, энтузиазм новичка — твоя суперсила!"
    ]

    greetings_amateur = [
        f"⭐ {name}, твоя база — отличный фундамент!",
        f"💪 {name}, ты уже многое знаешь, время расти дальше!",
        f"🎯 {name}, твой опыт стоит развивать системно!",
        f"🔥 {name}, любители часто обгоняют профи в мотивации!",
        f"🚴 {name}, ты уже не новичок — используй это!",
        f"🏆 {name}, твой уровень позволяет брать серьёзные цели!",
        f"⚙️ {name}, пора выводить катание на новый уровень!",
        f"🎿 {name}, у тебя есть база — теперь добавим систему!",
        f"💎 {name}, шлифовка техники даст тебе крылья!",
        f"🌟 {name}, любительский уровень — это уже достижение!"
    ]

    greetings_pro = [
        f"🏅 {name}, твой уровень впечатляет!",
        f"🚀 {name}, ты среди лучших!",
        f"⚡ {name}, профи знают цену деталям!",
        f"🔝 {name}, твой опыт — это сила!",
        f"💎 {name}, на твоём уровне важна точность!",
        f"🎖 {name}, профессионализм — твоя визитка!",
        f"⭐ {name}, ты в топе — продолжай совершенствоваться!",
        f"🏔 {name}, на вершине всегда есть куда расти!",
        f"🎯 {name}, твоя техника говорит сама за себя!",
        f"👑 {name}, профи никогда не останавливаются!"
    ]

    # === МОТИВАЦИЯ (40+ вариантов) ===
    motivations_by_level = {
        'новичок': [
            "Первые месяцы — это взрыв прогресса, если делать правильно.",
            "Новички растут быстрее всех, главное — не торопиться.",
            "Техника с самого начала экономит годы исправления ошибок.",
            "Твой чистый лист — преимущество, не нужно ничего переучивать.",
            "Каждая тренировка приносит видимый результат на старте.",
            "Правильная база сейчас = лёгкое катание через год.",
            "Ты удивишься, как быстро тело учится новым движениям.",
            "Первый сезон определяет всю технику на годы вперёд.",
            "Системный подход на старте даёт фундамент на всю жизнь.",
            "Не спеши, качество важнее километража."
        ],
        'любитель': [
            "Твой опыт — это платформа для серьёзного роста.",
            "Любители с системой обгоняют профи без неё.",
            "Шлифовка деталей даёт больше, чем километры.",
            "Ты уже понимаешь, что важно — используй это.",
            "На твоём уровне маленькие улучшения дают большой эффект.",
            "Твоя техника может стать оружием с правильной работой.",
            "Опыт + система = прорыв в результатах.",
            "Ты знаешь основы, теперь пора углубляться.",
            "Любительский уровень — это баланс удовольствия и прогресса.",
            "С твоей базой можно идти на серьёзные цели."
        ],
        'профи': [
            "На твоём уровне детали решают всё.",
            "Профи растут медленнее, но каждый процент на вес золота.",
            "Твой опыт позволяет видеть то, что скрыто от других.",
            "Экономичность движений — главное оружие профессионала.",
            "Ты понимаешь, что совершенству нет предела.",
            "Твоя техника — результат тысяч часов работы.",
            "На вершине важна не сила, а точность.",
            "Профессионализм — это постоянная работа над собой.",
            "Ты знаешь, что мелочи создают большую картину.",
            "Твой уровень требует индивидуального подхода."
        ]
    }

    # === СОВЕТЫ (60+ вариантов) ===
    advices_detailed = {
        'новичок': [
            "Первые 2 месяца — только классический ход на ровной местности",
            "Упражнения на баланс дома: стоять на одной ноге 30 сек × 3 подхода",
            "Короткие тренировки 20-30 минут эффективнее длинных на старте",
            "Смотри видео своей техники — это открывает глаза",
            "Первые 10 тренировок важнее следующих 100",
            "Отработай перенос веса перед скоростью",
            "Имитация дома 10 минут = полчаса на лыжах",
            "Не гонись за километрами, отрабатывай элементы",
            "Найди пологий склон и катайся без палок",
            "Техника отталкивания важнее силы ног"
        ],
        'любитель': [
            "Интервалы 4×4 минуты раз в неделю взорвут выносливость",
            "Работай над фазой проката — там теряется скорость",
            "Снимай на видео и сравнивай с профи",
            "Силовые 2 раза в неделю: приседания, выпады, планка",
            "Коньковый ход на подъёме — лучшая тренировка техники",
            "Раз в месяц делай тренировку только на технику без скорости",
            "Работа рук решает 30% скорости — не забывай про них",
            "Длинные раскаты на выходных + короткие интервалы в будни",
            "Отработай двухшажный коньковый до автоматизма",
            "Следи за пульсом: 80% времени в зоне комфорта"
        ],
        'профи': [
            "Скоростно-силовые: 10 подходов × 30 сек с весом",
            "Анализируй экономичность: считай толчки на километр",
            "Работай над асимметрией — снимай толчки слева/справа",
            "Плиометрика 2 раза в неделю для взрывной силы",
            "Включай тренировки в пульсовой зоне 5 — но дозировано",
            "Оттачивай переход с хода на ход на скорости",
            "Восстановительные тренировки так же важны, как ударные",
            "Работай с данными: мощность, каденс, ЧСС",
            "Специфичные упражнения: имитация на роликах с палками",
            "Микропериодизация: меняй нагрузку каждые 3-4 дня"
        ]
    }

    # === ДОПОЛНИТЕЛЬНЫЕ ИНСАЙТЫ (40+ вариантов) ===
    insights_training_low = [
        "Даже 2 тренировки в неделю дают результат при качественном подходе",
        "Лучше 2 раза качественно, чем 5 раз спустя рукава",
        "Попробуй добавить одну короткую тренировку — эффект будет заметен",
        "Нехватка времени не приговор — важна интенсивность",
        "20 минут интервалов заменяют час спокойного катания"
    ]

    insights_training_high = [
        "Частые тренировки — твоё преимущество, главное не перегореть",
        "При таком графике важно варьировать нагрузку",
        "Больше 5 тренировок в неделю? Обязательно включи восстановительные",
        "Твоя частота позволяет работать над деталями каждый день",
        "Качество важнее количества даже при высокой частоте"
    ]

    insights_lifestyle_sedentary = [
        "Сидячая работа требует компенсации — разминка каждые 2 часа по 5 минут",
        "Добавь упражнения на мобильность перед сном",
        "Офисный стул — враг спины: делай 'кошку' и 'собаку' утром",
        "Постоянное сидение укорачивает мышцы — растяжка обязательна",
        "Прогулка 15 минут в обед творит чудеса"
    ]

    insights_recovery_chaos = [
        "Хаос в восстановлении убивает 50% результата тренировок",
        "Сон 7-8 часов — не роскошь, а необходимость для прогресса",
        "Недосып = падение выносливости на 20-30%",
        "Наладь хотя бы питание в дни тренировок — это база",
        "Восстановление — это когда растут мышцы, а не на тренировке"
    ]

    insights_recovery_pro = [
        "Осознанное восстановление — признак профессионализма",
        "Ты понимаешь главное: результат делается во сне",
        "Твой подход к восстановлению продлит карьеру на годы",
        "Баня, массаж, растяжка — твои инвестиции в долголетие",
        "Профи восстанавливаются так же усердно, как тренируются"
    ]

    # === РЕГИОНАЛЬНЫЕ ИНСАЙТЫ ===
    insights_region = {
        'север': ["В твоём регионе сезон длинный — используй это преимущество", "Северные условия закаляют характер и технику"],
        'средняя': ["Средняя полоса — золотая середина для тренировок", "У тебя доступ к разным рельефам — пользуйся"],
        'центральный': ["Центральный регион даёт хорошие условия для стабильных тренировок", "Близость к крупным центрам — больше возможностей для развития"],
        'юг': ["Короткий сезон требует плотной работы", "Летом роллеры и имитация — твои друзья"]
    }

    # === ЦЕЛЕВЫЕ СООБЩЕНИЯ ===
    goal_messages = {
        'техника': [
            "Видеосъёмка — твой главный тренер. Снимай каждую тренировку",
            "Техника = экономия сил. Один процент улучшения даёт километры в запасе",
            "Работай над элементами отдельно, потом соединяй в целое",
            "Смотри профи в слоу-мо: детали, которые не видны на скорости"
        ],
        'соревнования': [
            "Соревновательные отрезки в каждой 3-й тренировке обязательны",
            "Туры — лучшая подготовка к стартам. Это и тренировка, и опыт",
            "Психология гонки тренируется только в гонках",
            "Анализируй каждый старт: что сработало, что нет"
        ],
        'знания': [
            "Теория без практики мертва, но практика без теории слепа",
            "Понимание физиологии удваивает эффект тренировок",
            "Знания дают осознанность, осознанность даёт контроль",
            "Изучай не только технику, но и биомеханику"
        ],
        'себя': [
            "Катание для себя — не значит без системы",
            "Кайф от движения растёт с техникой",
            "Тренируешься для удовольствия? Делай это качественно",
            "Лёгкое скольжение — результат правильной техники"
        ]
    }

    # === ПРИЗЫВЫ К ДЕЙСТВИЮ (20+ вариантов) ===
    ctas = [
        "👉 В Кафедре — готовые тренировочные планы под твой уровень",
        "👉 В Кафедре — разборы техники от тренера сборной России",
        "👉 Присоединяйся к Кафедре — система уже ждёт",
        "👉 В Кафедре — теория + практика в одном месте",
        "👉 Эфиры с Алексеем Торицыным раз в месяц только в Кафедре",
        "👉 Кафедра — это твоя персональная система роста",
        "👉 В Кафедре ты получишь ответы на все вопросы",
        "👉 Туры Кафедры — лучший способ применить знания",
        "👉 Система Кафедры работает для любого уровня",
        "👉 В Кафедре — сообщество единомышленников"
    ]

    # === УМНЫЙ ВЫБОР С АНТИПОВТОРОМ ===
    idx = profile_hash

    if level == 'новичок':
        greeting = greetings_novice[idx % len(greetings_novice)]
        motivation = motivations_by_level['новичок'][(idx+1) % len(motivations_by_level['новичок'])]
        advice = advices_detailed['новичок'][(idx+2) % len(advices_detailed['новичок'])]
    elif level == 'любитель':
        greeting = greetings_amateur[idx % len(greetings_amateur)]
        motivation = motivations_by_level['любитель'][(idx+1) % len(motivations_by_level['любитель'])]
        advice = advices_detailed['любитель'][(idx+2) % len(advices_detailed['любитель'])]
    else:
        greeting = greetings_pro[idx % len(greetings_pro)]
        motivation = motivations_by_level['профи'][(idx+1) % len(motivations_by_level['профи'])]
        advice = advices_detailed['профи'][(idx+2) % len(advices_detailed['профи'])]

    # Дополнительные инсайты
    extra_insights = []

    if '<3' in training:
        extra_insights.append(insights_training_low[(idx+3) % len(insights_training_low)])
    else:
        extra_insights.append(insights_training_high[(idx+3) % len(insights_training_high)])

    if lifestyle == 'сидячий':
        extra_insights.append(insights_lifestyle_sedentary[(idx+4) % len(insights_lifestyle_sedentary)])

    if recovery == 'хаос':
        extra_insights.append(insights_recovery_chaos[(idx+5) % len(insights_recovery_chaos)])
    elif recovery == 'про':
        extra_insights.append(insights_recovery_pro[(idx+5) % len(insights_recovery_pro)])

    if region and region in insights_region:
        extra_insights.append(insights_region[region][(idx+6) % len(insights_region[region])])

    # Целевое сообщение
    goal_msg = ""
    if 'техника' in goal and goal_messages['техника']:
        goal_msg = goal_messages['техника'][(idx+7) % len(goal_messages['техника'])]
    elif 'соревнования' in goal and goal_messages['соревнования']:
        goal_msg = goal_messages['соревнования'][(idx+7) % len(goal_messages['соревнования'])]
    elif 'знания' in goal and goal_messages['знания']:
        goal_msg = goal_messages['знания'][(idx+7) % len(goal_messages['знания'])]
    else:
        goal_msg = goal_messages['себя'][(idx+7) % len(goal_messages['себя'])]

    cta = ctas[(idx+8) % len(ctas)]

    # === СБОРКА СООБЩЕНИЯ ===
    msg_parts = [greeting, "", motivation, "", f"💡 {advice}"]

    if extra_insights:
        msg_parts.append("")
        msg_parts.extend([f"▪️ {ins}" for ins in extra_insights[:2]])  # Максимум 2 доп инсайта

    if goal_msg:
        msg_parts.append("")
        msg_parts.append(f"🎯 {goal_msg}")

    msg_parts.append("")
    msg_parts.append(cta)

    return "\n".join(msg_parts)
async def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Извлекает текст из PDF файла"""
    try:
        pdf_file = io.BytesIO(file_bytes)
        pdf_reader = PyPDF2.PdfReader(pdf_file)

        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"

        return text.strip()
    except Exception as e:
        logging.error(f"Ошибка извлечения текста из PDF: {e}")
        return ""

async def structure_training_content(text: str) -> dict:
    """AI обработка текста тренировок и создание структурированного контента"""

    # Разбиваем текст на секции
    lines = text.split('\n')

    # Ищем заголовок и даты
    title = ""
    dates = []
    trainings = []

    for i, line in enumerate(lines):
        line_clean = line.strip()

        # Ищем заголовок
        if 'ПЛАН' in line_clean.upper() or 'ТРЕНИРОВОЧНЫЙ' in line_clean.upper():
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and len(next_line) < 50:
                    title = next_line

        # Ищем даты и тренировки
        if any(char.isdigit() for char in line_clean):
            # Проверяем формат даты (XX.XX)
            parts = line_clean.split()
            for part in parts:
                if '.' in part and any(c.isdigit() for c in part):
                    dates.append(part)

        # Ищем описание тренировок
        if ('Тренировка' in line_clean or 'тренировка' in line_clean or
            'Зарядка' in line_clean or 'ОРУ' in line_clean or
            'Многофункциональный' in line_clean):

            # Собираем блок тренировки
            training_block = []
            j = i
            while j < len(lines) and j < i + 15:
                current_line = lines[j].strip()
                if current_line:
                    training_block.append(current_line)
                    if current_line.startswith('•') or current_line.startswith('-'):
                        j += 1
                    elif j > i and (current_line.startswith('Зарядка') or
                                   current_line.startswith('Тренировка') or
                                   any(d in current_line for d in ['отдых', 'Отдых'])):
                        break
                    else:
                        j += 1
                else:
                    j += 1

            if training_block:
                trainings.append('\n'.join(training_block))

    # Формируем структурированный результат
    result = {
        'title': title or 'Тренировочный план',
        'description': f"План содержит {len(trainings)} тренировок",
        'trainings': trainings[:20],  # Ограничиваем 20 тренировками
        'dates': dates[:30]
    }

    return result

async def generate_test_feedback(profile: dict) -> str:
    """Детальный автономный ИИ-анализ профиля после теста"""
    name = profile['name']
    level = profile['level']
    training = profile['weekly_training']
    injuries = profile['injuries']
    lifestyle = profile['lifestyle']
    recovery = profile['recovery']
    goal = profile['goal']
    age = profile.get('age', 0)
    region = profile.get('region', '')

    # Хеш для уникальности
    profile_hash = hash(str(profile)) % 1000

    # === НАЧАЛЬНЫЕ ФРАЗЫ (20+ вариантов) ===
    openings = [
        f"✅ {name}, отлично! Я проанализировал твой профиль.",
        f"✅ {name}, твои ответы зафиксированы. Вот что я увидел.",
        f"✅ Спасибо за ответы, {name}! Анализ готов.",
        f"✅ {name}, я составил для тебя персональную карту роста.",
        f"✅ {name}, на основе твоих данных готов план действий.",
        f"✅ Отлично, {name}! Твой профиль даёт мне много информации.",
        f"✅ {name}, я вижу твои сильные стороны и точки роста.",
        f"✅ {name}, анализ завершён. У меня есть рекомендации для тебя."
    ]

    # === РЕКОМЕНДАЦИИ ПО УРОВНЮ (30+ для каждого уровня) ===
    recs_by_level = {
        'новичок': [
            "Баланс — твоя главная задача. Упражнения: стоять на одной ноге 30 сек × 5 подходов ежедневно",
            "Первые 20 тренировок — только классический ход на ровной местности, без скорости",
            "Техника переноса веса важнее километража. Отрабатывай каждое движение медленно",
            "Короткие тренировки 20-30 минут 3 раза в неделю дадут больше, чем 2 часа раз в неделю",
            "Имитация дома 10 минут = 30 минут на лыжах. Делай каждый день",
            "Снимай себя на видео с первых тренировок. Ошибки легче исправить сразу",
            "Не спеши на коньковый ход. Классика строит правильную базу",
            "Найди пологий склон и откатывай спуски без палок — это прокачает баланс",
            "Первые 10 тренировок важнее следующих 100. Формируется мышечная память",
            "Отталкивание ногой — ключевой элемент. Чувствуй полный перенос веса"
        ],
        'любитель': [
            "Интервалы 4×4 минуты в зоне порога раз в неделю взорвут выносливость",
            "Работай над фазой скольжения — там теряется 30-40% скорости у любителей",
            "Силовые тренировки 2 раза в неделю: приседания, выпады, планка — база для лыж",
            "Снимай технику на видео и сравнивай с профи. Находи отличия",
            "Коньковый ход на подъёме — лучший тренажёр для техники и силы",
            "Один раз в месяц делай тренировку ТОЛЬКО на технику, забудь про скорость",
            "Работа рук даёт 30% скорости. Отрабатывай отталкивание палками отдельно",
            "Длинные раскаты (1.5-2 часа) на выходных + короткие интервалы (40 мин) в будни",
            "Двухшажный коньковый — твоя база. Отточи его до автоматизма",
            "Следи за пульсом: 80% времени в зонах 2-3, 20% — интенсив"
        ],
        'профи': [
            "Скоростно-силовые комплексы: 10×30 сек с весом, отдых 3 минуты",
            "Анализируй экономичность: считай количество толчков на километр и снижай",
            "Работай над асимметрией — снимай на видео толчки слева и справа, ищи дисбаланс",
            "Плиометрика 2 раза в неделю: прыжки в глубину, выпрыгивания, спринты в гору",
            "Пульсовая зона 5 (90-95% ЧССмакс) — не чаще раза в неделю, восстановление 48 часов",
            "Отточи переходы с хода на ход на полной скорости — это даёт секунды на финише",
            "Восстановительные тренировки так же важны, как ударные. Зона 1-2, 60-90 минут",
            "Собирай данные: мощность, каденс, ЧСС, лактат. Без цифр нет прогресса",
            "Имитация на роликах с палками — максимально специфичная тренировка летом",
            "Микропериодизация: 3 дня нагрузка — 1 день восстановление"
        ]
    }

    # === РЕКОМЕНДАЦИИ ПО ТРЕНИРОВКАМ (15+) ===
    recs_training = {
        'low': [
            "При 2 тренировках в неделю делай одну длинную (1.5-2ч), одну интервальную (40-50 мин)",
            "Нехватка времени? 20 минут интенсива эффективнее часа спокойного катания",
            "Добавь третью короткую тренировку (30 мин) — прогресс ускорится на 40%",
            "Качество важнее количества. Лучше 2 раза в неделю с полной отдачей",
            "При редких тренировках фокусируйся на технике, не на километраже"
        ],
        'high': [
            "При частых тренировках чередуй нагрузку: лёгкая — средняя — тяжёлая — восстановительная",
            "Более 5 тренировок в неделю? Минимум 2 должны быть восстановительными",
            "Риск перетренированности растёт. Следи за утренним пульсом — рост на 10% = нужен отдых",
            "Частота даёт возможность работать над деталями каждый день",
            "Больше — не всегда лучше. Качество тренировки важнее их количества"
        ]
    }

    # === РЕКОМЕНДАЦИИ ПО ОБРАЗУ ЖИЗНИ (20+) ===
    recs_lifestyle = {
        'сидячий': [
            "Сидячая работа укорачивает мышцы. Обязательна растяжка утром (10 мин) и вечером (10 мин)",
            "Каждые 2 часа вставай и делай 5-минутную разминку: приседания, выпады, наклоны",
            "Упражнения 'кошка-собака', 'мостик', 'поза ребёнка' — твои must have утром",
            "15-минутная прогулка в обед компенсирует 4 часа сидения",
            "Офисный стул — враг поясницы и тазобедренных. Мобильность — твой приоритет"
        ],
        'active': [
            "Твоя активность — огромный плюс. Следи, чтобы она не превращалась в перегрузку",
            "Активный образ жизни даёт тебе преимущество в адаптации к нагрузкам",
            "При высокой активности особенно важно качественное восстановление"
        ]
    }

    # === РЕКОМЕНДАЦИИ ПО ВОССТАНОВЛЕНИЮ (20+) ===
    recs_recovery = {
        'хаос': [
            "Хаос в восстановлении убивает 50% результата тренировок. Приоритет №1 — наладить режим",
            "Сон менее 7 часов = падение выносливости на 20-30%, рост травматизма на 60%",
            "Начни с малого: ложись в одно время 5 дней подряд. Организм привыкнет за неделю",
            "Питание в дни тренировок — это твоё топливо. Углеводы до, белок после",
            "Лёгкая растяжка 10 минут перед сном улучшает качество восстановления",
            "Недосып нельзя компенсировать. Мышцы растут во сне, не на тренировке"
        ],
        'норма': [
            "Ты следишь за базовыми вещами — это хорошо. Можно улучшить детали",
            "Добавь баню или контрастный душ раз в неделю — ускорит восстановление",
            "Попробуй вести дневник сна и самочувствия — увидишь закономерности",
            "Массаж или миофасциальный релиз 1-2 раза в неделю снимут накопленное напряжение"
        ],
        'про': [
            "Твой подход к восстановлению — уровень профи. Продолжай в том же духе",
            "Осознанное восстановление продлевает спортивное долголетие на годы",
            "Ты понимаешь главное: результат делается во сне, а не на тренировке",
            "Баня, массаж, растяжка, сон — твои инвестиции в многолетний прогресс"
        ]
    }

    # === РЕКОМЕНДАЦИИ ПО ЦЕЛЯМ (15+) ===
    recs_goals = {
        'техника': [
            "Снимай каждую тренировку на видео. Что не снято — не проанализировано",
            "Техника = экономия сил. 1% улучшения техники даёт 2-3% прироста скорости",
            "Работай над элементами отдельно: отталкивание, скольжение, работа рук",
            "Смотри профи в слоу-мо на YouTube — детали, которые не видны на скорости",
            "Найди тренера хотя бы на 3-5 занятий. Внешний взгляд бесценен"
        ],
        'соревнования': [
            "Соревновательные отрезки в каждой 3-й тренировке — имитация гонки",
            "Туры — лучшая подготовка к стартам. Это и тренировка, и психология гонки",
            "Психология решает 30% результата. Тренируй ментальную устойчивость",
            "Веди дневник стартов: что сработало, что нет, выводы",
            "Работай на ЧСС соревновательной интенсивности 1 раз в неделю"
        ],
        'знания': [
            "Теория без практики мертва, практика без теории слепа — баланс важен",
            "Изучай физиологию нагрузок — понимание удваивает эффект тренировок",
            "Знания дают осознанность, осознанность — контроль над процессом",
            "Биомеханика, энергообеспечение, восстановление — три кита прогресса"
        ],
        'себя': [
            "Катание для себя — не значит без системы. Система даёт стабильность и кайф",
            "Удовольствие от движения растёт с техникой — это проверено",
            "Тренируешься для себя? Делай это качественно — уважай своё время",
            "Лёгкое скольжение — результат правильной техники, а не только физики"
        ]
    }

    # === ИНСАЙТЫ ПО ВОЗРАСТУ (15+) ===
    age_insights = []
    try:
        age_num = int(age)
        if age_num < 25:
            age_insights = [
                "Твой возраст — время быстрого прогресса. Организм как губка впитывает нагрузки",
                "Молодость даёт быстрое восстановление — используй это",
                "Закладывай правильную технику сейчас — потом переучиваться сложнее"
            ]
        elif 25 <= age_num < 40:
            age_insights = [
                "Твой возраст — золотое время для любительского спорта. Опыт + физика",
                "После 30 важнее становится качество тренировок, а не количество",
                "Восстановление становится ключевым фактором прогресса"
            ]
        else:
            age_insights = [
                "Твой возраст — это мудрость в тренировках. Качество важнее объёма",
                "После 40 техника и восстановление решают всё",
                "Спортивное долголетие — результат умного подхода к нагрузкам"
            ]
    except:
        pass

    # === ТРАВМЫ ===
    injury_recs = []
    if injuries and injuries.lower() not in ['нет', 'none', '-', 'без травм']:
        injury_recs = [
            "Травмы требуют внимания — делай упражнения на укрепление проблемных зон",
            "Больше времени на растяжку и мобильность в зонах риска",
            "Профилактика травм = прогресс без остановок"
        ]

    # === СБОРКА РЕКОМЕНДАЦИЙ ===
    all_recs = []
    idx = profile_hash

    # Уровень (берём 2-3 рекомендации)
    level_list = recs_by_level.get(level, recs_by_level['новичок'])
    all_recs.append(level_list[idx % len(level_list)])
    all_recs.append(level_list[(idx+1) % len(level_list)])

    # Тренировки
    if '<3' in training:
        train_list = recs_training['low']
        all_recs.append(train_list[(idx+2) % len(train_list)])
    else:
        train_list = recs_training['high']
        all_recs.append(train_list[(idx+2) % len(train_list)])

    # Образ жизни
    if lifestyle == 'сидячий':
        life_list = recs_lifestyle['сидячий']
        all_recs.append(life_list[(idx+3) % len(life_list)])

    # Восстановление
    if recovery == 'хаос':
        rec_list = recs_recovery['хаос']
        all_recs.append(rec_list[(idx+4) % len(rec_list)])
    elif recovery == 'про':
        rec_list = recs_recovery['про']
        all_recs.append(rec_list[(idx+4) % len(rec_list)])
    else:
        rec_list = recs_recovery['норма']
        all_recs.append(rec_list[(idx+4) % len(rec_list)])

    # Цель
    goal_key = next((k for k in recs_goals.keys() if k in goal), 'себя')
    goal_list = recs_goals[goal_key]
    all_recs.append(goal_list[(idx+5) % len(goal_list)])

    # Травмы
    if injury_recs:
        all_recs.append(injury_recs[idx % len(injury_recs)])

    # Возраст
    if age_insights:
        all_recs.append(age_insights[(idx+6) % len(age_insights)])

    # Ограничиваем до 5-6 рекомендаций
    final_recs = all_recs[:6]

    # === ЗАВЕРШАЮЩИЕ ФРАЗЫ (15+) ===
    closings = [
        "💪 В Кафедре все программы учитывают твой уровень и цели!",
        "🎿 В Кафедре ты получишь систему, которая реально работает!",
        "⚡ Кафедра — это пошаговый план от точки А до результата!",
        "🚀 Присоединяйся к Кафедре — система уже готова для тебя!",
        "🏔 В Кафедре — тренер сборной + сообщество + готовые планы!",
        "🎯 Кафедра даст тебе структуру и ответы на все вопросы!",
        "💎 В Кафедре система адаптирована под любителей любого уровня!",
        "🔥 Кафедра — это не просто контент, это твоя дорожная карта!",
        "⭐ Присоединяйся к Кафедре и получи доступ к проверенной системе!",
        "🏆 В Кафедре ты не один — комьюнити поддержит на пути к цели!"
    ]

    # === ФИНАЛЬНАЯ СБОРКА ===
    opening = openings[idx % len(openings)]
    closing = closings[(idx+7) % len(closings)]

    msg_parts = [opening, "", "📋 <b>Персональные рекомендации на основе твоего профиля:</b>", ""]
    msg_parts.extend([f"• {rec}" for rec in final_recs])
    msg_parts.append("")
    msg_parts.append(closing)

    return "\n".join(msg_parts)
# ======================== КЛАВИАТУРЫ ========================
def main_kb(admin=False) -> ReplyKeyboardMarkup:
    btns = [
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="💳 Оплатить доступ")],
        [KeyboardButton(text="✅ Активная подписка")],
        [KeyboardButton(text="👥 Пригласить друга")],
        [KeyboardButton(text="💬 Поддержка")]
    ]
    if admin:
        btns.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=btns, resize_keyboard=True)

def get_admin_panel_text() -> str:
    """Текст админ-панели с датой последнего обновления"""
    return "⚙️ <b>Админ-панель</b>\n\n<i>Последнее обновление: 09.01.2026 00:30</i>"

def admin_kb() -> InlineKeyboardMarkup:
    global AUTO_BROADCAST_ENABLED, BROADCAST_INTERVAL_HOURS
    broadcast_status = "✅ ВКЛ" if AUTO_BROADCAST_ENABLED else "❌ ВЫКЛ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📨 Рассылка", callback_data="broadcast_menu")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
         InlineKeyboardButton(text="👥 Пользователи", callback_data="users")],
        [InlineKeyboardButton(text="✅ Выдать подписку", callback_data="grant_subscription")],
        [InlineKeyboardButton(text="💰 Цена 1111₽", callback_data="set_special_price"),
         InlineKeyboardButton(text="📚 Контент", callback_data="view_content")],
        [InlineKeyboardButton(text="🎬 Приветственное медиа", callback_data="change_welcome_media")],
        [InlineKeyboardButton(text=f"🤖 AI Авто: {broadcast_status}", callback_data="toggle_auto_broadcast")],
        [InlineKeyboardButton(text=f"⏰ Интервал: {BROADCAST_INTERVAL_HOURS}ч", callback_data="set_broadcast_interval")],
        [InlineKeyboardButton(text="📊 Google Таблицы", callback_data="export_menu")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="subscription_settings")]
    ])

def test_start_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, пройти тест", callback_data="start_test")],
        [InlineKeyboardButton(text="❌ Нет, позже", callback_data="skip_test")]
    ])

def tariff_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Тариф на 1 месяц", callback_data="tariff_1")]
    ])

def phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# ======================== КОМАНДЫ ========================
@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name or "друг"

    # Проверяем, пришел ли пользователь по реферальной ссылке
    referrer_id = None
    if message.text and len(message.text.split()) > 1:
        args = message.text.split()[1]
        if args.startswith('ref_'):
            try:
                referrer_id = int(args.replace('ref_', ''))

                # Проверяем, что пользователь новый
                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,)) as cursor:
                        existing_user = await cursor.fetchone()

                # Если пользователь новый и не пытается пригласить сам себя
                if not existing_user and referrer_id != user_id:
                    # Получаем данные реферера
                    async with aiosqlite.connect(DB_PATH) as db:
                        async with db.execute('SELECT username FROM users WHERE user_id = ?', (referrer_id,)) as cursor:
                            referrer_data = await cursor.fetchone()

                    if referrer_data:
                        referrer_username = referrer_data[0]

                        # Отправляем уведомление админу
                        for admin_id in ADMIN_IDS:
                            try:
                                admin_msg = (
                                    f"🎉 <b>Новый реферал!</b>\n\n"
                                    f"👤 <b>Пригласивший:</b>\n"
                                    f"├ ID: <code>{referrer_id}</code>\n"
                                    f"└ Username: @{referrer_username if referrer_username else 'не указан'}\n\n"
                                    f"👥 <b>Новый пользователь:</b>\n"
                                    f"├ ID: <code>{user_id}</code>\n"
                                    f"├ Username: @{username if username else 'не указан'}\n"
                                    f"└ Имя: {first_name}"
                                )
                                kb = InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="👤 Профиль приглашенного", url=f"tg://user?id={referrer_id}")],
                                    [InlineKeyboardButton(text="👥 Профиль нового", url=f"tg://user?id={user_id}")]
                                ])
                                await bot.send_message(admin_id, admin_msg, parse_mode="HTML", reply_markup=kb)
                            except Exception as e:
                                logging.error(f"Ошибка отправки уведомления админу {admin_id}: {e}")

                        # Уведомляем реферера
                        try:
                            ref_msg = (
                                f"🎉 <b>Отличная новость!</b>\n\n"
                                f"Твой друг <b>{first_name}</b> "
                                f"{'@' + username if username else ''} "
                                f"присоединился по твоей ссылке!\n\n"
                                f"Всего приглашенных: <b>{await get_referral_count(referrer_id) + 1}</b> чел."
                            )
                            await bot.send_message(referrer_id, ref_msg, parse_mode="HTML")
                        except Exception as e:
                            logging.error(f"Ошибка отправки уведомления рефереру: {e}")
                else:
                    referrer_id = None
            except (ValueError, IndexError):
                referrer_id = None

    await add_user(user_id, username, referrer_id)

    welcome_text = """Добро пожаловать в пространство, где даже любители растут как спортсмены.

Наша миссия — сделать правильные тренировки доступными каждому и помочь тебе выстроить прочную базу для техники, силы и выносливости.

Чтобы это стало реальностью, мы создали целую спортивную экосистему:
• Пошаговые курсы обучения — от азов техники до продвинутых навыков
• Подводящие и специальные упражнения, которые развивают нужные качества
• Еженедельные тренировочные программы — тренируйся системно
• Разборы, эфиры, лекции и подкасты

Подробнее — смотри в видео выше ⬆️

🎉 Ты почти КЛСник!

Осталось совсем немного, чтобы стать частью сильной команды — Кафедры любительского спорта.

Пройди короткий тест и получи персональные рекомендации!"""
    
    keyboard = main_kb(is_admin(user_id))

    # Проверяем тип медиа (видео или фото)
    media_type = await get_welcome_media_type()
    welcome_video_id = await get_welcome_video()
    welcome_photo_id = await get_welcome_photo()

    media_sent = False

    # Приоритет: видео > фото > текст
    if media_type == 'video' and welcome_video_id:
        try:
            await message.answer_video(
                video=welcome_video_id,
                caption=welcome_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            media_sent = True
        except Exception as e:
            logging.error(f"Ошибка отправки видео: {e}")

    if not media_sent and welcome_photo_id:
        try:
            await message.answer_photo(
                photo=welcome_photo_id,
                caption=welcome_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            media_sent = True
        except:
            pass

    if not media_sent:
        await message.answer(welcome_text, parse_mode="HTML", reply_markup=keyboard)

    # Проверяем, принял ли пользователь политику конфиденциальности
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT oferta_accepted, profile_completed FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            oferta_accepted = row and row[0]
            profile_done = row and row[1]

    # Если не принял оферту - показываем её после приветствия
    if not oferta_accepted:
        await asyncio.sleep(1)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Согласиться", callback_data="accept_oferta")]
        ])
        await message.answer(
            "📋 <b>Политика конфиденциальности</b>\n\n"
            "Пожалуйста, ознакомьтесь с политикой конфиденциальности перед началом работы с ботом.\n\n"
            "📄 <a href='https://drive.google.com/drive/folders/1aRKsmpdxMUTE69uuUmrbgywdAtadm7cW'>Открыть документ</a>",
            parse_mode="HTML",
            reply_markup=kb,
            disable_web_page_preview=True
        )
        return

    if not profile_done:
        await asyncio.sleep(1)
        await message.answer(
            "📋 <b>Хочешь пройти короткий тест?</b>\n\n"
            "Это поможет мне подбирать для тебя персональные советы и рекомендации по тренировкам 💪",
            parse_mode="HTML",
            reply_markup=test_start_kb()
        )

@router.callback_query(F.data == "start_test")
async def start_test(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📝 Как тебя зовут?")
    await state.set_state(ProfileStates.name)
    await callback.answer()

@router.callback_query(F.data == "skip_test")
async def skip_test(callback: CallbackQuery):
    await callback.message.edit_text("Хорошо, можешь пройти тест позже 👍")
    await callback.answer()

@router.callback_query(F.data == "accept_oferta")
async def accept_oferta(callback: CallbackQuery):
    user_id = callback.from_user.id

    # Сохраняем принятие оферты в БД
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('UPDATE users SET oferta_accepted = 1 WHERE user_id = ?', (user_id,))
        await db.commit()

        # Проверяем, завершён ли профиль
        async with db.execute('SELECT profile_completed FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            profile_done = row and row[0]

    # Редактируем сообщение
    try:
        await callback.message.edit_text(
            "✅ <b>Отлично!</b>\n\nПолитика конфиденциальности принята. Теперь ты можешь пользоваться всеми возможностями бота!",
            parse_mode="HTML"
        )
    except:
        pass

    await callback.answer("✅ Регистрация принята!")

    # Если профиль не завершён - предлагаем тест
    if not profile_done:
        await callback.message.answer(
            "📋 <b>Хочешь пройти короткий тест?</b>\n\n"
            "Это поможет мне подбирать для тебя персональные советы и рекомендации по тренировкам 💪",
            parse_mode="HTML",
            reply_markup=test_start_kb()
        )

# ======================== ТЕСТ ПРОФИЛЯ ========================
@router.message(ProfileStates.name)
async def profile_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Сколько тебе лет? 🎂")
    await state.set_state(ProfileStates.age)

@router.message(ProfileStates.age)
async def profile_age(message: Message, state: FSMContext):
    await state.update_data(age=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨 Мужской", callback_data="gender_м")],
        [InlineKeyboardButton(text="👩 Женский", callback_data="gender_ж")]
    ])
    await message.answer("Твой пол?", reply_markup=kb)
    await state.set_state(ProfileStates.gender)

@router.callback_query(ProfileStates.gender)
async def profile_gender(callback: CallbackQuery, state: FSMContext):
    gender = callback.data.split("_")[1]
    await state.update_data(gender=gender)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Прокачать технику", callback_data="goal_техника")],
        [InlineKeyboardButton(text="🏆 Подготовка к соревнованиям", callback_data="goal_соревнования")],
        [InlineKeyboardButton(text="💪 Тренировки для себя", callback_data="goal_себя")],
        [InlineKeyboardButton(text="📚 Хочу получить новые знания", callback_data="goal_знания")]
    ])
    await callback.message.edit_text("Твоя цель?", reply_markup=kb)
    await state.set_state(ProfileStates.goal)
    await callback.answer()

@router.callback_query(ProfileStates.goal)
async def profile_goal(callback: CallbackQuery, state: FSMContext):
    goal = callback.data.split("_")[1]
    await state.update_data(goal=goal)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Новичок", callback_data="lvl_новичок")],
        [InlineKeyboardButton(text="⭐ Любитель", callback_data="lvl_любитель")],
        [InlineKeyboardButton(text="🏅 Профи", callback_data="lvl_профи")]
    ])
    await callback.message.edit_text("Твой уровень?", reply_markup=kb)
    await state.set_state(ProfileStates.level)
    await callback.answer()

@router.callback_query(ProfileStates.level)
async def profile_level(callback: CallbackQuery, state: FSMContext):
    level = callback.data.split("_")[1]
    await state.update_data(level=level)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="<3 раза в неделю", callback_data="train_<3")],
        [InlineKeyboardButton(text=">3 раз в неделю", callback_data="train_>3")]
    ])
    await callback.message.edit_text("Сколько раз тренируешься в неделю?", reply_markup=kb)
    await state.set_state(ProfileStates.weekly_training)
    await callback.answer()

@router.callback_query(ProfileStates.weekly_training)
async def profile_training(callback: CallbackQuery, state: FSMContext):
    train = callback.data.split("_")[1]
    await state.update_data(weekly_training=train)
    await callback.message.edit_text("Есть ли травмы? (напиши или 'нет')")
    await state.set_state(ProfileStates.injuries)
    await callback.answer()

@router.message(ProfileStates.injuries)
async def profile_injuries(message: Message, state: FSMContext):
    await state.update_data(injuries=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❄️ Север/Северо-Запад/Сибирь", callback_data="reg_север")],
        [InlineKeyboardButton(text="🏔 Средняя полоса России/Урал", callback_data="reg_средняя")],
        [InlineKeyboardButton(text="🏛 Центральный регион", callback_data="reg_центральный")],
        [InlineKeyboardButton(text="☀️ Южный регион", callback_data="reg_юг")]
    ])
    await message.answer("Твой регион?", reply_markup=kb)
    await state.set_state(ProfileStates.region)

@router.callback_query(ProfileStates.region)
async def profile_region(callback: CallbackQuery, state: FSMContext):
    region = callback.data.split("_")[1]
    await state.update_data(region=region)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💺 Сидячий", callback_data="life_сидячий")],
        [InlineKeyboardButton(text="🚶 Умеренно активный", callback_data="life_умеренный")],
        [InlineKeyboardButton(text="⚙️ Активный", callback_data="life_активный")],
        [InlineKeyboardButton(text="🏃 Очень активный", callback_data="life_очень")]
    ])
    await callback.message.edit_text("Образ жизни?", reply_markup=kb)
    await state.set_state(ProfileStates.lifestyle)
    await callback.answer()

@router.callback_query(ProfileStates.lifestyle)
async def profile_lifestyle(callback: CallbackQuery, state: FSMContext):
    life = callback.data.split("_")[1]
    await state.update_data(lifestyle=life)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😴 Сплю и ем как попало, хочу наладить режим", callback_data="rec_хаос")],
        [InlineKeyboardButton(text="⚖️ В целом слежу за питанием и сном", callback_data="rec_норма")],
        [InlineKeyboardButton(text="🧘 Восстанавливаюсь осознанно", callback_data="rec_про")]
    ])
    await callback.message.edit_text("Восстановление и режим?", reply_markup=kb)
    await state.set_state(ProfileStates.recovery)
    await callback.answer()

@router.callback_query(ProfileStates.recovery)
async def profile_recovery(callback: CallbackQuery, state: FSMContext):
    rec = callback.data.split("_")[1]
    await state.update_data(recovery=rec)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да", callback_data="tour_да")],
        [InlineKeyboardButton(text="🤔 Не ездил, но было бы круто", callback_data="tour_хочу")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="tour_нет")]
    ])
    await callback.message.edit_text("Хотел бы принимать участие в турах?", reply_markup=kb)
    await state.set_state(ProfileStates.tours)
    await callback.answer()

@router.callback_query(ProfileStates.tours)
async def profile_tours(callback: CallbackQuery, state: FSMContext):
    tours = callback.data.split("_")[1]
    await state.update_data(tours=tours)
    
    data = await state.get_data()
    user_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''UPDATE users SET 
            name=?, age=?, gender=?, goal=?, level=?, weekly_training=?, 
            injuries=?, region=?, lifestyle=?, recovery=?, tours=?, profile_completed=1
            WHERE user_id=?''',
            (data['name'], data['age'], data['gender'], data['goal'], data['level'],
             data['weekly_training'], data['injuries'], data['region'], 
             data['lifestyle'], data['recovery'], tours, user_id))
        await db.commit()
    
    await callback.message.edit_text("⏳ Анализирую твой профиль...")
    
    # Генерируем персональную рекомендацию
    profile = {
        'name': data['name'],
        'age': data['age'],
        'gender': data['gender'],
        'goal': data['goal'],
        'level': data['level'],
        'weekly_training': data['weekly_training'],
        'injuries': data['injuries'],
        'region': data['region'],
        'lifestyle': data['lifestyle'],
        'recovery': data['recovery'],
        'tours': tours
    }
    
    feedback = await generate_test_feedback(profile)

    await callback.message.answer(feedback, parse_mode="HTML")

    # Добавляем кнопки после результатов теста
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оформить подписку", callback_data="subscribe_now")],
        [InlineKeyboardButton(text="📖 Еще подробнее о КЛС", callback_data="more_about_kls")]
    ])

    policy_text = "\n\n<i>Нажимая на кнопку оплаты, вы соглашаетесь с политикой конфиденциальности</i>"

    await callback.message.answer(
        "Что бы ты хотел сделать дальше?" + policy_text,
        reply_markup=kb,
        parse_mode="HTML"
    )

    await state.clear()
    await callback.answer()

# Обработчик "Еще подробнее о КЛС"
@router.callback_query(F.data == "more_about_kls")
async def more_about_kls_handler(callback: CallbackQuery):
    kls_text = """<b>Что такое КЛС?</b>

КЛС — это Кафедра Любительского Спорта — сообщество для тех, кто хочет тренироваться правильно, развиваться в лыжных гонках и чувствовать прогресс от недели к неделе.

Мы объединили всё, что нужно спортсмену-любителю в одном месте 👇
🏔 Курсы и программы от простого к сложному
💪 Еженедельные тренировки по системе
🎧 Разборы, эфиры, лекции и подкасты
🎥 Тренировки с тренерами сборной России
🧠 ИИ-помощник, созданный на основе спортивных исследований
🔥 Контрольные старты и сборы для проверки формы

КЛС — это не просто подписка.
Это твой путь в осознанный спорт, где каждая тренировка имеет смысл.

<i>Нажимая на кнопку оплаты, вы соглашаетесь с политикой конфиденциальности</i>"""

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Вступаю в КЛС", callback_data="subscribe_now")]
    ])

    await callback.message.edit_text(kls_text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

# Обработчик "Оформить подписку"
@router.callback_query(F.data == "subscribe_now")
async def subscribe_now_handler(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    keyboard = main_kb(is_admin(user_id))
    price = await get_user_price(user_id)

    try:
        def create_payment_sync():
            return Payment.create({
                "amount": {"value": f"{price}.00", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": f"https://t.me/djfkjf_bot"},
                "capture": True,
                "description": "Подписка на 1 месяц - Кафедра любительского спорта",
                "receipt": {
                    "customer": {"email": "user@example.com"},
                    "items": [{
                        "description": "Подписка на 1 месяц - Кафедра любительского спорта",
                        "quantity": "1",
                        "amount": {"value": f"{price}.00", "currency": "RUB"},
                        "vat_code": 1
                    }]
                },
                "metadata": {"user_id": user_id}
            }, str(uuid.uuid4()))

        payment = await asyncio.to_thread(create_payment_sync)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO payments (user_id, payment_id, amount, status, created_at) VALUES (?, ?, ?, ?, ?)',
                (user_id, payment.id, price, 'pending', int(datetime.now().timestamp()))
            )
            await db.commit()

        buttons = [[InlineKeyboardButton(text="💳 Оплатить", url=payment.confirmation.confirmation_url)]]
        await callback.message.answer(
            f"💰 Счет на оплату создан!\n\nСумма: {price} ₽\nНажмите кнопку ниже для оплаты:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        asyncio.create_task(check_payment(payment.id, user_id))

    except Exception as e:
        logging.error(f"Ошибка создания платежа: {e}")
        await callback.message.answer("❌ Ошибка создания платежа. Попробуйте позже.", reply_markup=keyboard)

    await callback.answer()

# ======================== МЕНЮ ========================
@router.message(F.text == "💳 Оплатить доступ")
async def pay_button(message: Message):
    text = "💳 <b>Тариф для:</b> 'Кафедра любительского спорта'\n\n"
    text += "При оплате тарифа Вы получите доступ: <i>Кафедра любительского спорта</i>"

    await message.answer(text, parse_mode="HTML", reply_markup=tariff_kb())

@router.callback_query(F.data == "pay_subscription")
async def pay_subscription_callback(callback: CallbackQuery, state: FSMContext):
    """Обработчик кнопки оплаты из рассылки"""
    user_id = callback.from_user.id
    keyboard = main_kb(is_admin(user_id))
    price = await get_user_price(user_id)

    try:
        def create_payment_sync():
            return Payment.create({
                "amount": {"value": f"{price}.00", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": f"https://t.me/djfkjf_bot"},
                "capture": True,
                "description": "Подписка на 1 месяц - Кафедра любительского спорта",
                "receipt": {
                    "customer": {"email": "user@example.com"},
                    "items": [{
                        "description": "Подписка на 1 месяц - Кафедра любительского спорта",
                        "quantity": "1",
                        "amount": {"value": f"{price}.00", "currency": "RUB"},
                        "vat_code": 1
                    }]
                },
                "metadata": {"user_id": user_id}
            }, str(uuid.uuid4()))

        payment = await asyncio.to_thread(create_payment_sync)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO payments (user_id, payment_id, amount, status, created_at) VALUES (?, ?, ?, ?, ?)',
                (user_id, payment.id, price, 'pending', int(datetime.now().timestamp()))
            )
            await db.commit()

        buttons = [[InlineKeyboardButton(text="💳 Оплатить", url=payment.confirmation.confirmation_url)]]
        await callback.message.answer(
            f"💰 Счет на оплату создан!\n\nСумма: {price} ₽\nНажмите кнопку ниже для оплаты:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        asyncio.create_task(check_payment(payment.id, user_id))

    except Exception as e:
        logging.error(f"Ошибка создания платежа: {e}")
        await callback.message.answer("❌ Ошибка создания платежа. Попробуйте позже.", reply_markup=keyboard)

    await callback.answer()

@router.callback_query(F.data == "tariff_1")
async def tariff_1_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    keyboard = main_kb(is_admin(user_id))
    price = await get_user_price(user_id)

    try:
        def create_payment_sync():
            return Payment.create({
                "amount": {"value": f"{price}.00", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": f"https://t.me/djfkjf_bot"},
                "capture": True,
                "description": "Подписка на 1 месяц - Кафедра любительского спорта",
                "receipt": {
                    "customer": {"email": "user@example.com"},
                    "items": [{
                        "description": "Подписка на 1 месяц - Кафедра любительского спорта",
                        "quantity": "1",
                        "amount": {"value": f"{price}.00", "currency": "RUB"},
                        "vat_code": 1
                    }]
                },
                "metadata": {"user_id": user_id}
            }, str(uuid.uuid4()))

        payment = await asyncio.to_thread(create_payment_sync)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO payments (user_id, payment_id, amount, status, created_at) VALUES (?, ?, ?, ?, ?)',
                (user_id, payment.id, price, 'pending', int(datetime.now().timestamp()))
            )
            await db.commit()

        buttons = [[InlineKeyboardButton(text="💳 Оплатить", url=payment.confirmation.confirmation_url)]]
        await callback.message.answer(
            f"💰 Счет на оплату создан!\n\nСумма: {price} ₽\nНажмите кнопку ниже для оплаты:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        asyncio.create_task(check_payment(payment.id, user_id))

    except Exception as e:
        logging.error(f"Ошибка создания платежа: {e}")
        await callback.message.answer("❌ Ошибка создания платежа. Попробуйте позже.", reply_markup=keyboard)

    await callback.answer()

@router.message(PhoneState.waiting_phone, F.contact)
async def phone_received(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    user_id = message.from_user.id

    logging.info(f"Получен контакт от {user_id}: {phone}")
    await update_phone(user_id, phone)

    keyboard = main_kb(is_admin(user_id))
    price = await get_user_price(user_id)  # Получаем цену для пользователя (с учётом special_price)

    try:
        logging.info(f"Создаю платеж для {user_id}...")

        # Обернем синхронный вызов ЮКасса в asyncio.to_thread
        def create_payment_sync():
            return Payment.create({
                "amount": {"value": f"{price}.00", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": f"https://t.me/djfkjf_bot"},
                "capture": True,
                "description": "Подписка на 1 месяц - Кафедра любительского спорта",
                "receipt": {
                    "customer": {"email": "user@example.com"},
                    "items": [{
                        "description": "Подписка на 1 месяц - Кафедра любительского спорта",
                        "quantity": "1",
                        "amount": {"value": f"{price}.00", "currency": "RUB"},
                        "vat_code": 1
                    }]
                },
                "metadata": {"user_id": user_id}
            }, str(uuid.uuid4()))

        payment = await asyncio.to_thread(create_payment_sync)

        if payment is None:
            raise Exception("Не удалось создать платеж - получен пустой ответ от сервера")

        logging.info(f"Платеж создан: {payment.id}, сумма: {price}")

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO payments (user_id, payment_id, amount, status, created_at) VALUES (?, ?, ?, ?, ?)',
                (user_id, payment.id, price, 'pending', int(datetime.now().timestamp()))
            )
            await db.commit()

        buttons = [[InlineKeyboardButton(text="💳 Оплатить", url=payment.confirmation.confirmation_url)]]

        logging.info(f"Отправляю сообщение с кнопкой оплаты пользователю {user_id}")

        await message.answer(
            f"💰 Счет на оплату создан!\n\nСумма: {price} ₽\nНажмите кнопку ниже для оплаты:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

        await message.answer("⬆️ Нажмите на кнопку оплаты выше", reply_markup=keyboard)

        logging.info(f"Сообщения отправлены пользователю {user_id}")

        asyncio.create_task(check_payment(payment.id, user_id))

    except Exception as e:
        logging.error(f"Ошибка создания платежа: {e}")
        await message.answer("❌ Ошибка создания платежа. Попробуйте позже.", reply_markup=keyboard)

    await state.clear()

# Резервный обработчик контактов (если состояние потерялось)
@router.message(F.contact)
async def phone_received_no_state(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    user_id = message.from_user.id

    logging.info(f"[РЕЗЕРВ] Получен контакт от {user_id}: {phone}")
    await update_phone(user_id, phone)

    keyboard = main_kb(is_admin(user_id))
    price = await get_user_price(user_id)  # Получаем цену для пользователя (с учётом special_price)

    try:
        # Обернем синхронный вызов ЮКасса в asyncio.to_thread
        def create_payment_sync():
            return Payment.create({
                "amount": {"value": f"{price}.00", "currency": "RUB"},
                "confirmation": {"type": "redirect", "return_url": f"https://t.me/djfkjf_bot"},
                "capture": True,
                "description": "Подписка на 1 месяц - Кафедра любительского спорта",
                "receipt": {
                    "customer": {"email": "user@example.com"},
                    "items": [{
                        "description": "Подписка на 1 месяц - Кафедра любительского спорта",
                        "quantity": "1",
                        "amount": {"value": f"{price}.00", "currency": "RUB"},
                        "vat_code": 1
                    }]
                },
                "metadata": {"user_id": user_id}
            }, str(uuid.uuid4()))

        payment = await asyncio.to_thread(create_payment_sync)

        if payment is None:
            raise Exception("Не удалось создать платеж - получен пустой ответ от сервера")

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO payments (user_id, payment_id, amount, status, created_at) VALUES (?, ?, ?, ?, ?)',
                (user_id, payment.id, price, 'pending', int(datetime.now().timestamp()))
            )
            await db.commit()

        buttons = [[InlineKeyboardButton(text="💳 Оплатить", url=payment.confirmation.confirmation_url)]]
        await message.answer(
            f"💰 Счет на оплату создан!\n\nСумма: {price} ₽\nНажмите кнопку ниже для оплаты:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )

        await message.answer("⬆️ Нажмите на кнопку оплаты выше", reply_markup=keyboard)

        asyncio.create_task(check_payment(payment.id, user_id))

    except Exception as e:
        logging.error(f"[РЕЗЕРВ] Ошибка создания платежа: {e}")
        await message.answer("❌ Ошибка создания платежа. Попробуйте позже.", reply_markup=keyboard)

    await state.clear()

async def check_payment(payment_id: str, user_id: int, max_checks: int = 60):
    for _ in range(max_checks):
        await asyncio.sleep(10)
        try:
            # Обернем синхронный вызов в asyncio.to_thread
            payment = await asyncio.to_thread(Payment.find_one, payment_id)
            if payment.status == 'succeeded':
                # Сохраняем цену которую заплатил пользователь как special_price
                paid_amount = int(payment.amount.value)
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        'UPDATE users SET special_price = ? WHERE user_id = ? AND special_price IS NULL',
                        (paid_amount, user_id)
                    )
                    await db.commit()

                await activate_subscription(user_id, 30, paid_amount)

                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute('UPDATE payments SET status = ? WHERE payment_id = ?', ('succeeded', payment_id))
                    await db.commit()

                # Отправляем видео или текст после оплаты
                paid_video = await get_paid_video()
                secret_word = await get_secret_word()

                if paid_video:
                    try:
                        await bot.send_video(
                            user_id,
                            video=paid_video,
                            caption="✅ <b>Оплата прошла успешно!</b>\n\n"
                                    "Подписка активирована на 30 дней.\n\n"
                                    "📺 Посмотри видео до конца и введи кодовое слово, чтобы получить ссылку на канал!",
                            parse_mode="HTML"
                        )
                    except:
                        await bot.send_message(
                            user_id,
                            "✅ <b>Оплата прошла успешно!</b>\n\n"
                            "Подписка активирована на 30 дней.\n\n"
                            "🔑 Введи кодовое слово чтобы получить ссылку на канал!",
                            parse_mode="HTML"
                        )
                else:
                    # Если видео не установлено - просто текст
                    await bot.send_message(
                        user_id,
                        "✅ <b>Оплата прошла успешно!</b>\n\n"
                        "Подписка активирована на 30 дней.\n\n"
                        "🔑 <b>Введи кодовое слово чтобы получить ссылку на канал!</b>",
                        parse_mode="HTML"
                    )
                break
        except Exception as e:
            logging.error(f"Ошибка проверки платежа: {e}")

@router.message(F.text == "✅ Активная подписка")
async def subscription_button(message: Message):
    if await has_active_subscription(message.from_user.id):
        await message.answer("✅ Подписка активна!")
    else:
        await message.answer("❌ Нет активной подписки\n\nОформи подписку для доступа к материалам.")

@router.message(F.text == "💬 Поддержка")
async def support_button(message: Message):
    await message.answer("💬 <b>Поддержка:</b>\n\nСвяжитесь с нами: @pavlychevayana99", parse_mode="HTML")

@router.message(F.text == "👥 Пригласить друга")
async def referral_button(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or "пользователь"

    # Получаем данные о рефералах и наградах
    rewards = await get_referral_rewards(user_id)
    ref_link = await get_referral_link(user_id)

    # Формируем прогресс-бар
    next_target = rewards['next_milestone']['target']
    remaining = rewards['next_milestone']['remaining']
    progress = rewards['count']
    progress_bar = '▰' * min(progress, 10) + '▱' * max(0, 10 - progress)

    # Улучшенное сообщение с системой уровней
    ref_message = (
        f"🎁 <b>РЕФЕРАЛЬНАЯ ПРОГРАММА</b>\n\n"
        f"🏅 <b>Твой уровень:</b> {rewards['level']}\n"
        f"👥 <b>Приглашено:</b> {rewards['count']} друзей\n\n"
        f"📊 <b>Прогресс до {next_target} друзей:</b>\n"
        f"{progress_bar} ({remaining} осталось)\n\n"
        f"🔗 <b>Твоя персональная ссылка:</b>\n"
        f"<code>{ref_link}</code>\n\n"
        f"💎 <b>Система уровней:</b>\n"
        f"• 5 друзей = ⭐ Активный партнер\n"
        f"• 10 друзей = 🥉 Бронзовый партнер\n"
        f"• 20 друзей = 🥈 Серебряный партнер\n"
        f"• 50 друзей = 🏆 Золотой партнер\n\n"
        f"💡 <i>Приглашай друзей и повышай свой уровень!</i>"
    )

    # Кнопки для шаринга и статистики
    share_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Поделиться ссылкой",
                            url=f"https://t.me/share/url?url={ref_link}&text=Присоединяйся к Кафедре любительского спорта! 🎿")],
        [InlineKeyboardButton(text="📊 Детальная статистика", callback_data="ref_stats")],
        [InlineKeyboardButton(text="📄 Условия программы", callback_data="ref_terms")]
    ])

    await message.answer(ref_message, parse_mode="HTML", reply_markup=share_kb)

@router.callback_query(F.data == "ref_terms")
async def ref_terms_handler(callback: CallbackQuery):
    """Отправка условий реферальной программы"""
    pdf_path = os.path.join(os.path.dirname(__file__), 'data', 'refer_programm.pdf')

    try:
        if not os.path.exists(pdf_path):
            await callback.answer("❌ Файл не найден", show_alert=True)
            return

        await callback.message.answer_document(
            FSInputFile(pdf_path),
            caption="📄 <b>Условия реферальной программы</b>",
            parse_mode="HTML"
        )
        await callback.answer()
    except Exception as e:
        logging.error(f"Ошибка отправки PDF: {e}")
        await callback.answer("❌ Ошибка отправки файла", show_alert=True)

@router.message(F.text == "👤 Профиль")
async def profile_button(message: Message):
    user_id = message.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        # Получаем данные пользователя
        async with db.execute(
            'SELECT name, age, subscription_until, referral_earnings FROM users WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                await message.answer("❌ Профиль не найден")
                return

            name = row[0] or "Не указано"
            age = row[1] or "Не указано"
            sub_until = row[2]
            earnings = row[3] or 0.0

        # Проверяем подписку
        now = int(datetime.now().timestamp())
        if sub_until and sub_until > now:
            sub_status = "✅ Активна"
            days_left = (sub_until - now) // 86400
            sub_text = f"📅 Осталось дней: {days_left}"
        else:
            sub_status = "❌ Не активна"
            sub_text = "Оформите подписку для доступа к материалам"

        # Считаем количество рефералов
        async with db.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,)) as cursor:
            ref_count = (await cursor.fetchone())[0]

    profile_text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"📝 Имя: {name}\n"
        f"🎂 Возраст: {age}\n\n"
        f"💎 Подписка: {sub_status}\n"
        f"{sub_text}\n\n"
        f"👥 Рефералов: {ref_count}\n"
        f"💰 Заработано: {earnings:.2f}₽\n\n"
        f"⚠️ <i>Вывод средств возможен только при наличии ИП/СЗ</i>"
    )

    profile_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Вывод средств", callback_data="request_withdrawal")]
    ])

    if earnings < 100:
        profile_text += f"\n<i>💡 Минимальная сумма для вывода: 100₽</i>"

    await message.answer(profile_text, parse_mode="HTML", reply_markup=profile_kb)

@router.callback_query(F.data == "request_withdrawal")
async def withdrawal_request(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT referral_earnings FROM users WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if not row or not row[0] or row[0] < 100:
                await callback.answer("❌ Недостаточно средств для вывода (минимум 100₽)", show_alert=True)
                return

            earnings = row[0]

    await callback.message.answer(
        f"💸 <b>Вывод средств</b>\n\n"
        f"💰 Сумма к выводу: {earnings:.2f}₽\n\n"
        f"📞 Для вывода средств обратитесь в поддержку: @pavlychevayana99",
        parse_mode="HTML"
    )

    await callback.answer()

# ======================== АДМИН ========================
@router.message(F.text == "⚙️ Админ-панель")
async def admin_panel_button(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(get_admin_panel_text(), reply_markup=admin_kb(), parse_mode="HTML")

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(get_admin_panel_text(), reply_markup=admin_kb(), parse_mode="HTML")

@router.message(Command("setp"))
async def cmd_setp(message: Message):
    """Установить подписку: /setp user_id время (1d=день, 10m=минут, 2h=часа)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Команда только для админов")
        return

    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            "📝 <b>Формат:</b> /setp user_id время\n\n"
            "<b>Примеры:</b>\n"
            "/setp 123456789 1d — 1 день\n"
            "/setp 123456789 2h — 2 часа\n"
            "/setp 123456789 10m — 10 минут",
            parse_mode="HTML"
        )
        return

    try:
        target_user_id = int(args[1])
        time_str = args[2].lower()

        # Парсим время
        if time_str.endswith('d'):
            minutes = int(time_str[:-1]) * 24 * 60
        elif time_str.endswith('h'):
            minutes = int(time_str[:-1]) * 60
        elif time_str.endswith('m'):
            minutes = int(time_str[:-1])
        else:
            minutes = int(time_str)  # По умолчанию минуты

        # Устанавливаем подписку
        sub_until = int((datetime.now() + timedelta(minutes=minutes)).timestamp())
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE users SET subscription_until = ? WHERE user_id = ?', (sub_until, target_user_id))
            await db.commit()

        end_time = datetime.fromtimestamp(sub_until).strftime('%d.%m.%Y %H:%M')
        await message.answer(
            f"✅ Подписка установлена!\n\n"
            f"👤 User ID: <code>{target_user_id}</code>\n"
            f"⏰ Истекает: {end_time}\n"
            f"⏱ Через: {minutes} мин",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@router.message(Command("pay"))
async def cmd_pay(message: Message):
    """Тестовая команда - активирует подписку для админа"""
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("❌ Команда только для админов")
        return

    # Активируем подписку на 30 дней
    await activate_subscription(user_id, 30)

    # Отправляем видео или текст как после оплаты
    paid_video = await get_paid_video()

    if paid_video:
        try:
            await message.answer_video(
                video=paid_video,
                caption="✅ <b>Тестовая оплата прошла!</b>\n\n"
                        "Подписка активирована на 30 дней.\n\n"
                        "📺 Введи кодовое слово чтобы получить ссылку на канал!",
                parse_mode="HTML"
            )
        except:
            await message.answer(
                "✅ <b>Тестовая оплата прошла!</b>\n\n"
                "Подписка активирована на 30 дней.\n\n"
                "🔑 Введи кодовое слово чтобы получить ссылку на канал!",
                parse_mode="HTML"
            )
    else:
        await message.answer(
            "✅ <b>Тестовая оплата прошла!</b>\n\n"
            "Подписка активирована на 30 дней.\n\n"
            "🔑 Введи кодовое слово чтобы получить ссылку на канал!",
            parse_mode="HTML"
        )

@router.message(Command("checkbot"))
async def cmd_checkbot(message: Message):
    """Проверка прав бота в канале"""
    if not is_admin(message.from_user.id):
        return

    try:
        # Получаем информацию о боте в канале
        bot_member = await bot.get_chat_member(CHANNEL_ID, bot.id)

        status = bot_member.status
        text = f"🤖 <b>Статус бота в канале</b>\n\n"
        text += f"📍 Канал ID: <code>{CHANNEL_ID}</code>\n"
        text += f"👤 Статус: <b>{status}</b>\n\n"

        if status == "administrator":
            # Проверяем права
            rights = []
            if getattr(bot_member, 'can_invite_users', False):
                rights.append("✅ Приглашение пользователей")
            else:
                rights.append("❌ Приглашение пользователей")

            if getattr(bot_member, 'can_restrict_members', False):
                rights.append("✅ Блокировка пользователей")
            else:
                rights.append("❌ Блокировка пользователей")

            text += "<b>Права:</b>\n" + "\n".join(rights)
        elif status == "member":
            text += "⚠️ Бот добавлен как обычный участник, НЕ админ!"
        elif status == "left":
            text += "❌ Бот не в канале!"

        await message.answer(text, parse_mode="HTML")

    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@router.message(Command("setbalance"))
async def cmd_setbalance(message: Message):
    """Установить баланс: /setbalance user_id сумма"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Команда только для админов")
        return

    args = message.text.split()
    if len(args) < 3:
        await message.answer(
            "📝 <b>Формат:</b> /setbalance user_id сумма\n\n"
            "<b>Пример:</b>\n"
            "/setbalance 123456789 500 — установить баланс 500₽",
            parse_mode="HTML"
        )
        return

    try:
        target_user_id = int(args[1])
        amount = float(args[2])

        if amount < 0:
            await message.answer("❌ Сумма не может быть отрицательной")
            return

        # Устанавливаем баланс
        async with aiosqlite.connect(DB_PATH) as db:
            # Проверяем существует ли пользователь
            async with db.execute('SELECT user_id, name, username FROM users WHERE user_id = ?', (target_user_id,)) as cursor:
                user = await cursor.fetchone()

            if not user:
                await message.answer(
                    f"⚠️ Пользователь с ID {target_user_id} не найден в базе.\n"
                    "Создать пользователя и установить баланс? Используйте сначала /grant"
                )
                return

            await db.execute('UPDATE users SET referral_earnings = ? WHERE user_id = ?', (amount, target_user_id))
            await db.commit()

            user_name = user[1] or user[2] or f"ID {target_user_id}"

        await message.answer(
            f"✅ <b>Баланс установлен!</b>\n\n"
            f"👤 Пользователь: {user_name}\n"
            f"🆔 User ID: <code>{target_user_id}</code>\n"
            f"💰 Баланс: {amount:.2f}₽",
            parse_mode="HTML"
        )

        # Уведомляем пользователя
        try:
            await bot.send_message(
                target_user_id,
                f"💰 <b>Ваш баланс обновлен!</b>\n\n"
                f"Новый баланс: {amount:.2f}₽\n\n"
                f"Вы можете вывести средства через Профиль → Вывод средств",
                parse_mode="HTML"
            )
        except:
            pass  # Если не удалось отправить - не критично

    except ValueError:
        await message.answer("❌ Неверный формат. Используйте: /setbalance USER_ID СУММА")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@router.message(Command("setspecialprice"))
async def cmd_setspecialprice(message: Message):
    """
    Установить специальную цену для пользователей
    Формат: /setspecialprice ЦЕНА USER_ID1,USER_ID2,...
    """
    if not is_admin(message.from_user.id):
        return

    try:
        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            await message.answer(
                "❌ Неверный формат!\n\n"
                "Используйте: /setspecialprice ЦЕНА USER_ID1,USER_ID2,...\n\n"
                "Пример: /setspecialprice 1111 123456,789012,345678"
            )
            return

        price = int(args[1])
        user_ids_str = args[2]

        # Парсим список ID
        user_ids = []
        for uid in user_ids_str.split(','):
            try:
                user_ids.append(int(uid.strip()))
            except:
                pass

        if not user_ids:
            await message.answer("❌ Не удалось распознать ID пользователей")
            return

        # Устанавливаем special_price и grace_period
        current_time = int(datetime.now().timestamp())
        grace_until = int((datetime.now() + timedelta(days=7)).timestamp())

        success_count = 0
        async with aiosqlite.connect(DB_PATH) as db:
            for user_id in user_ids:
                # Проверяем, существует ли пользователь
                async with db.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,)) as cursor:
                    exists = await cursor.fetchone()

                if exists:
                    # Устанавливаем special_price и grace_period
                    await db.execute(
                        'UPDATE users SET special_price = ?, grace_period_until = ? WHERE user_id = ?',
                        (price, grace_until, user_id)
                    )
                    success_count += 1

            await db.commit()

        grace_date = datetime.fromtimestamp(grace_until).strftime('%d.%m.%Y')
        await message.answer(
            f"✅ <b>Специальная цена установлена!</b>\n\n"
            f"💰 Цена: <b>{price} ₽</b>\n"
            f"👥 Пользователей: <b>{success_count}</b> из {len(user_ids)}\n"
            f"📅 Льготный период до: <b>{grace_date}</b>",
            parse_mode="HTML"
        )

    except ValueError:
        await message.answer("❌ Неверный формат цены! Используйте целое число.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

@router.callback_query(F.data == "stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        total = (await (await db.execute('SELECT COUNT(*) FROM users')).fetchone())[0]
        active = (await (await db.execute('SELECT COUNT(*) FROM users WHERE subscription_until > ?', 
                                           (int(datetime.now().timestamp()),))).fetchone())[0]
        revenue = (await (await db.execute('SELECT SUM(amount) FROM payments WHERE status = "succeeded"')).fetchone())[0] or 0
    
    text = f"📊 <b>Статистика бота</b>\n\n"
    text += f"👥 Всего пользователей: <b>{total}</b>\n"
    text += f"✅ Активных подписок: <b>{active}</b>\n"
    text += f"💰 Общая выручка: <b>{revenue} ₽</b>"
    
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "users")
async def admin_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT user_id, username, phone, subscription_until FROM users ORDER BY created_at DESC LIMIT 20'
        ) as cursor:
            users = await cursor.fetchall()
    
    text = "👥 <b>Последние пользователи:</b>\n\n"
    for user_id, username, phone, sub_until in users:
        status = "✅" if sub_until and sub_until > int(datetime.now().timestamp()) else "❌"
        username_str = f"@{username}" if username else f"ID: {user_id}"
        phone_str = f"📱 {phone}" if phone else "Нет номера"
        text += f"{status} {username_str}\n{phone_str}\n\n"
    
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

# Старая система рассылки удалена - используется новая пошаговая система

@router.callback_query(F.data == "toggle_auto_broadcast")
async def toggle_auto_broadcast(callback: CallbackQuery):
    """Включить/выключить автоматическую рассылку"""
    global AUTO_BROADCAST_ENABLED
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    AUTO_BROADCAST_ENABLED = not AUTO_BROADCAST_ENABLED
    status = "включена ✅" if AUTO_BROADCAST_ENABLED else "выключена ❌"
    await callback.answer(f"Авто-рассылка {status}", show_alert=True)
    await callback.message.edit_text(get_admin_panel_text(), reply_markup=admin_kb(), parse_mode="HTML")

@router.callback_query(F.data == "set_broadcast_interval")
async def set_broadcast_interval(callback: CallbackQuery):
    """Настройка интервала авто-рассылки"""
    global BROADCAST_INTERVAL_HOURS
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="6 часов", callback_data="interval_6")],
        [InlineKeyboardButton(text="10 часов", callback_data="interval_10")],
        [InlineKeyboardButton(text="12 часов", callback_data="interval_12")],
        [InlineKeyboardButton(text="15 часов", callback_data="interval_15")],
        [InlineKeyboardButton(text="24 часа", callback_data="interval_24")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])
    await callback.message.edit_text(
        f"⏰ <b>Интервал авто-рассылки</b>\n\nТекущий: {BROADCAST_INTERVAL_HOURS} часов",
        reply_markup=kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("interval_"))
async def set_interval_value(callback: CallbackQuery):
    """Установить интервал"""
    global BROADCAST_INTERVAL_HOURS
    if not is_admin(callback.from_user.id):
        return

    hours = int(callback.data.split("_")[1])
    BROADCAST_INTERVAL_HOURS = hours
    await callback.answer(f"Интервал установлен: {hours} часов", show_alert=True)
    await callback.message.edit_text(get_admin_panel_text(), reply_markup=admin_kb(), parse_mode="HTML")

@router.callback_query(F.data == "preview_broadcast_me")
async def preview_broadcast_me(callback: CallbackQuery):
    """Отправить превью рассылки админу"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    # Получаем профиль админа
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT * FROM users WHERE user_id = ?', (callback.from_user.id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                profile = {
                    'name': row[4],
                    'age': row[5],
                    'gender': row[6],
                    'goal': row[7],
                    'level': row[8],
                    'weekly_training': row[9],
                    'injuries': row[10],
                    'region': row[11],
                    'lifestyle': row[12],
                    'recovery': row[13],
                    'tours': row[14]
                }
            else:
                profile = None

    msg = await generate_subscription_promo(profile, callback.from_user.id)
    await callback.message.answer(
        f"👁 <b>Превью рассылки:</b>\n\n{msg}",
        parse_mode="HTML"
    )
    await callback.answer("Превью отправлено")

@router.callback_query(F.data == "admin_panel")
async def back_to_admin(callback: CallbackQuery):
    """Вернуться в админ панель"""
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text(get_admin_panel_text(), reply_markup=admin_kb(), parse_mode="HTML")

@router.callback_query(F.data == "ai_broadcast")
async def ai_broadcast_handler(callback: CallbackQuery):
    """Ручной запуск AI рассылки для пользователей без подписки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text("🤖 Генерирую AI сообщение и запускаю рассылку...")

    # Генерируем превью
    promo_msg = await generate_subscription_promo()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отправить", callback_data="confirm_ai_broadcast")],
        [InlineKeyboardButton(text="🔄 Перегенерировать", callback_data="ai_broadcast")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_admin")]
    ])

    await callback.message.edit_text(
        f"<b>📨 ПРЕВЬЮ РАССЫЛКИ</b>\n\n{promo_msg}\n\n"
        f"<i>Будет отправлена всем пользователям БЕЗ активной подписки</i>",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data == "confirm_ai_broadcast")
async def confirm_ai_broadcast(callback: CallbackQuery):
    """Подтверждение и отправка AI рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    await callback.message.edit_text("📨 Отправляю рассылку...")

    sent = await broadcast_to_non_subscribers()

    await callback.message.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"Отправлено сообщений: {sent}",
        parse_mode="HTML"
    )

    # Возврат в админ-панель через 3 секунды
    await asyncio.sleep(3)
    await callback.message.edit_text(get_admin_panel_text(), reply_markup=admin_kb(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "admin_change_photo")
async def admin_change_photo(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await callback.message.answer("🖼 <b>Изменение приветственного фото</b>\n\nОтправь новое фото:", parse_mode="HTML")
    await state.set_state(PhoneState.waiting_phone)  # Используем для фото временно
    await callback.answer()

# ======================== ПРИВЕТСТВЕННОЕ МЕДИА (ВИДЕО/ФОТО) ========================
class WelcomeMediaState(StatesGroup):
    waiting_media = State()

@router.callback_query(F.data == "change_welcome_media")
async def change_welcome_media_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    current_type = await get_welcome_media_type()
    current_text = "Видео" if current_type == "video" else "Фото" if current_type == "photo" else "Не установлено"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎥 Загрузить видео", callback_data="upload_welcome_video")],
        [InlineKeyboardButton(text="🖼 Загрузить фото", callback_data="upload_welcome_photo")],
        [InlineKeyboardButton(text="🗑 Удалить медиа", callback_data="delete_welcome_media")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
    ])

    await callback.message.edit_text(
        f"🎬 <b>Приветственное медиа</b>\n\n"
        f"Текущий тип: <b>{current_text}</b>\n\n"
        f"Выбери действие:",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data == "upload_welcome_video")
async def upload_welcome_video(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await state.update_data(welcome_media_type="video")
    await state.set_state(WelcomeMediaState.waiting_media)
    await callback.message.answer(
        "🎥 <b>Загрузка приветственного видео</b>\n\n"
        "Отправь видео (до 50MB, максимум 1024 символов caption):",
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "upload_welcome_photo")
async def upload_welcome_photo(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await state.update_data(welcome_media_type="photo")
    await state.set_state(WelcomeMediaState.waiting_media)
    await callback.message.answer(
        "🖼 <b>Загрузка приветственного фото</b>\n\nОтправь фото:",
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "delete_welcome_media")
async def delete_welcome_media(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM settings WHERE key IN ('welcome_video', 'welcome_photo', 'welcome_media_type')")
        await db.commit()

    await callback.message.edit_text(
        "✅ Приветственное медиа удалено!\n\nТеперь будет отправляться только текст.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
        ])
    )
    await callback.answer()

@router.message(WelcomeMediaState.waiting_media, F.video)
async def handle_welcome_video(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    video_id = message.video.file_id
    await set_welcome_video(video_id)
    await set_welcome_media_type("video")

    await message.answer(
        "✅ <b>Приветственное видео установлено!</b>\n\n"
        "Теперь при /start будет отправляться это видео.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В админ-панель", callback_data="back_to_admin")]
        ])
    )
    await state.clear()

@router.message(WelcomeMediaState.waiting_media, F.photo)
async def handle_welcome_photo(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    photo_id = message.photo[-1].file_id
    await set_welcome_photo(photo_id)
    await set_welcome_media_type("photo")

    await message.answer(
        "✅ <b>Приветственное фото установлено!</b>\n\n"
        "Теперь при /start будет отправляться это фото.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В админ-панель", callback_data="back_to_admin")]
        ])
    )
    await state.clear()

# ======================== ЗАГРУЗКА PDF ========================
@router.callback_query(F.data == "upload_pdf")
async def upload_pdf_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    categories_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏃 Тренировки", callback_data="pdf_cat_trainings")],
        [InlineKeyboardButton(text="💪 СФП", callback_data="pdf_cat_sfp")],
        [InlineKeyboardButton(text="📚 База знаний", callback_data="pdf_cat_knowledge")],
        [InlineKeyboardButton(text="🎿 Лыжероллеры", callback_data="pdf_cat_rollers")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_upload")]
    ])

    await callback.message.answer(
        "📄 <b>Загрузка PDF с тренировками</b>\n\nВыбери категорию:",
        parse_mode="HTML",
        reply_markup=categories_kb
    )
    await callback.answer()

@router.callback_query(F.data.startswith("pdf_cat_"))
async def pdf_category_selected(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    category = callback.data.replace("pdf_cat_", "")
    await state.update_data(pdf_category=category)

    category_names = {
        'trainings': 'Тренировки',
        'sfp': 'СФП',
        'knowledge': 'База знаний',
        'rollers': 'Лыжероллеры'
    }

    await callback.message.edit_text(
        f"📄 Категория: <b>{category_names.get(category, category)}</b>\n\n"
        f"Теперь отправь PDF файл с тренировочным планом.\n\n"
        f"<i>AI автоматически извлечёт текст и создаст структурированный каталог знаний.</i>",
        parse_mode="HTML"
    )
    await state.set_state(ContentUpload.waiting_pdf_file)
    await callback.answer()

@router.message(ContentUpload.waiting_pdf_file, F.document)
async def pdf_file_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    # Проверяем, что это PDF
    if not message.document.file_name.lower().endswith('.pdf'):
        await message.answer("❌ Пожалуйста, отправь PDF файл!")
        return

    await message.answer("⏳ Обрабатываю PDF... Извлекаю текст и создаю каталог знаний...")

    try:
        # Скачиваем файл
        file = await bot.get_file(message.document.file_id)
        file_bytes = await bot.download_file(file.file_path)

        # Извлекаем текст
        text = await extract_text_from_pdf(file_bytes.read())

        if not text:
            await message.answer("❌ Не удалось извлечь текст из PDF. Попробуй другой файл.")
            await state.clear()
            return

        # Структурируем контент с помощью AI
        structured = await structure_training_content(text)

        # Получаем категорию
        data = await state.get_data()
        category = data.get('pdf_category', 'general')

        # Сохраняем в БД
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                '''INSERT INTO training_pdfs (category, title, description, file_id, file_name, extracted_text, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (category, structured['title'], structured['description'],
                 message.document.file_id, message.document.file_name, text, int(datetime.now().timestamp()))
            )
            await db.commit()

        # Формируем красивый ответ
        response = f"✅ <b>PDF успешно обработан!</b>\n\n"
        response += f"📌 <b>Название:</b> {structured['title']}\n"
        response += f"📝 <b>Описание:</b> {structured['description']}\n"
        response += f"📊 <b>Извлечено тренировок:</b> {len(structured['trainings'])}\n\n"

        if structured['trainings']:
            response += "<b>Примеры тренировок:</b>\n\n"
            for i, training in enumerate(structured['trainings'][:3], 1):
                preview = training[:200] + "..." if len(training) > 200 else training
                response += f"{i}. {preview}\n\n"

        response += "🎉 Контент добавлен в каталог знаний и доступен в разделе Тренировки!"

        await message.answer(response, parse_mode="HTML")
        await state.clear()

    except Exception as e:
        logging.error(f"Ошибка обработки PDF: {e}")
        await message.answer(f"❌ Ошибка обработки PDF: {e}")
        await state.clear()

# ======================== ЗАГРУЗКА ВИДЕО ========================
@router.callback_query(F.data == "upload_video")
async def upload_video_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    categories_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Лекции", callback_data="video_cat_lectures")],
        [InlineKeyboardButton(text="🎯 Техника", callback_data="video_cat_technique")],
        [InlineKeyboardButton(text="💪 Упражнения", callback_data="video_cat_exercises")],
        [InlineKeyboardButton(text="🏆 Соревнования", callback_data="video_cat_competitions")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_upload")]
    ])

    await callback.message.answer(
        "🎥 <b>Загрузка видео</b>\n\nВыбери категорию:",
        parse_mode="HTML",
        reply_markup=categories_kb
    )
    await callback.answer()

@router.callback_query(F.data.startswith("video_cat_"))
async def video_category_selected(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    category = callback.data.replace("video_cat_", "")
    await state.update_data(video_category=category)

    category_names = {
        'lectures': 'Лекции',
        'technique': 'Техника',
        'exercises': 'Упражнения',
        'competitions': 'Соревнования'
    }

    await callback.message.edit_text(
        f"🎥 Категория: <b>{category_names.get(category, category)}</b>\n\n"
        f"Теперь отправь видео файл или перешли видео из чата.",
        parse_mode="HTML"
    )
    await state.set_state(ContentUpload.waiting_video_file)
    await callback.answer()

@router.message(ContentUpload.waiting_video_file, F.video)
async def video_file_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    # Сохраняем file_id видео, миниатюры и имя файла
    video_file_id = message.video.file_id
    thumbnail_id = message.video.thumbnail.file_id if message.video.thumbnail else None
    file_name = message.video.file_name or "video.mp4"

    await state.update_data(video_file_id=video_file_id, thumbnail_id=thumbnail_id, video_file_name=file_name)

    await message.answer(
        "✅ Видео получено!\n\n"
        "📝 Теперь отправь краткое описание видео (1-3 предложения):"
    )
    await state.set_state(ContentUpload.waiting_video_description)

@router.message(ContentUpload.waiting_video_description)
async def video_description_received(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    description = message.text
    data = await state.get_data()

    category = data.get('video_category', 'general')
    video_file_id = data.get('video_file_id')
    thumbnail_id = data.get('thumbnail_id')
    file_name = data.get('video_file_name', 'video.mp4')

    # Генерируем название из описания (первые 50 символов)
    title = description[:50] + "..." if len(description) > 50 else description

    # Сохраняем в БД
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            '''INSERT INTO lecture_videos (category, title, description, file_id, file_name, thumbnail_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (category, title, description, video_file_id, file_name, thumbnail_id, int(datetime.now().timestamp()))
        )
        await db.commit()

    response = f"✅ <b>Видео успешно добавлено!</b>\n\n"
    response += f"📌 <b>Название:</b> {title}\n"
    response += f"📝 <b>Описание:</b> {description}\n"
    response += f"📂 <b>Категория:</b> {category}\n\n"
    response += "🎉 Видео доступно в разделе Лекции!"

    await message.answer(response, parse_mode="HTML")
    await state.clear()

@router.callback_query(F.data == "cancel_upload")
async def cancel_upload(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Загрузка отменена")
    await callback.answer()

# ======================== ПРОСМОТР КОНТЕНТА ========================
@router.callback_query(F.data == "view_content")
async def view_content_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        pdf_count = (await (await db.execute('SELECT COUNT(*) FROM training_pdfs')).fetchone())[0]
        video_count = (await (await db.execute('SELECT COUNT(*) FROM lecture_videos')).fetchone())[0]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📄 PDF ({pdf_count})", callback_data="list_pdfs")],
        [InlineKeyboardButton(text=f"🎥 Видео ({video_count})", callback_data="list_videos")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
    ])

    await callback.message.edit_text(
        "📚 <b>Просмотр загруженного контента</b>\n\nВыбери тип контента:",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data == "list_pdfs")
async def list_pdfs(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT id, category, title, description, file_name, created_at FROM training_pdfs ORDER BY created_at DESC LIMIT 20'
        ) as cursor:
            pdfs = await cursor.fetchall()

    if not pdfs:
        await callback.answer("Нет загруженных PDF", show_alert=True)
        return

    text = "📄 <b>Загруженные PDF:</b>\n\n"
    for pdf_id, category, title, description, file_name, created_at in pdfs:
        date = datetime.fromtimestamp(created_at).strftime('%d.%m.%Y')
        text += f"<b>{title}</b>\n"
        text += f"📂 {category} | 📅 {date}\n"
        if file_name:
            text += f"📄 Файл: <code>{file_name}</code>\n"
        text += f"📝 {description}\n\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="view_content")]
    ])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "list_videos")
async def list_videos(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT id, category, title, description, file_name, created_at FROM lecture_videos ORDER BY created_at DESC LIMIT 20'
        ) as cursor:
            videos = await cursor.fetchall()

    if not videos:
        await callback.answer("Нет загруженных видео", show_alert=True)
        return

    text = "🎥 <b>Загруженные видео:</b>\n\n"
    for video_id, category, title, description, file_name, created_at in videos:
        date = datetime.fromtimestamp(created_at).strftime('%d.%m.%Y')
        text += f"<b>{title}</b>\n"
        text += f"📂 {category} | 📅 {date}\n"
        if file_name:
            text += f"🎬 Файл: <code>{file_name}</code>\n"
        text += f"📝 {description}\n\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="view_content")]
    ])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "ref_stats")
async def referral_stats(callback: CallbackQuery):
    """Детальная статистика по рефералам"""
    user_id = callback.from_user.id

    # Получаем список всех рефералов
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            '''SELECT u.username, u.name, r.created_at, u.subscription_until
               FROM referrals r
               JOIN users u ON r.referred_id = u.user_id
               WHERE r.referrer_id = ?
               ORDER BY r.created_at DESC LIMIT 20''',
            (user_id,)
        ) as cursor:
            referrals = await cursor.fetchall()

    rewards = await get_referral_rewards(user_id)

    if not referrals:
        text = (
            f"📊 <b>ДЕТАЛЬНАЯ СТАТИСТИКА</b>\n\n"
            f"У тебя пока нет приглашенных друзей.\n\n"
            f"Поделись своей ссылкой и получи первые бонусы! 🎁"
        )
    else:
        text = (
            f"📊 <b>ДЕТАЛЬНАЯ СТАТИСТИКА</b>\n\n"
            f"🏅 Уровень: {rewards['level']}\n"
            f"👥 Всего друзей: {rewards['count']}\n\n"
            f"📋 <b>Последние приглашенные:</b>\n\n"
        )

        for username, name, created_at, sub_until in referrals[:10]:
            date = datetime.fromtimestamp(created_at).strftime('%d.%m.%Y')
            display_name = name or username or "Пользователь"
            has_sub = "✅" if sub_until and sub_until > int(datetime.now().timestamp()) else "⏳"
            text += f"{has_sub} {display_name} — {date}\n"

        if rewards['count'] > 10:
            text += f"\n<i>... и еще {rewards['count'] - 10} друзей</i>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="close_stats")]
    ])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "close_stats")
async def close_stats(callback: CallbackQuery):
    """Закрыть статистику"""
    await callback.message.delete()
    await callback.answer()

# ======================== НАСТРОЙКИ ПОДПИСКИ ========================
class SubscriptionSettings(StatesGroup):
    waiting_price = State()
    waiting_channel_link = State()
    waiting_paid_video = State()
    waiting_secret_word = State()

@router.callback_query(F.data == "set_special_price")
async def set_special_price_menu(callback: CallbackQuery):
    """Меню управления ценой 1111₽"""
    if not is_admin(callback.from_user.id):
        return

    # Получаем статистику
    async with aiosqlite.connect(DB_PATH) as db:
        current_time = int(datetime.now().timestamp())

        # Общее количество пользователей с ценой 1111₽
        async with db.execute(
            'SELECT COUNT(*) FROM users WHERE special_price = 1111'
        ) as cursor:
            total_count = (await cursor.fetchone())[0]

        # Активные (в пределах grace period)
        async with db.execute(
            'SELECT COUNT(*) FROM users WHERE special_price = 1111 AND grace_period_until > ?',
            (current_time,)
        ) as cursor:
            active_count = (await cursor.fetchone())[0]

    text = (
        f"💰 <b>Управление ценой 1111₽</b>\n\n"
        f"Всего пользователей: <b>{total_count}</b>\n"
        f"✅ Активный период: <b>{active_count}</b>\n"
        f"⏰ Истёкший период: <b>{total_count - active_count}</b>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Установить по списку", callback_data="set_price_manual")],
        [InlineKeyboardButton(text="📋 Показать список", callback_data="show_special_price_users")],
        [InlineKeyboardButton(text="⏰ 7 дней", callback_data="set_days_7")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
    ])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "show_special_price_users")
async def show_special_price_users(callback: CallbackQuery):
    """Показать список пользователей с ценой 1111₽"""
    if not is_admin(callback.from_user.id):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        current_time = int(datetime.now().timestamp())

        # Получаем пользователей со спец ценой
        async with db.execute(
            '''SELECT user_id, name, username, grace_period_until, subscription_until
               FROM users WHERE special_price = 1111
               ORDER BY grace_period_until DESC LIMIT 30''',
        ) as cursor:
            users = await cursor.fetchall()

        # Общее количество
        async with db.execute(
            'SELECT COUNT(*) FROM users WHERE special_price = 1111'
        ) as cursor:
            total_count = (await cursor.fetchone())[0]

    if not users:
        await callback.answer("❌ Нет пользователей с ценой 1111₽", show_alert=True)
        return

    text = f"💰 <b>Пользователи с ценой 1111₽</b>\n\n"
    text += f"Всего: <b>{total_count}</b> пользователей\n\n"

    for user_id, name, username, grace_until, sub_until in users:
        display_name = name or username or f"ID {user_id}"

        # Проверяем активность льготного периода
        if grace_until and grace_until > current_time:
            grace_date = datetime.fromtimestamp(grace_until).strftime('%d.%m')
            status = f"✅ до {grace_date}"
        else:
            status = "⏰ Истёк"

        # Проверяем подписку
        if sub_until and sub_until > current_time:
            sub_status = "💎"
        else:
            sub_status = "❌"

        text += f"{sub_status} {display_name} ({status})\n"

    if total_count > 30:
        text += f"\n<i>Показаны первые 30 из {total_count}</i>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="set_special_price")]
    ])

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("set_days_"))
async def set_days_for_special_price(callback: CallbackQuery):
    """Установить количество дней для пользователей с ценой 1111₽"""
    if not is_admin(callback.from_user.id):
        return

    # Извлекаем количество дней из callback_data
    days = int(callback.data.split("_")[2])

    # Считаем сколько пользователей будет обновлено
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT COUNT(*) FROM users WHERE special_price = 1111'
        ) as cursor:
            count = (await cursor.fetchone())[0]

    if count == 0:
        await callback.answer("❌ Нет пользователей с ценой 1111₽", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, установить", callback_data=f"confirm_set_days_{days}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="set_special_price")]
    ])

    await callback.message.edit_text(
        f"⚠️ <b>Подтверждение</b>\n\n"
        f"Установить льготный период <b>{days} дней</b>\n"
        f"для <b>{count}</b> пользователей с ценой 1111₽?",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_set_days_"))
async def confirm_set_days(callback: CallbackQuery):
    """Подтверждение установки дней"""
    if not is_admin(callback.from_user.id):
        return

    days = int(callback.data.split("_")[3])

    await callback.message.edit_text("⏳ Устанавливаю льготный период...")

    grace_until = int((datetime.now() + timedelta(days=days)).timestamp())

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'UPDATE users SET grace_period_until = ? WHERE special_price = 1111',
            (grace_until,)
        )
        await db.commit()

        async with db.execute(
            'SELECT COUNT(*) FROM users WHERE special_price = 1111'
        ) as cursor:
            updated = (await cursor.fetchone())[0]

    grace_date = datetime.fromtimestamp(grace_until).strftime('%d.%m.%Y')

    await callback.message.edit_text(
        f"✅ <b>Готово!</b>\n\n"
        f"Обновлено: <b>{updated}</b> пользователей\n"
        f"Льготный период: <b>{days} дней</b>\n"
        f"Действует до: <b>{grace_date}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="set_special_price")]
        ])
    )
    await callback.answer()

@router.callback_query(F.data == "set_price_manual")
async def set_price_manual(callback: CallbackQuery, state: FSMContext):
    """Установить цену вручную списком"""
    if not is_admin(callback.from_user.id):
        return

    await state.set_state(SetPriceState.waiting_user_list)
    await callback.message.answer(
        "💰 <b>Установка специальной цены 1111₽</b>\n\n"
        "Отправьте список User ID построчно в формате:\n\n"
        "<code>User id: 670030071\n"
        "User id: 342534630\n"
        "User id: 463485998</code>\n\n"
        "Или просто ID через строку:\n"
        "<code>670030071\n"
        "342534630\n"
        "463485998</code>",
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "set_price_all")
async def set_price_all_confirm(callback: CallbackQuery):
    """Подтверждение установки цены всем"""
    if not is_admin(callback.from_user.id):
        return

    # Считаем сколько пользователей будет затронуто
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT COUNT(*) FROM users') as cursor:
            total_users = (await cursor.fetchone())[0]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, установить всем", callback_data="set_price_all_confirmed")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="set_special_price")]
    ])

    await callback.message.edit_text(
        f"⚠️ <b>Подтверждение</b>\n\n"
        f"Установить цену 1111₽ для <b>ВСЕХ {total_users} пользователей</b>?\n\n"
        f"Льготный период: 7 дней",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data == "set_price_all_confirmed")
async def set_price_all_confirmed(callback: CallbackQuery):
    """Установить цену всем пользователям"""
    if not is_admin(callback.from_user.id):
        return

    await callback.message.edit_text("⏳ Устанавливаю цену для всех пользователей...")

    grace_until = int((datetime.now() + timedelta(days=7)).timestamp())

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'UPDATE users SET special_price = ?, grace_period_until = ?',
            (1111, grace_until)
        )
        await db.commit()

        async with db.execute('SELECT COUNT(*) FROM users') as cursor:
            updated = (await cursor.fetchone())[0]

    grace_date = datetime.fromtimestamp(grace_until).strftime('%d.%m.%Y')

    await callback.message.edit_text(
        f"✅ <b>Готово!</b>\n\n"
        f"Установлена цена 1111₽ для <b>{updated}</b> пользователей\n\n"
        f"⏰ Льготная цена действует до <b>{grace_date}</b> (7 дней)",
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(SetPriceState.waiting_user_list)
async def process_special_price_list(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    text = message.text.strip()

    # Извлекаем все числа (user_id) из текста
    import re
    user_ids = list(set(re.findall(r'\d{6,}', text)))  # убираем дубликаты

    if not user_ids:
        await message.answer("❌ Не найдено ни одного User ID. Попробуйте снова.")
        return

    # Устанавливаем специальную цену для всех пользователей
    grace_until = int((datetime.now() + timedelta(days=7)).timestamp())
    created = 0
    updated = 0

    async with aiosqlite.connect(DB_PATH) as db:
        for user_id_str in user_ids:
            user_id = int(user_id_str)

            # Проверяем существует ли пользователь
            async with db.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,)) as cursor:
                exists = await cursor.fetchone()

            if exists:
                # Обновляем существующего
                await db.execute(
                    'UPDATE users SET special_price = ?, grace_period_until = ? WHERE user_id = ?',
                    (1111, grace_until, user_id)
                )
                updated += 1
            else:
                # Создаем нового
                await db.execute(
                    'INSERT INTO users (user_id, special_price, grace_period_until, created_at) VALUES (?, ?, ?, ?)',
                    (user_id, 1111, grace_until, int(datetime.now().timestamp()))
                )
                created += 1

        await db.commit()

    total = created + updated
    status_text = []
    if created > 0:
        status_text.append(f"🆕 Создано новых: {created}")
    if updated > 0:
        status_text.append(f"✏️ Обновлено: {updated}")

    await message.answer(
        f"✅ <b>Готово!</b>\n\n"
        f"Установлена цена 1111₽ для {total} пользователей\n"
        + "\n".join(status_text) + "\n\n"
        f"ID: {', '.join(user_ids[:10])}"
        f"{'...' if len(user_ids) > 10 else ''}\n\n"
        f"⏰ Льготная цена действует 7 дней.\n"
        f"Если они не продлят подписку, цена автоматически вернётся к 2222₽.",
        parse_mode="HTML"
    )
    await state.clear()

@router.callback_query(F.data == "subscription_settings")
async def subscription_settings_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    price = await get_price()
    channel_link = await get_channel_link()
    secret_word = await get_secret_word()
    paid_video = await get_paid_video()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💰 Цена: {price} ₽", callback_data="set_price")],
        [InlineKeyboardButton(text="🔗 Ссылка на канал", callback_data="set_channel_link")],
        [InlineKeyboardButton(text="🎥 Видео после оплаты", callback_data="set_paid_video")],
        [InlineKeyboardButton(text=f"🔑 Кодовое слово: {secret_word}", callback_data="set_secret_word")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
    ])

    status_video = "✅ Установлено" if paid_video else "❌ Не установлено"
    status_link = "✅ Установлена" if channel_link else "❌ Не установлена"

    await callback.message.edit_text(
        f"⚙️ <b>Настройки подписки</b>\n\n"
        f"💰 Цена: <b>{price} ₽</b>\n"
        f"🔗 Ссылка на канал: {status_link}\n"
        f"🎥 Видео после оплаты: {status_video}\n"
        f"🔑 Кодовое слово: <b>{secret_word}</b>",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data == "set_price")
async def set_price_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await callback.message.answer("💰 Введи новую цену подписки (в рублях):")
    await state.set_state(SubscriptionSettings.waiting_price)
    await callback.answer()

@router.message(SubscriptionSettings.waiting_price)
async def set_price_handler(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    try:
        price = int(message.text)
        await set_price(price)
        await message.answer(
            f"✅ Цена установлена: <b>{price} ₽</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К настройкам", callback_data="subscription_settings")]
            ])
        )
    except ValueError:
        await message.answer("❌ Введи число!")
        return

    await state.clear()

@router.callback_query(F.data == "set_channel_link")
async def set_channel_link_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await callback.message.answer("🔗 Введи ссылку на канал (например: https://t.me/+abc123):")
    await state.set_state(SubscriptionSettings.waiting_channel_link)
    await callback.answer()

@router.message(SubscriptionSettings.waiting_channel_link)
async def set_channel_link_handler(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    link = message.text.strip()
    await set_channel_link(link)
    await message.answer(
        f"✅ Ссылка установлена!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К настройкам", callback_data="subscription_settings")]
        ])
    )
    await state.clear()

@router.callback_query(F.data == "set_paid_video")
async def set_paid_video_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await callback.message.answer("🎥 Отправь видео, которое будет показано после оплаты:")
    await state.set_state(SubscriptionSettings.waiting_paid_video)
    await callback.answer()

@router.message(SubscriptionSettings.waiting_paid_video, F.video)
async def set_paid_video_handler(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    video_id = message.video.file_id
    await set_paid_video(video_id)
    await message.answer(
        "✅ Видео после оплаты установлено!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К настройкам", callback_data="subscription_settings")]
        ])
    )
    await state.clear()

@router.callback_query(F.data == "set_secret_word")
async def set_secret_word_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return

    await callback.message.answer("🔑 Введи новое кодовое слово (одно слово, без пробелов):")
    await state.set_state(SubscriptionSettings.waiting_secret_word)
    await callback.answer()

@router.message(SubscriptionSettings.waiting_secret_word)
async def set_secret_word_handler(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    word = message.text.strip().lower().split()[0]  # Берём первое слово
    await set_secret_word(word)
    await message.answer(
        f"✅ Кодовое слово установлено: <b>{word}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К настройкам", callback_data="subscription_settings")]
        ])
    )
    await state.clear()

# ======================== ОБРАБОТЧИКИ С STATE (ДОЛЖНЫ БЫТЬ ВЫШЕ F.text) ========================
@router.message(GrantSubscriptionState.waiting_user_id)
async def process_grant_user_id_moved(message: Message, state: FSMContext):
    """Обработка user_id"""
    logging.info(f"[GRANT] Получен User ID от {message.from_user.id}: {message.text}")

    if not is_admin(message.from_user.id):
        logging.warning(f"[GRANT] Не админ пытается отправить User ID")
        return

    try:
        user_id = int(message.text.strip())
        await state.update_data(user_id=user_id)

        logging.info(f"[GRANT] User ID {user_id} сохранен, запрашиваем дни")
        await message.answer(
            f"👤 User ID: <code>{user_id}</code>\n\n"
            "📅 Отправьте количество дней подписки:",
            parse_mode="HTML"
        )
        await state.set_state(GrantSubscriptionState.waiting_days)

    except ValueError:
        logging.error(f"[GRANT] Неверный формат User ID: {message.text}")
        await message.answer("❌ Неверный формат. Введите числовой User ID:")

@router.message(GrantSubscriptionState.waiting_days)
async def process_grant_days_moved(message: Message, state: FSMContext):
    """Обработка количества дней и запрос уведомления"""
    if not is_admin(message.from_user.id):
        return

    try:
        days = int(message.text.strip())
        if days <= 0:
            await message.answer("❌ Количество дней должно быть больше 0")
            return

        data = await state.get_data()
        user_id = data['user_id']

        await state.update_data(days=days)

        until_date = (datetime.now() + timedelta(days=days)).strftime('%d.%m.%Y %H:%M')

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, уведомить", callback_data="grant_notify_yes")],
            [InlineKeyboardButton(text="❌ Нет, не уведомлять", callback_data="grant_notify_no")]
        ])

        await message.answer(
            f"📋 <b>Подтверждение</b>\n\n"
            f"🆔 User ID: <code>{user_id}</code>\n"
            f"📅 Дней: {days}\n"
            f"⏰ До: {until_date}\n\n"
            f"Уведомить пользователя?",
            parse_mode="HTML",
            reply_markup=kb
        )

    except ValueError:
        await message.answer("❌ Неверный формат. Введите количество дней числом:")

# ======================== ОБРАБОТЧИК КОДОВОГО СЛОВА ========================
@router.message(F.text)
async def secret_word_handler(message: Message, state: FSMContext):
    """Проверка кодового слова для получения ссылки на канал"""
    user_id = message.from_user.id

    # Если есть активное состояние FSM - пропускаем этот обработчик
    current_state = await state.get_state()
    if current_state is not None:
        logging.info(f"[SECRET_WORD] Пропускаем - активен state: {current_state}")
        return

    # Если это команда (начинается с /) - пропускаем
    if message.text.startswith('/'):
        logging.info(f"[SECRET_WORD] Пропускаем команду: {message.text}")
        return

    logging.info(f"[SECRET_WORD] Проверяем кодовое слово от {user_id}")
    text = message.text.strip().lower()

    secret_word = await get_secret_word()

    if text == secret_word:
        # Проверяем есть ли активная подписка
        if await has_active_subscription(user_id):
            # Генерируем одноразовую ссылку
            invite_link = await generate_one_time_invite()

            if invite_link:
                await message.answer(
                    f"🎉 <b>Поздравляем!</b>\n\n"
                    f"Вот твоя персональная ссылка на канал:\n{invite_link}\n\n"
                    f"⚠️ Ссылка одноразовая - используй её только для себя!\n\n"
                    f"Добро пожаловать в КЛС!",
                    parse_mode="HTML"
                )
            else:
                # Если не удалось создать ссылку - используем запасную
                await message.answer(
                    f"🎉 <b>Поздравляем!</b>\n\n"
                    f"Вот ссылка на канал:\n{FALLBACK_CHANNEL_LINK}\n\n"
                    f"Добро пожаловать в КЛС!",
                    parse_mode="HTML"
                )
        else:
            await message.answer(
                "❌ У тебя нет активной подписки.\n\n"
                "Оплати подписку, чтобы получить доступ к каналу!"
            )

# ======================== НОВАЯ СИСТЕМА РАССЫЛКИ ========================
@router.callback_query(F.data == "broadcast_menu")
async def broadcast_menu(callback: CallbackQuery):
    """Меню рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Рассылка с текстом", callback_data="new_broadcast_start")],
        [InlineKeyboardButton(text="🤖 AI рассылка (без подписки)", callback_data="ai_broadcast")],
        [InlineKeyboardButton(text="👁 Превью AI рассылки", callback_data="preview_broadcast_me")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_admin")]
    ])

    await callback.message.edit_text(
        "📨 <b>Меню рассылки</b>\n\n"
        "Выберите тип рассылки:",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()

@router.callback_query(F.data == "new_broadcast_start")
async def new_broadcast_start(callback: CallbackQuery, state: FSMContext):
    """Начало новой рассылки - ввод текста"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    await state.set_state(NewBroadcastState.waiting_text)
    await callback.message.answer(
        "📝 <b>Шаг 1/3: Текст рассылки</b>\n\n"
        "Отправьте текст сообщения для рассылки.\n\n"
        "Можете использовать HTML теги:\n"
        "<code>&lt;b&gt;жирный&lt;/b&gt;</code>\n"
        "<code>&lt;i&gt;курсив&lt;/i&gt;</code>\n"
        "<code>&lt;code&gt;код&lt;/code&gt;</code>",
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(NewBroadcastState.waiting_text)
async def new_broadcast_text_received(message: Message, state: FSMContext):
    """Получен текст рассылки"""
    if not is_admin(message.from_user.id):
        return

    text = message.text or message.caption
    if not text:
        await message.answer("❌ Отправьте текстовое сообщение")
        return

    await state.update_data(broadcast_text=text)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📷 Добавить фото", callback_data="add_photo")],
        [InlineKeyboardButton(text="🎥 Добавить видео", callback_data="add_video")],
        [InlineKeyboardButton(text="➡️ Пропустить (только текст)", callback_data="skip_media")]
    ])

    await message.answer(
        "✅ <b>Шаг 2/3: Медиа (опционально)</b>\n\n"
        "Хотите добавить фото или видео?\n\n"
        f"Ваш текст:\n{text[:100]}{'...' if len(text) > 100 else ''}",
        parse_mode="HTML",
        reply_markup=kb
    )

@router.callback_query(F.data.in_(["add_photo", "add_video"]))
async def add_media_type(callback: CallbackQuery, state: FSMContext):
    """Выбор типа медиа"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    media_type = "photo" if callback.data == "add_photo" else "video"
    await state.update_data(media_type=media_type)
    await state.set_state(NewBroadcastState.waiting_media)

    emoji = "📷 фото" if media_type == "photo" else "🎥 видео"
    await callback.message.edit_text(
        f"📤 <b>Отправьте {emoji}</b>\n\n"
        f"Загрузите {'фотографию' if media_type == 'photo' else 'видео'} для рассылки.",
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "skip_media")
async def skip_media(callback: CallbackQuery, state: FSMContext):
    """Пропуск медиа - переход к выбору аудитории"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    await show_audience_selection(callback.message, state)
    await callback.answer()

@router.message(NewBroadcastState.waiting_media, F.photo)
async def broadcast_photo_received(message: Message, state: FSMContext):
    """Получено фото"""
    if not is_admin(message.from_user.id):
        return

    photo_id = message.photo[-1].file_id
    await state.update_data(media_file_id=photo_id)
    await show_audience_selection(message, state)

@router.message(NewBroadcastState.waiting_media, F.video)
async def broadcast_video_received(message: Message, state: FSMContext):
    """Получено видео"""
    if not is_admin(message.from_user.id):
        return

    video_id = message.video.file_id
    await state.update_data(media_file_id=video_id)
    await show_audience_selection(message, state)

async def show_audience_selection(message: Message, state: FSMContext):
    """Показать выбор аудитории"""
    # Считаем пользователей
    async with aiosqlite.connect(DB_PATH) as db:
        current_time = int(datetime.now().timestamp())

        # Всего пользователей
        async with db.execute('SELECT COUNT(*) FROM users') as cursor:
            total = (await cursor.fetchone())[0]

        # Без подписки
        async with db.execute(
            'SELECT COUNT(*) FROM users WHERE subscription_until IS NULL OR subscription_until < ?',
            (current_time,)
        ) as cursor:
            no_sub = (await cursor.fetchone())[0]

        # С подпиской
        with_sub = total - no_sub

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📢 Всем ({total} чел.)", callback_data="send_to_all")],
        [InlineKeyboardButton(text=f"❌ Только без подписки ({no_sub} чел.)", callback_data="send_to_no_sub")],
        [InlineKeyboardButton(text=f"✅ Только с подпиской ({with_sub} чел.)", callback_data="send_to_with_sub")],
        [InlineKeyboardButton(text="🚫 Отмена", callback_data="cancel_broadcast")]
    ])

    await message.answer(
        "👥 <b>Шаг 3/3: Кому отправить?</b>\n\n"
        f"📊 Всего пользователей: {total}\n"
        f"✅ С подпиской: {with_sub}\n"
        f"❌ Без подписки: {no_sub}\n\n"
        "Выберите аудиторию:",
        parse_mode="HTML",
        reply_markup=kb
    )
    await state.set_state(NewBroadcastState.confirm_send)

@router.callback_query(F.data.in_(["send_to_all", "send_to_no_sub", "send_to_with_sub"]))
async def confirm_and_send_broadcast(callback: CallbackQuery, state: FSMContext):
    """Подтверждение и отправка рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещен", show_alert=True)
        return

    data = await state.get_data()
    text = data.get('broadcast_text')
    media_type = data.get('media_type')
    media_file_id = data.get('media_file_id')

    target = callback.data  # send_to_all / send_to_no_sub / send_to_with_sub

    await callback.message.edit_text("📨 Отправляю рассылку...")

    # Получаем пользователей
    async with aiosqlite.connect(DB_PATH) as db:
        current_time = int(datetime.now().timestamp())

        if target == "send_to_all":
            query = 'SELECT user_id FROM users'
            params = ()
        elif target == "send_to_no_sub":
            query = 'SELECT user_id FROM users WHERE subscription_until IS NULL OR subscription_until < ?'
            params = (current_time,)
        else:  # send_to_with_sub
            query = 'SELECT user_id FROM users WHERE subscription_until IS NOT NULL AND subscription_until >= ?'
            params = (current_time,)

        async with db.execute(query, params) as cursor:
            users = await cursor.fetchall()

    sent_count = 0
    failed_count = 0

    for row in users:
        user_id = row[0]
        try:
            # Отправляем в зависимости от типа
            if media_file_id and media_type == "photo":
                await bot.send_photo(user_id, photo=media_file_id, caption=text, parse_mode="HTML")
            elif media_file_id and media_type == "video":
                await bot.send_video(user_id, video=media_file_id, caption=text, parse_mode="HTML")
            else:
                await bot.send_message(user_id, text=text, parse_mode="HTML")

            sent_count += 1
            await asyncio.sleep(0.05)  # Небольшая задержка
        except Exception as e:
            failed_count += 1
            logging.error(f"[BROADCAST ERROR] User {user_id}: {e}")

    await callback.message.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📨 Отправлено: {sent_count}\n"
        f"❌ Ошибок: {failed_count}",
        parse_mode="HTML"
    )
    await state.clear()
    await callback.answer()

@router.callback_query(F.data == "cancel_broadcast")
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    """Отмена рассылки"""
    await state.clear()
    await callback.message.edit_text("🚫 Рассылка отменена")
    await callback.answer()

@router.callback_query(F.data == "back_to_admin")
async def back_to_admin(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text(get_admin_panel_text(), reply_markup=admin_kb(), parse_mode="HTML")
    await callback.answer()

# ======================== ВЫДАЧА ПОДПИСКИ ========================
@router.message(Command("grant"))
async def grant_subscription_command(message: Message, state: FSMContext):
    """Команда для выдачи подписки"""
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "✅ <b>Выдача подписки</b>\n\n"
        "Отправьте User ID пользователя:",
        parse_mode="HTML"
    )
    await state.set_state(GrantSubscriptionState.waiting_user_id)

@router.callback_query(F.data == "grant_subscription")
async def grant_subscription_start(callback: CallbackQuery, state: FSMContext):
    """Начало выдачи подписки через кнопку"""
    logging.info(f"[GRANT] Callback grant_subscription от {callback.from_user.id}")

    if not is_admin(callback.from_user.id):
        logging.warning(f"[GRANT] Не админ: {callback.from_user.id}")
        await callback.answer("❌ Доступ запрещен", show_alert=True)
        return

    logging.info(f"[GRANT] Админ подтвержден, запрашиваем User ID")
    await callback.message.answer(
        "✅ <b>Выдача подписки</b>\n\n"
        "Отправьте User ID пользователя:",
        parse_mode="HTML"
    )
    await state.set_state(GrantSubscriptionState.waiting_user_id)
    await callback.answer()

@router.message(GrantSubscriptionState.waiting_user_id)
async def process_grant_user_id(message: Message, state: FSMContext):
    """Обработка user_id"""
    logging.info(f"[GRANT] Получен User ID от {message.from_user.id}: {message.text}")

    if not is_admin(message.from_user.id):
        logging.warning(f"[GRANT] Не админ пытается отправить User ID")
        return

    try:
        user_id = int(message.text.strip())
        await state.update_data(user_id=user_id)

        logging.info(f"[GRANT] User ID {user_id} сохранен, запрашиваем дни")
        await message.answer(
            f"👤 User ID: <code>{user_id}</code>\n\n"
            "📅 Отправьте количество дней подписки:",
            parse_mode="HTML"
        )
        await state.set_state(GrantSubscriptionState.waiting_days)

    except ValueError:
        logging.error(f"[GRANT] Неверный формат User ID: {message.text}")
        await message.answer("❌ Неверный формат. Введите числовой User ID:")

@router.message(GrantSubscriptionState.waiting_days)
async def process_grant_days(message: Message, state: FSMContext):
    """Обработка количества дней и запрос уведомления"""
    if not is_admin(message.from_user.id):
        return

    try:
        days = int(message.text.strip())
        if days <= 0:
            await message.answer("❌ Количество дней должно быть больше 0")
            return

        data = await state.get_data()
        user_id = data['user_id']

        await state.update_data(days=days)

        until_date = (datetime.now() + timedelta(days=days)).strftime('%d.%m.%Y %H:%M')

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, уведомить", callback_data="grant_notify_yes")],
            [InlineKeyboardButton(text="❌ Нет, не уведомлять", callback_data="grant_notify_no")]
        ])

        await message.answer(
            f"📋 <b>Подтверждение</b>\n\n"
            f"🆔 User ID: <code>{user_id}</code>\n"
            f"📅 Дней: {days}\n"
            f"⏰ До: {until_date}\n\n"
            f"Уведомить пользователя?",
            parse_mode="HTML",
            reply_markup=kb
        )

    except ValueError:
        await message.answer("❌ Неверный формат. Введите количество дней числом:")

@router.callback_query(F.data.startswith("grant_notify_"))
async def process_grant_confirm(callback: CallbackQuery, state: FSMContext):
    """Выдача подписки с уведомлением или без"""
    if not is_admin(callback.from_user.id):
        return

    notify = callback.data == "grant_notify_yes"
    data = await state.get_data()
    user_id = data['user_id']
    days = data['days']

    # Проверяем существует ли пользователь
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT user_id, name, username FROM users WHERE user_id = ?', (user_id,)) as cursor:
            user = await cursor.fetchone()

        if not user:
            # Создаем пользователя если не существует
            await db.execute(
                'INSERT INTO users (user_id, created_at) VALUES (?, ?)',
                (user_id, int(datetime.now().timestamp()))
            )
            await db.commit()
            user_name = f"ID {user_id}"
        else:
            user_name = user[1] or user[2] or f"ID {user_id}"

    # Активируем подписку
    await activate_subscription(user_id, days)

    until_date = (datetime.now() + timedelta(days=days)).strftime('%d.%m.%Y %H:%M')

    result_text = (
        f"✅ <b>Подписка выдана!</b>\n\n"
        f"👤 Пользователь: {user_name}\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"📅 Дней: {days}\n"
        f"⏰ Действует до: {until_date}"
    )

    # Уведомляем пользователя если нужно
    if notify:
        try:
            # Генерируем одноразовую ссылку
            invite_link = await generate_one_time_invite()

            if invite_link:
                await bot.send_message(
                    user_id,
                    f"🎉 <b>Вам выдана подписка!</b>\n\n"
                    f"📅 Срок: {days} дней\n"
                    f"⏰ Действует до: {until_date}\n\n"
                    f"🔗 <b>Ваша персональная ссылка на канал:</b>\n{invite_link}\n\n"
                    f"⚠️ Ссылка одноразовая - используй её только для себя!\n\n"
                    f"Добро пожаловать в КЛС!",
                    parse_mode="HTML"
                )
                result_text += "\n\n✅ Пользователь уведомлен с одноразовой ссылкой"
            else:
                # Если не удалось создать одноразовую ссылку
                await bot.send_message(
                    user_id,
                    f"🎉 <b>Вам выдана подписка!</b>\n\n"
                    f"📅 Срок: {days} дней\n"
                    f"⏰ Действует до: {until_date}\n\n"
                    f"Теперь у вас есть полный доступ ко всем материалам!",
                    parse_mode="HTML"
                )
                result_text += "\n\n✅ Пользователь уведомлен (без ссылки)"
        except Exception as e:
            result_text += f"\n\n⚠️ Не удалось уведомить: {e}"
    else:
        result_text += "\n\n🔕 Пользователь не уведомлен"

    await callback.message.edit_text(result_text, parse_mode="HTML")
    await state.clear()
    await callback.answer()

# ======================== ЗАПУСК ========================
async def main():
    await init_db()
    load_fallback_messages()
    dp.include_router(router)

    # Первый экспорт при запуске
    if GOOGLE_SHEETS_URL:
        try:
            success, message = await google_sheets.export_referrals_to_sheet(
                spreadsheet_url=GOOGLE_SHEETS_URL
            )
            if success:
                logging.info(f"✅ Начальный экспорт рефералов: {message}")
        except Exception as e:
            logging.warning(f"⚠️ Ошибка начального экспорта: {e}")

    # Запускаем периодический экспорт рефералов в фоне
    asyncio.create_task(periodic_export_referrals())
    logging.info("🔄 Периодический экспорт рефералов запущен (каждые 5 минут)")

    # Запускаем планировщик рассылки для пользователей без подписки
    asyncio.create_task(subscription_reminder_scheduler())
    logging.info(f"📨 Планировщик рассылки запущен (каждые {BROADCAST_INTERVAL_HOURS} часов)")

    # Запускаем проверку истёкших подписок
    asyncio.create_task(subscription_checker_scheduler())
    logging.info("🔒 Проверка подписок запущена (каждые 5 минут)")

    # Запускаем отправку уведомлений о скором истечении подписки
    asyncio.create_task(subscription_notification_scheduler())
    logging.info("⏰ Уведомления о подписке запущены (каждый час)")

    logging.info("🚀 Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
