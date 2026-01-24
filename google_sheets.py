"""
Модуль для работы с Google Таблицами
"""
import gspread
from google.oauth2.service_account import Credentials
import aiosqlite
from datetime import datetime
import logging
import os

# Путь к базе данных
DB_PATH = 'data/bot.db'

# Настройка области доступа
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# Путь к файлу с credentials
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), 'credentials.json')


def get_google_sheets_client():
    """Создает и возвращает клиент для работы с Google Sheets"""
    try:
        credentials = Credentials.from_service_account_file(
            CREDENTIALS_FILE,
            scopes=SCOPES
        )
        client = gspread.authorize(credentials)
        return client
    except Exception as e:
        logging.error(f"Ошибка подключения к Google Sheets: {e}")
        return None


async def export_users_to_sheet(spreadsheet_url: str = None, spreadsheet_id: str = None):
    """
    Экспортирует данные пользователей в Google Таблицу

    Args:
        spreadsheet_url: URL таблицы (например, https://docs.google.com/spreadsheets/d/ВАШ_ID/edit)
        spreadsheet_id: ID таблицы (можно использовать вместо URL)
    """
    try:
        # Подключаемся к Google Sheets
        client = get_google_sheets_client()
        if not client:
            return False, "Ошибка подключения к Google Sheets"

        # Открываем таблицу
        if spreadsheet_url:
            sheet = client.open_by_url(spreadsheet_url).sheet1
        elif spreadsheet_id:
            sheet = client.open_by_key(spreadsheet_id).sheet1
        else:
            return False, "Не указан URL или ID таблицы"

        # Получаем данные из БД
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT
                    user_id,
                    username,
                    phone,
                    subscription_until,
                    name,
                    age,
                    gender,
                    goal,
                    level,
                    created_at
                FROM users
                ORDER BY created_at DESC
            ''') as cursor:
                users = await cursor.fetchall()

        # Заголовки таблицы
        headers = [
            'User ID',
            'Username',
            'Телефон',
            'Подписка до',
            'Имя',
            'Возраст',
            'Пол',
            'Цель',
            'Уровень',
            'Дата регистрации',
            'Статус подписки'
        ]

        # Формируем данные для экспорта
        data = [headers]

        now = int(datetime.now().timestamp())

        for user in users:
            user_id, username, phone, sub_until, name, age, gender, goal, level, created_at = user

            # Форматируем дату подписки
            sub_date = datetime.fromtimestamp(sub_until).strftime('%d.%m.%Y %H:%M') if sub_until else 'Нет'

            # Статус подписки
            if sub_until and sub_until > now:
                status = '✅ Активна'
            else:
                status = '❌ Неактивна'

            # Дата регистрации
            reg_date = datetime.fromtimestamp(created_at).strftime('%d.%m.%Y') if created_at else ''

            row = [
                str(user_id),
                f"@{username}" if username else 'Нет',
                phone or 'Нет',
                sub_date,
                name or '',
                age or '',
                gender or '',
                goal or '',
                level or '',
                reg_date,
                status
            ]
            data.append(row)

        # Очищаем таблицу и записываем новые данные
        sheet.clear()
        sheet.update('A1', data, value_input_option='USER_ENTERED')

        # Форматируем заголовки (жирный текст)
        sheet.format('A1:K1', {
            'textFormat': {'bold': True},
            'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
        })

        return True, f"Экспортировано {len(users)} пользователей"

    except Exception as e:
        logging.error(f"Ошибка экспорта в Google Sheets: {e}")
        return False, f"Ошибка: {str(e)}"


async def export_referrals_to_sheet(spreadsheet_url: str = None, spreadsheet_id: str = None):
    """
    Экспортирует данные о рефералах в Google Таблицу

    Args:
        spreadsheet_url: URL таблицы
        spreadsheet_id: ID таблицы
    """
    try:
        client = get_google_sheets_client()
        if not client:
            return False, "Ошибка подключения к Google Sheets"

        # Открываем таблицу
        if spreadsheet_url:
            spreadsheet = client.open_by_url(spreadsheet_url)
        elif spreadsheet_id:
            spreadsheet = client.open_by_key(spreadsheet_id)
        else:
            return False, "Не указан URL или ID таблицы"

        # Создаем или получаем лист "Рефералы"
        try:
            sheet = spreadsheet.worksheet("Рефералы")
        except:
            sheet = spreadsheet.add_worksheet(title="Рефералы", rows=1000, cols=10)

        # Получаем данные из БД
        now = int(datetime.now().timestamp())
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT
                    r.id,
                    r.referrer_id,
                    u1.username as referrer_username,
                    u1.name as referrer_name,
                    r.referred_id,
                    u2.username as referred_username,
                    u2.name as referred_name,
                    u2.subscription_until,
                    r.created_at
                FROM referrals r
                LEFT JOIN users u1 ON r.referrer_id = u1.user_id
                LEFT JOIN users u2 ON r.referred_id = u2.user_id
                ORDER BY r.created_at DESC
            ''') as cursor:
                referrals = await cursor.fetchall()

            # Считаем сколько оплативших у каждого реферера
            async with db.execute('''
                SELECT r.referrer_id, COUNT(*) as paid_count
                FROM referrals r
                JOIN users u ON r.referred_id = u.user_id
                WHERE u.subscription_until IS NOT NULL AND u.subscription_until > ?
                GROUP BY r.referrer_id
            ''', (now,)) as cursor:
                paid_stats = {row[0]: row[1] for row in await cursor.fetchall()}

        # Заголовки
        headers = [
            'ID',
            'Пригласивший ID',
            'Пригласивший Username',
            'Пригласивший Имя',
            'Оплативших у него',
            'Приглашенный ID',
            'Приглашенный Username',
            'Приглашенный Имя',
            'Оплатил подписку',
            'Дата приглашения'
        ]

        data = [headers]

        for ref in referrals:
            ref_id, referrer_id, ref_user, ref_name, referred_id, referred_user, referred_name, sub_until, created = ref

            date = datetime.fromtimestamp(created).strftime('%d.%m.%Y %H:%M') if created else ''
            paid = '✅ Да' if (sub_until and sub_until > now) else '❌ Нет'
            paid_count = paid_stats.get(referrer_id, 0)

            row = [
                str(ref_id),
                str(referrer_id),
                f"@{ref_user}" if ref_user else 'Нет',
                ref_name or '',
                str(paid_count),
                str(referred_id),
                f"@{referred_user}" if referred_user else 'Нет',
                referred_name or '',
                paid,
                date
            ]
            data.append(row)

        # Записываем данные
        sheet.clear()
        sheet.update('A1', data, value_input_option='USER_ENTERED')

        # Форматируем заголовки
        sheet.format('A1:J1', {
            'textFormat': {'bold': True},
            'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
        })

        return True, f"Экспортировано {len(referrals)} рефералов"

    except Exception as e:
        logging.error(f"Ошибка экспорта рефералов в Google Sheets: {e}")
        return False, f"Ошибка: {str(e)}"


async def export_payments_to_sheet(spreadsheet_url: str = None, spreadsheet_id: str = None):
    """
    Экспортирует данные о платежах в Google Таблицу
    """
    try:
        client = get_google_sheets_client()
        if not client:
            return False, "Ошибка подключения к Google Sheets"

        if spreadsheet_url:
            spreadsheet = client.open_by_url(spreadsheet_url)
        elif spreadsheet_id:
            spreadsheet = client.open_by_key(spreadsheet_id)
        else:
            return False, "Не указан URL или ID таблицы"

        # Создаем или получаем лист "Платежи"
        try:
            sheet = spreadsheet.worksheet("Платежи")
        except:
            sheet = spreadsheet.add_worksheet(title="Платежи", rows=1000, cols=10)

        # Получаем данные из БД
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT
                    p.id,
                    p.user_id,
                    u.username,
                    u.name,
                    p.payment_id,
                    p.amount,
                    p.status,
                    p.created_at
                FROM payments p
                LEFT JOIN users u ON p.user_id = u.user_id
                ORDER BY p.created_at DESC
            ''') as cursor:
                payments = await cursor.fetchall()

        # Заголовки
        headers = [
            'ID',
            'User ID',
            'Username',
            'Имя',
            'Payment ID',
            'Сумма (₽)',
            'Статус',
            'Дата создания'
        ]

        data = [headers]

        for payment in payments:
            p_id, user_id, username, name, payment_id, amount, status, created = payment

            date = datetime.fromtimestamp(created).strftime('%d.%m.%Y %H:%M') if created else ''

            status_emoji = '✅' if status == 'succeeded' else '⏳' if status == 'pending' else '❌'

            row = [
                str(p_id),
                str(user_id),
                f"@{username}" if username else 'Нет',
                name or '',
                payment_id or '',
                str(amount),
                f"{status_emoji} {status}",
                date
            ]
            data.append(row)

        # Записываем данные
        sheet.clear()
        sheet.update('A1', data, value_input_option='USER_ENTERED')

        # Форматируем заголовки
        sheet.format('A1:H1', {
            'textFormat': {'bold': True},
            'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
        })

        return True, f"Экспортировано {len(payments)} платежей"

    except Exception as e:
        logging.error(f"Ошибка экспорта платежей в Google Sheets: {e}")
        return False, f"Ошибка: {str(e)}"


async def export_withdrawals_to_sheet(spreadsheet_url: str = None, spreadsheet_id: str = None):
    """
    Экспортирует данные о выводах в Google Таблицу
    """
    try:
        client = get_google_sheets_client()
        if not client:
            return False, "Ошибка подключения к Google Sheets"

        if spreadsheet_url:
            spreadsheet = client.open_by_url(spreadsheet_url)
        elif spreadsheet_id:
            spreadsheet = client.open_by_key(spreadsheet_id)
        else:
            return False, "Не указан URL или ID таблицы"

        try:
            sheet = spreadsheet.worksheet("Выводы")
        except:
            sheet = spreadsheet.add_worksheet(title="Выводы", rows=1000, cols=10)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('''
                SELECT
                    w.id,
                    w.user_id,
                    u.username,
                    u.name,
                    w.amount,
                    w.status,
                    w.created_at,
                    w.processed_at
                FROM withdrawals w
                LEFT JOIN users u ON w.user_id = u.user_id
                ORDER BY w.created_at DESC
            ''') as cursor:
                withdrawals = await cursor.fetchall()

        headers = [
            'ID',
            'User ID',
            'Username',
            'Имя',
            'Сумма (₽)',
            'Статус',
            'Дата создания',
            'Дата обработки'
        ]

        data = [headers]

        for w in withdrawals:
            w_id, user_id, username, name, amount, status, created, processed = w

            created_date = datetime.fromtimestamp(created).strftime('%d.%m.%Y %H:%M') if created else ''
            processed_date = datetime.fromtimestamp(processed).strftime('%d.%m.%Y %H:%M') if processed else ''

            status_emoji = '✅' if status == 'completed' else '⏳' if status == 'pending' else '❌'

            row = [
                str(w_id),
                str(user_id),
                f"@{username}" if username else 'Нет',
                name or '',
                str(amount),
                f"{status_emoji} {status}",
                created_date,
                processed_date
            ]
            data.append(row)

        sheet.clear()
        sheet.update('A1', data, value_input_option='USER_ENTERED')

        sheet.format('A1:H1', {
            'textFormat': {'bold': True},
            'backgroundColor': {'red': 0.9, 'green': 0.9, 'blue': 0.9}
        })

        return True, f"Экспортировано {len(withdrawals)} выводов"

    except Exception as e:
        logging.error(f"Ошибка экспорта выводов в Google Sheets: {e}")
        return False, f"Ошибка: {str(e)}"


async def export_all_data(spreadsheet_url: str = None, spreadsheet_id: str = None):
    """
    Экспортирует все данные в одну таблицу на разные листы
    """
    results = []

    success, msg = await export_users_to_sheet(spreadsheet_url, spreadsheet_id)
    results.append(f"Пользователи: {msg}")

    success, msg = await export_referrals_to_sheet(spreadsheet_url, spreadsheet_id)
    results.append(f"Рефералы: {msg}")

    success, msg = await export_payments_to_sheet(spreadsheet_url, spreadsheet_id)
    results.append(f"Платежи: {msg}")

    success, msg = await export_withdrawals_to_sheet(spreadsheet_url, spreadsheet_id)
    results.append(f"Выводы: {msg}")

    return True, "\n".join(results)
