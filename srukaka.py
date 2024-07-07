import os
import datetime
import logging
import aiocryptopay
import pydantic
import asyncio
import re
import openpyxl
from openpyxl.styles import PatternFill, Alignment, Font
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Text
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiocryptopay import AioCryptoPay, Networks
import signal
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(name)
ADMIN_IDS = [5150619792, 5150619792]  # Замените на реальные ID администраторов
# Логирование версий библиотек
logger.info(f"aiocryptopay version: {aiocryptopay.version}")
logger.info(f"pydantic version: {pydantic.version}")
TOKEN = '7266212298:AAHFblaG0mIPgNGVQcLDW3WawS0Qo7N7D9w'
CRYPTOBOT_TOKEN = '224616:AAhUpDVfMjwoLKjNQoZHjpWgIDuk5BknMsu'
CRYPTOBOT_USER_ID = 1189549622  # ID бота @CryptoBot
USER_FILES_DIR = '/Users/workacc/Documents/botforCryptoTeam/resourse/anoun'
os.makedirs(USER_FILES_DIR, exist_ok=True)

class UserState(StatesGroup):
    REGISTERED = State()
    WORKING_DAY_STARTED = State()
    WORKING_DAY_NOT_STARTED = State()
    AWAITING_PAYMENT = State()
    ADMIN_GRANTING_SUBSCRIPTION = State()
    ADMIN_GRANTING_FREE_SUBSCRIPTION = State()  # Новое состояние # Новое состояние

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)


crypto = AioCryptoPay(token=CRYPTOBOT_TOKEN, network=Networks.MAIN_NET)
logger.info(f"Crypto object initialized: {crypto}")

user_payments = {}
SUBSCRIPTIONS_FILE = 'subscriptions.json'
def account_button():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("Аккаунт"))
    return markup

@dp.message_handler(commands=['admin'], state='*')
async def admin_panel(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("У вас нет прав администратора.")
        return
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Добавить подписку", callback_data="add_subscription"))
    await message.answer("Панель администратора", reply_markup=markup)
    
def load_subscriptions():
    try:
        with open(SUBSCRIPTIONS_FILE, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return {}
@dp.callback_query_handler(lambda c: c.data == 'admin_view_subscriptions')
async def view_subscriptions(callback_query: types.CallbackQuery):
    if callback_query.from_user.id not in ADMIN_IDS:
        await bot.answer_callback_query(callback_query.id, "У вас нет доступа к этой функции.")
        return

    subscriptions_text = "Активные подписки:\n\n"
    for user_id, expiration_date in user_subscriptions.items():
        subscriptions_text += f"Пользователь ID: {user_id}, Подписка до: {expiration_date.strftime('%d.%m.%Y')}\n"
    
    await bot.send_message(callback_query.from_user.id, subscriptions_text)
    await bot.answer_callback_query(callback_query.id)

@dp.callback_query_handler(lambda c: c.data == 'admin_grant_subscription')
async def grant_subscription_start(callback_query: types.CallbackQuery):
    if callback_query.from_user.id not in ADMIN_IDS:
        await bot.answer_callback_query(callback_query.id, "У вас нет доступа к этой функции.")
        return

    await bot.send_message(callback_query.from_user.id, "Введите ID пользователя и количество дней подписки в формате: ID дни")
    await bot.answer_callback_query(callback_query.id)
    await UserState.ADMIN_GRANTING_SUBSCRIPTION.set()
user_subscriptions = load_subscriptions()
@dp.message_handler(state=UserState.ADMIN_GRANTING_SUBSCRIPTION)
async def grant_subscription(message: types.Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        await message.reply("У вас нет доступа к этой функции.")
        return

    try:
        user_id, days = map(int, message.text.split())
        expiration_date = datetime.datetime.now() + datetime.timedelta(days=days)
        user_subscriptions[user_id] = expiration_date
        save_subscriptions()
        await message.reply(f"Подписка выдана пользователю {user_id} до {expiration_date.strftime('%d.%м.%Y')}")
    except ValueError:
        await message.reply("Неверный формат. Используйте: ID дни")
    
    await state.finish()

async def check_subscriptions():
    current_time = datetime.datetime.now()
    for user_id, expiration_date in list(user_subscriptions.items()):
        if expiration_date < current_time:
            await bot.send_message(user_id, "Ваша подписка истекла. Пожалуйста, обновите подписку для продолжения использования бота.")
            del user_subscriptions[user_id]
            save_subscriptions()
        elif (expiration_date - current_time).days <= 3:
            await bot.send_message(user_id, f"Ваша подписка истекает через {(expiration_date - current_time).days} дней. Не забудьте продлить ее.")
        elif (expiration_date - current_time).days == 0:
            await bot.send_message(user_id, "Ваша подписка истекает сегодня. Пожалуйста, продлите ее для дальнейшего использования бота.")
            
def check_active_subscription(func):
    async def wrapper(message: types.Message, *args, **kwargs):
        user_id = message.from_user.id
        if user_id in ADMIN_IDS or check_subscription(user_id):
            return await func(message, *args, **kwargs)
        else:
            await show_subscription_options(message)
    return wrapper

def check_subscription(user_id):
    return user_id in user_subscriptions and user_subscriptions[user_id] > datetime.datetime.now()

async def create_invoice(amount, currency):
    try:
        logger.info(f"Attempting to create invoice: amount={amount}, currency={currency}")
        invoice = await crypto.create_invoice(
            asset=currency,
            amount=amount,
            payload=f"subscription:{amount}"
        )
        logger.info(f"Invoice created: {invoice}")
        result = invoice.model_dump() if hasattr(invoice, 'model_dump') else invoice.dict()
        logger.info(f"Invoice data: {result}")
        return result
    except Exception as e:
        logger.error(f"Error creating invoice: {str(e)}", exc_info=True)
        return None

async def check_invoice_status(invoice_id):
    try:
        invoices = await crypto.get_invoices(invoice_ids=[invoice_id])
        if invoices and len(invoices) > 0:
            return invoices[0].status
        else:
            logger.error(f"No invoice found with id: {invoice_id}")
            return None
    except Exception as e:
        logger.error(f"Error checking invoice status: {str(e)}", exc_info=True)
        return None

async def check_crypto_connection():
    try:
        me = await crypto.get_me()
        logger.info(f"Connected to Crypto Bot: {me}")
    except Exception as e:
        logger.error(f"Failed to connect to Crypto Bot: {str(e)}", exc_info=True)

async def check_subscriptions():
    current_time = datetime.datetime.now()
    for user_id, expiration_date in user_subscriptions.items():
        if expiration_date < current_time:
            await bot.send_message(user_id, "Ваша подписка истекла. Пожалуйста, обновите подписку для продолжения использования бота.")
            del user_subscriptions[user_id]
        elif (expiration_date - current_time).days <= 3:
            await bot.send_message(user_id, f"Ваша подписка истекает через {(expiration_date - current_time).days} дней. Не забудьте продлить ее.")

async def schedule_subscription_check(dp: Dispatcher):
    while True:
        await check_subscriptions()
        await asyncio.sleep(86400)  # 24 часа
@dp.message_handler(commands=['start'], state='*')
async def start(message: types.Message, state: FSMContext):
    user_id = str(message.from_user.id)
    if user_id in user_subscriptions:
        await message.answer("Вы уже можете приступать к работе, подробнее о Вашей подписке можете узнать в разделе 'Аккаунт'.", reply_markup=account_button())
    else:
        # Your existing code for handling new users
        pass    
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id in ADMIN_IDS:
        await admin_panel(message)
    
    if user_id in user_subscriptions:
        await message.answer("Вы уже можете приступать к работе, подробнее о Вашей подписке можете узнать в разделе 'Аккаунт'.", reply_markup=account_button())
    else:
        await show_subscription_options(message)

async def show_subscription_options(message: types.Message):
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("3 дня - 2 USDT", callback_data="sub:3:days:2"),
                 InlineKeyboardButton("5 дней - 3 USDT", callback_data="sub:5:days:3"),
                 InlineKeyboardButton("7 дней - 4 USDT", callback_data="sub:7:days:4"))
    await message.reply("Выберите план подписки:", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data.startswith('pay:'))
async def process_payment(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    parts = callback_query.data.split(':')
    
    logger.info(f"Callback data: {callback_query.data}")
    logger.info(f"Parsed parts: {parts}")
    
    if len(parts) != 5:
        await bot.answer_callback_query(callback_query.id, "Неверные данные для оплаты.")
        return
    
    try:
        subscription_period, unit, amount, currency = parts[1], parts[2], parts[3], parts[4]
        amount = float(amount)
    except ValueError:
        await bot.answer_callback_query(callback_query.id, "Неверные данные для оплаты.")
        return
    
    logger.info(f"Creating invoice with amount: {amount} and currency: {currency}")
    invoice = await create_invoice(amount, currency)
    if invoice:
        user_payments[user_id] = {
            "invoice_id": invoice['invoice_id'],
            "amount": amount,
            "currency": currency,
            "subscription_period": subscription_period,
            "unit": unit
        }
        await bot.send_message(user_id, f"Счет на оплату: {invoice['pay_url']}")
        await UserState.AWAITING_PAYMENT.set()
    else:
        await bot.send_message(user_id, "Ошибка при создании счета. Попробуйте еще раз позже.")
        
@dp.callback_query_handler(lambda c: c.data.startswith('sub:'))
async def process_subscription(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    parts = callback_query.data.split(':')
    if len(parts) != 4:
        await bot.answer_callback_query(callback_query.id, "Неверные данные для подписки.")
        return
    
    days, _, amount = parts[1], parts[2], parts[3]
    
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("Оплатить USDT", callback_data=f"pay:{days}:days:{amount}:USDT"),
        InlineKeyboardButton("Оплатить BTC", callback_data=f"pay:{days}:days:{amount}:BTC")
    )
    await bot.send_message(user_id, f"Вы выбрали подписку на {days} дней за {amount} USDT. Выберите валюту для оплаты:", reply_markup=keyboard)
    await bot.answer_callback_query(callback_query.id)

def save_subscriptions(subscriptions):
    with open(SUBSCRIPTIONS_FILE, 'w') as file:
        json.dump(subscriptions, file)


async def on_startup(_):
    await check_crypto_connection()
    asyncio.create_task(schedule_subscription_check(dp))
    load_subscriptions()

async def on_shutdown(dp):
    save_subscriptions()

dp.loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(on_shutdown(dp)))
dp.loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.create_task(on_shutdown(dp)))

if __name__ == "__main__":
    from aiogram import executor
    executor.start_polling(dp, on_startup=on_startup)
