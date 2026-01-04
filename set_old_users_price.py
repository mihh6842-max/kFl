"""
Скрипт для установки special_price = 1111 для старых пользователей кафедры
"""
import asyncio
import aiosqlite
from datetime import datetime, timedelta

DB_PATH = 'data/bot.db'

# Список старых пользователей кафедры
OLD_USERS = [
    1088957059, 5121438255, 493400017, 627588247, 5078535686, 1297292247,
    1087396221, 5174280432, 2111901900, 605427511, 6252631670, 445793647,
    1099010235, 699959816, 191973444, 427581781, 6963942235, 842082772,
    1081930069, 1850971618, 1483234621, 1117884372, 6952844021, 1306826603,
    1930355817, 2051726424, 2119328146, 808940816, 7160440665, 1458271181,
    5255317083, 5276077737, 913651711, 2047126777, 6903447413, 511826502,
    5526304010, 7147560663, 995013954, 274422255, 479304338, 576042727,
    876656610, 5252417492, 1074060803, 1621597984, 6470776552, 7106080754,
    1049642785, 6907129508, 6589874868, 638259241, 5234815755, 5131499734,
    211966459
]

SPECIAL_PRICE = 1111  # Старая цена для участников

async def set_old_users_price():
    now = int(datetime.now().timestamp())
    grace_7_days = int((datetime.now() + timedelta(days=7)).timestamp())

    async with aiosqlite.connect(DB_PATH) as db:
        updated = 0
        for user_id in OLD_USERS:
            # Проверяем есть ли пользователь
            async with db.execute('SELECT subscription_until FROM users WHERE user_id = ?', (user_id,)) as cursor:
                row = await cursor.fetchone()

            if row:
                sub_until = row[0] or 0
                # grace_period = подписка + 7 дней или сейчас + 7 дней (если подписка истекла)
                if sub_until > now:
                    grace = sub_until + 7 * 24 * 3600  # +7 дней от окончания подписки
                else:
                    grace = grace_7_days  # +7 дней от сейчас

                await db.execute(
                    'UPDATE users SET special_price = ?, grace_period_until = ? WHERE user_id = ?',
                    (SPECIAL_PRICE, grace, user_id)
                )
                updated += 1
                print(f"✅ User {user_id}: special_price = {SPECIAL_PRICE}")
            else:
                print(f"⚠️ User {user_id} не найден в БД")

        await db.commit()
        print(f"\n🎉 Обновлено {updated} пользователей")

if __name__ == '__main__':
    asyncio.run(set_old_users_price())
