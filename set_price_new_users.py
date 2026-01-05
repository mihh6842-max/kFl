import asyncio
import aiosqlite
from datetime import datetime, timedelta

DB_PATH = 'data/bot.db'

# Новые пользователи со специальной ценой 1111₽
new_users = [670030071, 342534630, 463485998]

async def set_special_price():
    grace_until = int((datetime.now() + timedelta(days=365)).timestamp())

    async with aiosqlite.connect(DB_PATH) as db:
        for user_id in new_users:
            await db.execute(
                'UPDATE users SET special_price = ?, grace_period_until = ? WHERE user_id = ?',
                (1111, grace_until, user_id)
            )
            print(f"User {user_id}: price 1111 set")

        await db.commit()

    print(f"\nDone! Updated {len(new_users)} users")

if __name__ == '__main__':
    asyncio.run(set_special_price())
