import aiosqlite
import asyncio
from datetime import datetime

async def check():
    db = await aiosqlite.connect('data/bot.db')

    # Показываем всех пользователей
    cursor = await db.execute('SELECT user_id, name, username, special_price, grace_period_until FROM users')
    rows = await cursor.fetchall()

    print(f'=== Всего пользователей: {len(rows)} ===\n')

    # Сначала пользователи с ценой 1111
    users_1111 = [r for r in rows if r[3] == 1111]
    if users_1111:
        print('--- С ценой 1111 ---')
        for r in users_1111:
            user_id = r[0]
            name = r[1] or r[2] or 'Без имени'
            grace = r[4]
            grace_str = datetime.fromtimestamp(grace).strftime('%d.%m.%Y') if grace else 'Не установлен'
            print(f'User id: {user_id}')
            print(f'Имя: {name}')
            print(f'Льгота до: {grace_str}')
            print()
    else:
        print('--- С ценой 1111: нет пользователей ---\n')

    # Потом все остальные
    others = [r for r in rows if r[3] != 1111]
    if others:
        print('--- Остальные пользователи ---')
        for r in others:
            user_id = r[0]
            name = r[1] or r[2] or 'Без имени'
            price = r[3] or 'Не установлена'
            print(f'User id: {user_id}, Имя: {name}, Цена: {price}')

    await db.close()

asyncio.run(check())
