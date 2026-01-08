"""
Webhook сервер для приёма уведомлений от Робокассы
Запускается отдельно или вместе с ботом
"""
from aiohttp import web
import aiosqlite
import logging
import sys
import os

# Добавляем путь к боту для импорта
sys.path.insert(0, os.path.dirname(__file__))

import robokassa
from bot import process_successful_payment, DB_PATH, bot

logging.basicConfig(level=logging.INFO)

async def robokassa_result(request):
    """
    ResultURL - обработчик уведомления об оплате от Робокассы
    Робокасса отправляет POST запрос с параметрами оплаты
    """
    try:
        # Получаем данные от Робокассы
        data = await request.post()

        out_sum = float(data.get('OutSum', 0))
        inv_id = int(data.get('InvId', 0))
        signature = data.get('SignatureValue', '')

        # Собираем пользовательские параметры
        shp_params = {k: v for k, v in data.items() if k.startswith('Shp_')}
        user_id = int(shp_params.get('Shp_UserId', 0)) if 'Shp_UserId' in shp_params else None

        logging.info(f"[ROBOKASSA WEBHOOK] Получено уведомление: InvId={inv_id}, OutSum={out_sum}, UserId={user_id}")

        # Проверяем подпись
        if not robokassa.check_signature_result(out_sum, inv_id, signature, shp_params):
            logging.error(f"[ROBOKASSA WEBHOOK] Неверная подпись для InvId={inv_id}")
            return web.Response(text="BAD SIGN", status=400)

        # Проверяем что платёж ещё не обработан
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT status, user_id FROM payments WHERE payment_id = ?',
                (str(inv_id),)
            ) as cursor:
                payment_row = await cursor.fetchone()

        if not payment_row:
            logging.error(f"[ROBOKASSA WEBHOOK] Платёж {inv_id} не найден в БД")
            return web.Response(text="PAYMENT NOT FOUND", status=404)

        status, db_user_id = payment_row

        # Используем user_id из БД если не передан в Shp_
        if not user_id:
            user_id = db_user_id

        if status == 'succeeded':
            logging.info(f"[ROBOKASSA WEBHOOK] Платёж {inv_id} уже обработан")
            return web.Response(text=f"OK{inv_id}")

        # Обрабатываем успешную оплату
        await process_successful_payment(inv_id, user_id, out_sum)

        logging.info(f"[ROBOKASSA WEBHOOK] Платёж {inv_id} успешно обработан")

        # Возвращаем OK согласно документации Робокассы
        return web.Response(text=f"OK{inv_id}")

    except Exception as e:
        logging.error(f"[ROBOKASSA WEBHOOK] Ошибка обработки: {e}")
        return web.Response(text="ERROR", status=500)


async def robokassa_success(request):
    """
    SuccessURL - страница успешной оплаты (показывается пользователю)
    """
    try:
        data = await request.get()
        inv_id = data.get('InvId', 'unknown')

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>Оплата прошла успешно</title>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    text-align: center;
                    padding: 50px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                }}
                .container {{
                    background: white;
                    color: #333;
                    padding: 40px;
                    border-radius: 10px;
                    max-width: 500px;
                    margin: 0 auto;
                    box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                }}
                h1 {{ color: #4CAF50; }}
                .icon {{ font-size: 80px; }}
                .button {{
                    background: #667eea;
                    color: white;
                    padding: 15px 30px;
                    text-decoration: none;
                    border-radius: 5px;
                    display: inline-block;
                    margin-top: 20px;
                    font-weight: bold;
                }}
                .button:hover {{ background: #5568d3; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="icon">✅</div>
                <h1>Оплата прошла успешно!</h1>
                <p>Номер счета: <b>{inv_id}</b></p>
                <p>Ваша подписка активирована на 30 дней.</p>
                <p>Проверьте бота - вам отправлено подтверждение!</p>
                <a href="https://t.me/KLSClub_bot" class="button">Вернуться в бота</a>
            </div>
        </body>
        </html>
        """

        return web.Response(text=html, content_type='text/html')

    except Exception as e:
        logging.error(f"[ROBOKASSA SUCCESS] Ошибка: {e}")
        return web.Response(text="Ошибка", status=500)


async def robokassa_fail(request):
    """
    FailURL - страница неуспешной оплаты
    """
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Оплата не прошла</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {
                font-family: Arial, sans-serif;
                text-align: center;
                padding: 50px;
                background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                color: white;
            }
            .container {
                background: white;
                color: #333;
                padding: 40px;
                border-radius: 10px;
                max-width: 500px;
                margin: 0 auto;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            }
            h1 { color: #f5576c; }
            .icon { font-size: 80px; }
            .button {
                background: #f5576c;
                color: white;
                padding: 15px 30px;
                text-decoration: none;
                border-radius: 5px;
                display: inline-block;
                margin-top: 20px;
                font-weight: bold;
            }
            .button:hover { background: #d94358; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">❌</div>
            <h1>Оплата не прошла</h1>
            <p>Что-то пошло не так при оплате.</p>
            <p>Попробуйте ещё раз или свяжитесь с поддержкой.</p>
            <a href="https://t.me/KLSClub_bot" class="button">Вернуться в бота</a>
        </div>
    </body>
    </html>
    """

    return web.Response(text=html, content_type='text/html')


async def health_check(request):
    """Проверка работоспособности сервера"""
    return web.Response(text="OK")


def create_app():
    """Создаёт приложение aiohttp"""
    app = web.Application()

    # Роуты для Робокассы
    app.router.add_post('/robokassa/result', robokassa_result)
    app.router.add_get('/robokassa/success', robokassa_success)
    app.router.add_get('/robokassa/fail', robokassa_fail)
    app.router.add_get('/health', health_check)

    return app


if __name__ == '__main__':
    app = create_app()

    # Запуск на порту 8080
    # В Робокассе нужно указать:
    # ResultURL: http://ваш_домен:8080/robokassa/result
    # SuccessURL: http://ваш_домен:8080/robokassa/success
    # FailURL: http://ваш_домен:8080/robokassa/fail

    print("="*60)
    print("Webhook сервер Робокасса запущен")
    print("="*60)
    print("Настройки в личном кабинете Робокассы:")
    print("ResultURL:  http://ваш_домен:8080/robokassa/result")
    print("SuccessURL: http://ваш_домен:8080/robokassa/success")
    print("FailURL:    http://ваш_домен:8080/robokassa/fail")
    print("="*60)

    web.run_app(app, host='0.0.0.0', port=8080)
