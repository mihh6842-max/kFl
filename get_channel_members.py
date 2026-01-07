import asyncio
from aiogram import Bot
from dotenv import dotenv_values
from crypto_helper import decrypt_token

# Загружаем конфиг
env = dotenv_values('.env')
encrypted_token = env.get('BOT_TOKEN_ENCRYPTED')
if encrypted_token:
    BOT_TOKEN = decrypt_token(encrypted_token)
else:
    BOT_TOKEN = env.get('BOT_TOKEN', "")

CHANNEL_ID = -1002284489725

async def get_members():
    bot = Bot(token=BOT_TOKEN)

    try:
        # Получаем информацию о канале
        chat = await bot.get_chat(CHANNEL_ID)
        print(f"=== Информация о канале ===")
        print(f"Название: {chat.title}")
        print(f"Тип: {chat.type}")
        print(f"ID: {chat.id}")

        # Получаем количество участников
        count = await bot.get_chat_member_count(CHANNEL_ID)
        print(f"\nВсего участников: {count}")

        # Получаем администраторов
        print(f"\n=== Администраторы канала ===")
        admins = await bot.get_chat_administrators(CHANNEL_ID)
        for admin in admins:
            user = admin.user
            status = admin.status
            username = f"@{user.username}" if user.username else "Нет username"
            print(f"User ID: {user.id}")
            print(f"Имя: {user.first_name} {user.last_name or ''}")
            print(f"Username: {username}")
            print(f"Статус: {status}")
            print("---")

        print(f"\n❗ Telegram Bot API не позволяет получить полный список участников канала/группы.")
        print(f"Можно только:\n- Количество участников: {count}")
        print(f"- Список администраторов (показано выше)")
        print(f"\nДля получения полного списка нужно использовать Telegram Client API (не Bot API)")

    except Exception as e:
        print(f"Ошибка: {e}")
    finally:
        await bot.session.close()

asyncio.run(get_members())
