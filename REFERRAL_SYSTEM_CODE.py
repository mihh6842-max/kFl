"""
═══════════════════════════════════════════════════════════════════
РЕФЕРАЛЬНАЯ СИСТЕМА - ИСХОДНЫЙ КОД
═══════════════════════════════════════════════════════════════════

Этот файл содержит все ключевые функции реферальной системы.
Код уже встроен в bot.py, это справочный файл для понимания логики.
"""

import aiosqlite
from datetime import datetime
import logging

DB_PATH = 'data/bot.db'
BOT_USERNAME = "ваш_бот"  # Замените на username вашего бота

# ═══════════════════════════════════════════════════════════════════
# 1. СОЗДАНИЕ ТАБЛИЦЫ РЕФЕРАЛОВ В БД
# ═══════════════════════════════════════════════════════════════════

async def init_referral_db():
    """Создает таблицу рефералов и добавляет колонку earnings"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица связей: кто кого пригласил
        await db.execute('''CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            created_at INTEGER,
            UNIQUE(referrer_id, referred_id)
        )''')

        # Колонка для заработка с рефералов
        try:
            await db.execute('ALTER TABLE users ADD COLUMN referral_earnings REAL DEFAULT 0')
        except:
            pass  # Колонка уже есть

        await db.commit()


# ═══════════════════════════════════════════════════════════════════
# 2. ГЕНЕРАЦИЯ РЕФЕРАЛЬНОЙ ССЫЛКИ
# ═══════════════════════════════════════════════════════════════════

async def get_referral_link(user_id: int) -> str:
    """
    Генерирует реферальную ссылку вида:
    https://t.me/ваш_бот?start=ref_123456789
    """
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"


# ═══════════════════════════════════════════════════════════════════
# 3. СОХРАНЕНИЕ РЕФЕРАЛА ПРИ СТАРТЕ БОТА
# ═══════════════════════════════════════════════════════════════════

async def save_referral(referrer_id: int, referred_id: int):
    """
    Сохраняет связь реферала в базу данных

    Args:
        referrer_id: ID пригласившего пользователя
        referred_id: ID приглашенного пользователя
    """
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Проверяем что пользователь не приглашает сам себя
            if referrer_id == referred_id:
                return False

            # Сохраняем связь
            await db.execute(
                'INSERT OR IGNORE INTO referrals (referrer_id, referred_id, created_at) VALUES (?, ?, ?)',
                (referrer_id, referred_id, int(datetime.now().timestamp()))
            )
            await db.commit()
            return True
    except Exception as e:
        logging.error(f"Ошибка сохранения реферала: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════
# 4. ОБРАБОТКА КОМАНДЫ /start С РЕФЕРАЛЬНОЙ ССЫЛКОЙ
# ═══════════════════════════════════════════════════════════════════

async def handle_start_with_referral(message, user_id: int):
    """
    Обрабатывает команду /start с параметром ref_XXXXXX

    Пример: /start ref_123456789
    """
    # Извлекаем referrer_id из команды
    args = message.text.split()

    if len(args) > 1 and args[1].startswith('ref_'):
        try:
            referrer_id = int(args[1].replace('ref_', ''))

            # Проверяем что пользователь новый
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    'SELECT user_id FROM users WHERE user_id = ?',
                    (user_id,)
                ) as cursor:
                    existing = await cursor.fetchone()

            # Если пользователь новый - сохраняем реферала
            if not existing:
                success = await save_referral(referrer_id, user_id)

                if success:
                    # Уведомляем пригласившего
                    await notify_referrer(referrer_id, user_id)
                    return True
        except Exception as e:
            logging.error(f"Ошибка обработки реферальной ссылки: {e}")

    return False


async def notify_referrer(referrer_id: int, referred_id: int):
    """Отправляет уведомление пригласившему о новом реферале"""
    from aiogram import Bot

    # Получаем информацию о новом пользователе
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT name, username FROM users WHERE user_id = ?',
            (referred_id,)
        ) as cursor:
            user_data = await cursor.fetchone()

    if user_data:
        name, username = user_data
        display_name = name or username or f"ID {referred_id}"

        # Считаем всех рефералов
        ref_count = await get_referral_count(referrer_id)

        message = (
            f"🎉 <b>Новый реферал!</b>\n\n"
            f"👤 {display_name} присоединился по твоей ссылке!\n\n"
            f"Всего приглашенных: <b>{ref_count}</b> чел."
        )

        # Отправляем уведомление (нужен инициализированный bot)
        # await bot.send_message(referrer_id, message, parse_mode="HTML")


# ═══════════════════════════════════════════════════════════════════
# 5. ПОДСЧЕТ РЕФЕРАЛОВ
# ═══════════════════════════════════════════════════════════════════

async def get_referral_count(user_id: int) -> int:
    """Возвращает количество приглашенных пользователей"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT COUNT(*) FROM referrals WHERE referrer_id = ?',
            (user_id,)
        ) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else 0


async def get_paid_referrals_count(user_id: int) -> int:
    """Возвращает количество рефералов, которые оплатили подписку"""
    now = int(datetime.now().timestamp())

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('''
            SELECT COUNT(*) FROM referrals r
            JOIN users u ON r.referred_id = u.user_id
            WHERE r.referrer_id = ?
            AND u.subscription_until IS NOT NULL
            AND u.subscription_until > ?
        ''', (user_id, now)) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else 0


# ═══════════════════════════════════════════════════════════════════
# 6. СИСТЕМА НАГРАД И УРОВНЕЙ
# ═══════════════════════════════════════════════════════════════════

async def get_referral_rewards(user_id: int) -> dict:
    """
    Рассчитывает награды и уровень реферала

    Returns:
        dict: {
            'count': количество рефералов,
            'paid_count': количество оплативших,
            'level': уровень (Новичок, Активист и т.д.),
            'reward': описание награды,
            'next_level': следующий уровень,
            'next_reward': следующая награда,
            'progress': прогресс до следующего уровня
        }
    """
    count = await get_referral_count(user_id)
    paid_count = await get_paid_referrals_count(user_id)

    # Система уровней
    levels = [
        (0, "🌱 Новичок", "Пригласи друзей!", 3),
        (3, "🔥 Активист", "Скидка 10% на подписку", 5),
        (5, "⭐ Амбассадор", "Скидка 15% на подписку", 10),
        (10, "💎 VIP", "Скидка 20% + бонусный контент", 20),
        (20, "👑 Легенда", "Максимальные привилегии", float('inf'))
    ]

    # Определяем текущий уровень
    current_level = levels[0]
    next_level = None

    for i, level in enumerate(levels):
        if count >= level[0]:
            current_level = level
            if i + 1 < len(levels):
                next_level = levels[i + 1]

    # Прогресс до следующего уровня
    if next_level:
        progress = count - current_level[0]
        needed = next_level[0] - current_level[0]
        progress_percent = int((progress / needed) * 100)
    else:
        progress_percent = 100

    return {
        'count': count,
        'paid_count': paid_count,
        'level': current_level[1],
        'reward': current_level[2],
        'next_level': next_level[1] if next_level else None,
        'next_reward': next_level[2] if next_level else None,
        'progress': progress_percent,
        'needed': next_level[0] if next_level else 0
    }


# ═══════════════════════════════════════════════════════════════════
# 7. НАЧИСЛЕНИЕ БОНУСОВ ЗА ОПЛАТУ РЕФЕРАЛА
# ═══════════════════════════════════════════════════════════════════

async def reward_referrer_for_payment(referred_id: int, payment_amount: float):
    """
    Начисляет бонус пригласившему, когда реферал оплачивает подписку

    Args:
        referred_id: ID пользователя который оплатил
        payment_amount: сумма платежа
    """
    # Находим кто пригласил этого пользователя
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT referrer_id FROM referrals WHERE referred_id = ?',
            (referred_id,)
        ) as cursor:
            result = await cursor.fetchone()

        if result:
            referrer_id = result[0]

            # Начисляем 10% от суммы платежа
            bonus = payment_amount * 0.1

            await db.execute(
                'UPDATE users SET referral_earnings = referral_earnings + ? WHERE user_id = ?',
                (bonus, referrer_id)
            )
            await db.commit()

            # Уведомляем пригласившего
            # await bot.send_message(
            #     referrer_id,
            #     f"💰 Твой реферал оплатил подписку!\n"
            #     f"Начислено: {bonus:.2f}₽"
            # )


# ═══════════════════════════════════════════════════════════════════
# 8. ПОЛУЧЕНИЕ СПИСКА РЕФЕРАЛОВ
# ═══════════════════════════════════════════════════════════════════

async def get_referral_list(user_id: int, limit: int = 50):
    """
    Возвращает список всех рефералов пользователя

    Returns:
        list: [(username, name, created_at, subscription_until), ...]
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('''
            SELECT u.username, u.name, r.created_at, u.subscription_until
            FROM referrals r
            JOIN users u ON r.referred_id = u.user_id
            WHERE r.referrer_id = ?
            ORDER BY r.created_at DESC
            LIMIT ?
        ''', (user_id, limit)) as cursor:
            return await cursor.fetchall()


# ═══════════════════════════════════════════════════════════════════
# ПРИМЕР ИСПОЛЬЗОВАНИЯ
# ═══════════════════════════════════════════════════════════════════

"""
# 1. При запуске бота создаем таблицы
await init_referral_db()

# 2. При обработке /start проверяем реферальную ссылку
@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id

    # Обрабатываем реферальную ссылку
    await handle_start_with_referral(message, user_id)

    # ... остальная логика старта

# 3. Показываем реферальную ссылку пользователю
@router.message(F.text == "👥 Пригласить друга")
async def referral_button(message: Message):
    user_id = message.from_user.id

    # Получаем данные
    rewards = await get_referral_rewards(user_id)
    ref_link = await get_referral_link(user_id)

    text = (
        f"🎁 <b>РЕФЕРАЛЬНАЯ ПРОГРАММА</b>\n\n"
        f"Твой уровень: {rewards['level']}\n"
        f"Приглашено: {rewards['count']} чел.\n"
        f"Оплатили: {rewards['paid_count']} чел.\n\n"
        f"Твоя ссылка:\n{ref_link}"
    )

    await message.answer(text, parse_mode="HTML")

# 4. При оплате начисляем бонус пригласившему
async def handle_successful_payment(user_id: int, amount: float):
    # ... логика подписки

    # Начисляем бонус пригласившему
    await reward_referrer_for_payment(user_id, amount)
"""
