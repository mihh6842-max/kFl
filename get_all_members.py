"""
Скрипт для получения всех участников канала через Telegram Client API

Требуется:
1. API_ID и API_HASH с https://my.telegram.org/apps
2. Номер телефона для авторизации

Установка: pip install telethon
"""

from telethon import TelegramClient
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
import asyncio

# ===== НАСТРОЙКИ =====
# Получите эти данные на https://my.telegram.org/apps
API_ID = None  # Введите ваш API_ID
API_HASH = None  # Введите ваш API_HASH

CHANNEL_ID = -1002284489725  # ID канала КЛС
SESSION_NAME = 'get_members_session'

async def get_all_members():
    # Проверяем наличие API данных
    if not API_ID or not API_HASH:
        print("=" * 60)
        print("ИНСТРУКЦИЯ:")
        print("=" * 60)
        print("1. Откройте https://my.telegram.org/apps")
        print("2. Войдите с вашим номером телефона")
        print("3. Создайте приложение (если еще не создано)")
        print("4. Скопируйте API_ID и API_HASH")
        print("5. Вставьте их в этот файл (строки 16-17)")
        print("=" * 60)
        return

    # Создаем клиент
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)

    try:
        await client.start()
        print("✅ Авторизация успешна!")

        # Получаем информацию о канале
        entity = await client.get_entity(CHANNEL_ID)
        print(f"\n📊 Канал: {entity.title}")
        print(f"ID: {entity.id}")

        # Получаем всех участников
        print("\n⏳ Загружаю участников...")

        all_participants = []
        offset = 0
        limit = 100

        while True:
            participants = await client(GetParticipantsRequest(
                channel=entity,
                filter=ChannelParticipantsSearch(''),
                offset=offset,
                limit=limit,
                hash=0
            ))

            if not participants.users:
                break

            all_participants.extend(participants.users)
            offset += len(participants.users)
            print(f"Загружено: {len(all_participants)} участников...")

            if len(participants.users) < limit:
                break

        print(f"\n✅ Всего участников: {len(all_participants)}\n")
        print("=" * 60)
        print("СПИСОК УЧАСТНИКОВ (User ID)")
        print("=" * 60)

        # Выводим список ID
        for user in all_participants:
            name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            username = f"@{user.username}" if user.username else "Нет username"
            bot_mark = " [BOT]" if user.bot else ""

            print(f"User id: {user.id}")
            print(f"Имя: {name or 'Без имени'}")
            print(f"Username: {username}{bot_mark}")
            print()

        # Сохраняем только ID в файл
        with open('channel_members_ids.txt', 'w', encoding='utf-8') as f:
            f.write("# Список User ID участников канала\n")
            f.write(f"# Канал: {entity.title}\n")
            f.write(f"# Всего: {len(all_participants)} участников\n\n")
            for user in all_participants:
                if not user.bot:  # Исключаем ботов
                    f.write(f"{user.id}\n")

        print("=" * 60)
        print(f"✅ Список ID сохранен в: channel_members_ids.txt")
        print(f"📝 Можно скопировать и вставить в админку для установки цены 1111₽")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        await client.disconnect()

if __name__ == '__main__':
    asyncio.run(get_all_members())
