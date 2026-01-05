"""
Утилита для шифрования/расшифровки токена бота (без внешних библиотек)
"""
import base64

# Секретный ключ (замените на свой!)
SECRET_KEY = "KafedraLyubitelskogo2025SecretKey"

def encrypt_token(token: str) -> str:
    """Шифрует токен простым XOR + base64"""
    key_bytes = SECRET_KEY.encode()
    token_bytes = token.encode()

    # XOR шифрование
    encrypted = bytearray()
    for i, byte in enumerate(token_bytes):
        encrypted.append(byte ^ key_bytes[i % len(key_bytes)])

    # Конвертируем в base64 для читаемости
    return base64.b64encode(bytes(encrypted)).decode()

def decrypt_token(encrypted_token: str) -> str:
    """Расшифровывает токен"""
    key_bytes = SECRET_KEY.encode()

    # Декодируем из base64
    encrypted_bytes = base64.b64decode(encrypted_token.encode())

    # XOR расшифровка (XOR обратим)
    decrypted = bytearray()
    for i, byte in enumerate(encrypted_bytes):
        decrypted.append(byte ^ key_bytes[i % len(key_bytes)])

    return bytes(decrypted).decode()

if __name__ == "__main__":
    # Тестирование
    original = "8576168614:AAEfCUkIo347_6uN9aXEqEa_VzAocdeRCzk"
    encrypted = encrypt_token(original)
    print(f"Encrypted: {encrypted}")
    print(f"Decrypted: {decrypt_token(encrypted)}")
