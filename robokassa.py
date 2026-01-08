"""
Модуль для работы с Робокасса
Документация: https://docs.robokassa.ru/
"""
import hashlib
from urllib.parse import urlencode

# Данные магазина
MERCHANT_LOGIN = "KLS_club"
PASSWORD_1 = "M1UeOkDl42T4KZmQ0BZz"  # Пароль #1 для генерации подписи
PASSWORD_2 = "pR4FHN52OM4PwpbTr4Fj"  # Пароль #2 для проверки результата

# URL Робокассы
ROBOKASSA_URL = "https://auth.robokassa.ru/Merchant/Index.aspx"
TEST_MODE = False  # Переключение между боевым и тестовым режимом


def generate_payment_link(
    out_sum: float,
    inv_id: int,
    description: str,
    user_email: str = None,
    user_id: int = None
) -> str:
    """
    Генерирует ссылку на оплату в Робокассе

    Args:
        out_sum: сумма заказа
        inv_id: номер счета (уникальный ID платежа в вашей системе)
        description: описание покупки
        user_email: email пользователя (опционально)
        user_id: ID пользователя для передачи в callback (опционально)

    Returns:
        str: URL для перенаправления на оплату
    """
    # Параметры для подписи
    params = {
        'MerchantLogin': MERCHANT_LOGIN,
        'OutSum': f"{out_sum:.2f}",
        'InvId': str(inv_id),
        'Description': description,
        'Encoding': 'utf-8'
    }

    # Добавляем опциональные параметры
    if user_email:
        params['Email'] = user_email

    # Пользовательские параметры (начинаются с Shp_)
    if user_id:
        params['Shp_UserId'] = str(user_id)

    if TEST_MODE:
        params['IsTest'] = '1'

    # Генерируем подпись
    # Формат: MerchantLogin:OutSum:InvId:Password1[:Shp_param1=value1:Shp_param2=value2...]
    signature_parts = [
        MERCHANT_LOGIN,
        f"{out_sum:.2f}",
        str(inv_id),
        PASSWORD_1
    ]

    # Добавляем пользовательские параметры в подпись (в алфавитном порядке)
    shp_params = {k: v for k, v in params.items() if k.startswith('Shp_')}
    for key in sorted(shp_params.keys()):
        signature_parts.append(f"{key}={shp_params[key]}")

    signature_string = ':'.join(signature_parts)
    signature = hashlib.md5(signature_string.encode('utf-8')).hexdigest()

    params['SignatureValue'] = signature

    # Формируем URL
    query_string = urlencode(params)
    payment_url = f"{ROBOKASSA_URL}?{query_string}"

    return payment_url


def check_signature_result(
    out_sum: float,
    inv_id: int,
    signature_value: str,
    shp_params: dict = None
) -> bool:
    """
    Проверяет подпись от Робокассы (ResultURL)

    Args:
        out_sum: сумма заказа
        inv_id: номер счета
        signature_value: подпись от Робокассы
        shp_params: пользовательские параметры (dict с ключами Shp_*)

    Returns:
        bool: True если подпись верна
    """
    # Формат подписи для ResultURL: OutSum:InvId:Password2[:Shp_param1=value1...]
    signature_parts = [
        f"{out_sum:.2f}",
        str(inv_id),
        PASSWORD_2
    ]

    # Добавляем пользовательские параметры в подпись (в алфавитном порядке)
    if shp_params:
        for key in sorted(shp_params.keys()):
            signature_parts.append(f"{key}={shp_params[key]}")

    signature_string = ':'.join(signature_parts)
    expected_signature = hashlib.md5(signature_string.encode('utf-8')).hexdigest()

    return expected_signature.upper() == signature_value.upper()


def check_signature_success(
    out_sum: float,
    inv_id: int,
    signature_value: str,
    shp_params: dict = None
) -> bool:
    """
    Проверяет подпись от Робокассы (SuccessURL)
    Использует тот же алгоритм что и ResultURL

    Args:
        out_sum: сумма заказа
        inv_id: номер счета
        signature_value: подпись от Робокассы
        shp_params: пользовательские параметры

    Returns:
        bool: True если подпись верна
    """
    return check_signature_result(out_sum, inv_id, signature_value, shp_params)


# Пример использования
if __name__ == "__main__":
    # Создание ссылки на оплату
    payment_url = generate_payment_link(
        out_sum=2222.0,
        inv_id=12345,
        description="Подписка на 1 месяц - Кафедра любительского спорта",
        user_email="user@example.com",
        user_id=123456789
    )

    print("Ссылка на оплату:")
    print(payment_url)
    print()

    # Проверка подписи (пример)
    # Эти данные придут от Робокассы
    test_signature = "ABC123DEF456"
    is_valid = check_signature_result(
        out_sum=2222.0,
        inv_id=12345,
        signature_value=test_signature,
        shp_params={'Shp_UserId': '123456789'}
    )

    print(f"Подпись валидна: {is_valid}")
