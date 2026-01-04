import sqlite3

def delete_users(db_path, user_ids):
    """
    Удаляет пользователей из всех таблиц базы данных
    
    Args:
        db_path: путь к файлу базы данных
        user_ids: список ID пользователей для удаления
    """
    try:
        # Подключение к базе данных
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        for user_id in user_ids:
            print(f"\nУдаление пользователя {user_id}...")
            
            # Удаление из таблицы users
            cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            print(f"  - Удалено из users: {cursor.rowcount} записей")
            
            # Удаление из таблицы broadcast_history
            cursor.execute("DELETE FROM broadcast_history WHERE user_id = ?", (user_id,))
            print(f"  - Удалено из broadcast_history: {cursor.rowcount} записей")
            
            # Удаление из таблицы message_history
            cursor.execute("DELETE FROM message_history WHERE user_id = ?", (user_id,))
            print(f"  - Удалено из message_history: {cursor.rowcount} записей")
            
            # Удаление из таблицы payments
            cursor.execute("DELETE FROM payments WHERE user_id = ?", (user_id,))
            print(f"  - Удалено из payments: {cursor.rowcount} записей")
            
            # Удаление из таблицы referrals (как реферер)
            cursor.execute("DELETE FROM referrals WHERE referrer_id = ?", (user_id,))
            print(f"  - Удалено из referrals (referrer): {cursor.rowcount} записей")
            
            # Удаление из таблицы referrals (как приглашенный)
            cursor.execute("DELETE FROM referrals WHERE referred_id = ?", (user_id,))
            print(f"  - Удалено из referrals (referred): {cursor.rowcount} записей")
        
        # Сохранение изменений
        conn.commit()
        print("\n✅ Все изменения успешно сохранены!")
        
    except sqlite3.Error as e:
        print(f"\n❌ Ошибка при работе с базой данных: {e}")
        conn.rollback()
    
    finally:
        if conn:
            conn.close()
            print("Соединение с базой данных закрыто.")

if __name__ == "__main__":
    # Путь к файлу базы данных
    DB_PATH = "bot.db"
    
    # ID пользователей для удаления
    USER_IDS = [870227242, 7338817463]
    
    print("Начало удаления пользователей из базы данных...")
    print(f"База данных: {DB_PATH}")
    print(f"Пользователи для удаления: {USER_IDS}")
    
    delete_users(DB_PATH, USER_IDS)