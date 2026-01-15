#!/usr/bin/env python3
"""
Reminder Pro Bot - Умная напоминалка с поддержкой timezone
НОВАЯ ЛОГИКА: время → текст → повторение
"""

import os
import psutil
import platform

import asyncio
import logging
import sys
from datetime import datetime, timedelta
from typing import Optional, Tuple

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

from config import Config
from database import Database
from utils.time_parser import TimeParser
from keyboards.main_menu import get_main_keyboard, get_cancel_keyboard

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(Config.LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Инициализация
Config.validate()
bot = Bot(token=Config.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler(timezone="UTC")

# Инициализация компонентов
db = Database(Config.DB_NAME)
time_parser = TimeParser()

# ===== АДМИН-УТИЛИТЫ =====

def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь админом"""
    logger.debug(f"🔍 Проверка прав админа для user_id: {user_id}")
    logger.debug(f"   Config.ADMINS: {Config.ADMINS}")
    
    # Проверяем в Config.ADMINS
    if user_id in Config.ADMINS:
        logger.info(f"✅ Пользователь {user_id} найден в Config.ADMINS")
        # Добавляем в базу если еще нет
        if not db.is_admin(user_id):
            user = db.get_user(user_id)
            username = user.get('username') if user else None
            db.add_admin(user_id, username)
            logger.info(f"✅ Пользователь {user_id} добавлен в таблицу admins")
        return True
    
    # Проверяем в базе данных
    is_admin_in_db = db.is_admin(user_id)
    logger.debug(f"   db.is_admin({user_id}): {is_admin_in_db}")
    
    return is_admin_in_db

async def admin_only(handler):
    """Декоратор для проверки прав админа"""
    async def wrapper(message: types.Message, *args, **kwargs):
        user_id = message.from_user.id
        logger.debug(f"🔍 Проверка прав админа через декоратор для user_id: {user_id}")
        
        if not is_admin(user_id):
            logger.warning(f"⛔ Пользователь {user_id} не админ, пытался использовать админ-команду: {message.text}")
            await message.answer("⛔ У вас нет прав администратора.")
            return
        logger.debug(f"✅ Пользователь {user_id} прошел проверку админских прав")
        return await handler(message, *args, **kwargs)
    return wrapper

# ===== НОВЫЕ СОСТОЯНИЯ FSM (время → текст → повторение) =====
class ReminderState(StatesGroup):
    waiting_for_time = State()    # Ждем время напоминания
    waiting_for_text = State()    # Ждем текст напоминания  
    waiting_for_repeat = State()  # Ждем тип повторения

class SettingsState(StatesGroup):
    waiting_for_language = State()
    waiting_for_timezone = State()

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

def format_local_time(dt: datetime, timezone: str, language: str) -> str:
    """Форматировать время для пользователя в его часовом поясе"""
    try:
        # Если время naive (без часового пояса), считаем что это UTC
        if dt.tzinfo is None:
            dt = pytz.UTC.localize(dt)
        
        # Конвертируем в часовой пояс пользователя
        user_tz = pytz.timezone(timezone)
        local_dt = dt.astimezone(user_tz)
        
        if language == 'ru':
            # Русский формат: 15 января 2024, 14:30
            months_ru = [
                'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
                'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
            ]
            month_name = months_ru[local_dt.month - 1]
            return f"{local_dt.day} {month_name} {local_dt.year}, {local_dt.strftime('%H:%M')}"
        else:
            # Английский формат: January 15, 2024, 2:30 PM
            return local_dt.strftime("%B %d, %Y, %I:%M %p")
    except Exception as e:
        logger.error(f"Error formatting time: {e}")
        # Фолбэк
        return dt.strftime("%Y-%m-%d %H:%M")

async def send_reminder_notification(reminder: dict):
    """Отправить уведомление о напоминании"""
    try:
        user_timezone = reminder['timezone']
        user_lang = reminder.get('language_code', 'ru')
        
        # Логируем информацию о напоминании
        logger.info(f"Отправка напоминания {reminder['id']} пользователю {reminder['user_id']}")
        logger.info(f"  Текст: {reminder['text']}")
        logger.info(f"  Часовой пояс пользователя: {user_timezone}")
        logger.info(f"  Тип повторения: {reminder.get('repeat_type', 'once')}")
        logger.info(f"  Дни повторения: {reminder.get('repeat_days')}")
        
        # Проблема: remind_time_utc может быть строкой или datetime
        remind_time = reminder['remind_time_utc']
        logger.info(f"  Время из БД (сырое): {remind_time}, тип: {type(remind_time)}")
        
        if isinstance(remind_time, str):
            try:
                remind_time = datetime.fromisoformat(remind_time.replace('Z', '+00:00'))
                # Делаем aware (с часовым поясом UTC)
                remind_time = pytz.UTC.localize(remind_time)
            except Exception as e:
                logger.error(f"Ошибка парсинга времени из строки: {e}")
                try:
                    remind_time = datetime.strptime(remind_time, '%Y-%m-%d %H:%M:%S')
                    remind_time = pytz.UTC.localize(remind_time)
                except Exception as e2:
                    logger.error(f"Вторая попытка парсинга тоже не удалась: {e2}")
                    # Если все плохо, используем текущее время
                    remind_time = datetime.now(pytz.UTC)
        
        # Если это naive datetime, добавляем UTC
        if remind_time.tzinfo is None:
            remind_time = pytz.UTC.localize(remind_time)
        
        # Конвертируем в местное время пользователя для отображения
        user_tz = pytz.timezone(user_timezone)
        local_time = remind_time.astimezone(user_tz)
        
        logger.info(f"  Время UTC: {remind_time}")
        logger.info(f"  Местное время пользователя: {local_time}")
        logger.info(f"  Разница: {(local_time - remind_time).total_seconds()/3600} часов")
        
        formatted_time = format_local_time(remind_time, user_timezone, user_lang)
        
        # Текст уведомления
        notification_text = {
            'ru': f"🔔 *Напоминание!*\n\n"
                  f"📝 {reminder['text']}\n"
                  f"⏰ {formatted_time}\n\n"
                  f"🆔 ID: {reminder['id']}",
            'en': f"🔔 *Reminder!*\n\n"
                  f"📝 {reminder['text']}\n"
                  f"⏰ {formatted_time}\n\n"
                  f"🆔 ID: {reminder['id']}"
        }
        
        await bot.send_message(
            reminder['user_id'],
            notification_text.get(user_lang, notification_text['en']),
            parse_mode="Markdown"
        )
        
        logger.info(f"✅ Напоминание {reminder['id']} отправлено пользователю {reminder['user_id']}")
        
        # Помечаем как отправленное
        db.mark_reminder_sent(reminder['id'])
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки напоминания {reminder['id']}: {e}", exc_info=True)
        # Увеличиваем счетчик ошибок
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE reminders 
                SET error_count = error_count + 1 
                WHERE id = ?
            ''', (reminder['id'],))
async def check_and_send_reminders():
    """Проверить и отправить напоминания, которые подошли по времени"""
    try:
        logger.info("=" * 50)
        logger.info("🔄 ЗАПУСК ПРОВЕРКИ НАПОМИНАНИЙ")
        
        due_reminders = db.get_due_reminders()
        
        logger.info(f"📊 Найдено напоминаний для отправки: {len(due_reminders)}")
        
        if not due_reminders:
            logger.info("✅ Нет напоминаний для отправки")
            return
        
        sent_count = 0
        error_count = 0
        
        for reminder in due_reminders:
            try:
                logger.info(f"📤 Отправляю напоминание {reminder['id']}...")
                await send_reminder_notification(reminder)
                sent_count += 1
                await asyncio.sleep(0.1)  # Небольшая пауза между отправками
                
            except Exception as e:
                logger.error(f"❌ Ошибка отправки напоминания {reminder['id']}: {e}", exc_info=True)
                error_count += 1
        
        logger.info(f"📈 ИТОГ: отправлено {sent_count}, ошибок {error_count}")
        logger.info("=" * 50)
            
    except Exception as e:
        logger.error(f"💥 КРИТИЧЕСКАЯ ОШИБКА в check_and_send_reminders: {e}", exc_info=True)

async def handle_cancel(message: types.Message, state: FSMContext, language: str):
    """Обработка отмены создания напоминания"""
    await state.clear()
    cancel_text = {
        'ru': "❌ Создание напоминания отменено",
        'en': "❌ Reminder creation cancelled"
    }
    await message.answer(
        cancel_text.get(language, cancel_text['ru']),
        reply_markup=get_main_keyboard(language)
    )

# ===== ОСНОВНЫЕ КОМАНДЫ =====

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start - начало работы"""
    user = message.from_user
    
    # Определяем часовой пояс
    timezone_name = 'Europe/Moscow'
    offset_seconds = 10800  # UTC+3 по умолчанию
    
    # Пробуем получить offset из данных Telegram
    if hasattr(user, 'timezone_offset'):
        offset_seconds = user.timezone_offset
        # Простая конвертация offset в таймзону
        offset_hours = offset_seconds // 3600
        timezone_map = {
            3: 'Europe/Moscow',
            5: 'Asia/Yekaterinburg',
            7: 'Asia/Krasnoyarsk',
            8: 'Asia/Irkutsk',
            9: 'Asia/Yakutsk',
            10: 'Asia/Vladivostok',
            11: 'Asia/Magadan',
            12: 'Asia/Kamchatka',
            0: 'UTC',
            -5: 'America/New_York',
            -8: 'America/Los_Angeles'
        }
        timezone_name = timezone_map.get(offset_hours, 'Europe/Moscow')
    
    # Регистрируем/обновляем пользователя
    db.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language_code=user.language_code or 'ru',
        timezone_offset=offset_seconds
    )
    
    # Обновляем часовой пояс, если определили
    db.update_user_timezone(user.id, timezone_name, offset_seconds)
    
    # Приветственное сообщение
    welcome_text = {
        'ru': f"Привет, {user.first_name}! 👋\n\n"
              "Я *Reminder Pro* - умная напоминалка.\n"
              "Я помогу вам не забывать о важных делах.\n\n"
              "📝 *Что я умею:*\n"
              "• Создавать разовые и повторяющиеся напоминания\n"
              "• Автоматически определять ваш часовой пояс\n"
              "• Показывать напоминания в вашем локальном времени\n"
              "• Отправлять уведомления точно в срок\n\n"
              "🎯 *Ваш часовой пояс:* {timezone}\n"
              "🌐 *Язык:* Русский\n\n"
              "Используйте меню ниже или команды:\n"
              "/add - добавить напоминание\n"
              "/list - мои напоминания\n"
              "/today - на сегодня\n"
              "/help - помощь",
        
        'en': f"Hello, {user.first_name}! 👋\n\n"
              "I'm *Reminder Pro* - smart reminder bot.\n"
              "I'll help you remember important things.\n\n"
              "📝 *What I can do:*\n"
              "• Create one-time and repeating reminders\n"
              "• Automatically detect your timezone\n"
              "• Show reminders in your local time\n"
              "• Send notifications on time\n\n"
              "🎯 *Your timezone:* {timezone}\n"
              "🌐 *Language:* English\n\n"
              "Use the menu below or commands:\n"
              "/add - add reminder\n"
              "/list - my reminders\n"
              "/today - for today\n"
              "/help - help"
    }
    
    user_lang = user.language_code or 'ru'
    if user_lang not in ['ru', 'en']:
        user_lang = 'en'
    
    # Простое отображение таймзоны
    tz_display = timezone_name.split('/')[-1].replace('_', ' ')
    
    keyboard = get_main_keyboard(user_lang)
    
    await message.answer(
        welcome_text[user_lang].format(timezone=tz_display),
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    
    logger.info(f"User {user.id} started the bot")

@dp.message(Command("help"))
@dp.message(F.text.in_(["❓ Помощь", "❓ Help"]))
async def cmd_help(message: types.Message):
    """Команда /help - помощь"""
    user = db.get_user(message.from_user.id)
    user_lang = user.get('language_code', 'ru') if user else 'ru'
    
    help_text = {
        'ru': """
📚 *Доступные команды:*

*Основные:*
/start - Начать работу
/help - Эта справка
/add - Добавить напоминание (сначала время, потом текст)
/quick - Быстрое добавление (время и текст в одном сообщении)
/list - Мои напоминания
/today - Напоминания на сегодня
/tomorrow - На завтра
/calendar - Открыть календарь

*Управление:*
/pause <id> - Пауза напоминания
/resume <id> - Возобновить
/delete <id> - Удалить
/clear - Удалить выполненные

*Настройки:*
/settings - Настройки
/language - Сменить язык
/timezone - Установить часовой пояс
/stats - Статистика

⚡ *Быстрое создание:*
`/quick завтра 15:30 сходить в музей`
`/quick через 2 часа позвонить маме`

📝 *Формат времени:*
• *Завтра 10:30* - завтра в 10:30
• *20:15* - сегодня в 20:15
• *31.12.2024 23:59* - конкретная дата
• *через 2 часа* - через 2 часа
• *ежедневно 09:00* - каждый день в 9 утра

💡 *Советы:*
• Используйте кнопки в меню для удобства
• Напоминания работают в вашем часовом поясе
• Можно ставить напоминания на паузу
• Лимит: 100 активных напоминаний
        """,
        
        'en': """
📚 *Available commands:*

*Basic:*
/start - Start bot
/help - This help
/add - Add reminder (time first, then text)
/quick - Quick add (time and text in one message)
/list - My reminders
/today - For today
/tomorrow - For tomorrow
/calendar - Open calendar

*Management:*
/pause <id> - Pause reminder
/resume <id> - Resume
/delete <id> - Delete
/clear - Delete completed

*Settings:*
/settings - Settings
/language - Change language
/timezone - Set timezone
/stats - Statistics

⚡ *Quick creation:*
`/quick tomorrow 3:30 PM go to museum`
`/quick in 2 hours call mom`

📝 *Time formats:*
• *Tomorrow 10:30* - tomorrow at 10:30
• *20:15* - today at 20:15
• *12/31/2024 23:59* - specific date
• *in 2 hours* - in 2 hours
• *daily 09:00* - every day at 9 AM

💡 *Tips:*
• Use menu buttons for convenience
• Reminders work in your timezone
• You can pause reminders
• Limit: 100 active reminders
        """
    }
    
    await message.answer(
        help_text[user_lang],
        parse_mode="Markdown"
    )

@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    """Отмена текущей операции"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    language = user.get('language_code', 'ru') if user else 'ru'
    
    current_state = await state.get_state()
    
    if current_state:
        await state.clear()
        cancel_text = {
            'ru': "❌ Операция отменена.",
            'en': "❌ Operation cancelled."
        }
        await message.answer(
            cancel_text.get(language, cancel_text['ru']),
            reply_markup=get_main_keyboard(language)
        )
    else:
        no_op_text = {
            'ru': "ℹ️ Нет активных операций для отмены.",
            'en': "ℹ️ No active operations to cancel."
        }
        await message.answer(no_op_text.get(language, no_op_text['ru']))

# ===== КОМАНДЫ ДЛЯ СЕГОДНЯ/ЗАВТРА =====

@dp.message(Command("today"))
@dp.message(F.text.in_(["📅 На сегодня", "📅 For today"]))
async def cmd_today(message: types.Message):
    """Показать напоминания на сегодня - С УЧЕТОМ ПОВТОРЯЮЩИХСЯ"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    timezone = user.get('timezone', 'Europe/Moscow')
    
    reminders = db.get_user_reminders(user_id, active_only=True)
    
    if not reminders:
        empty_text = {
            'ru': "📭 У вас нет активных напоминаний на сегодня.",
            'en': "📭 You have no active reminders for today."
        }
        await message.answer(empty_text.get(language, empty_text['ru']))
        return
    
    user_tz = pytz.timezone(timezone)
    now_utc = datetime.now(pytz.UTC)
    now_local = now_utc.astimezone(user_tz)
    
    today_reminders = []
    
    for reminder in reminders:
        # ВАЖНОЕ ИЗМЕНЕНИЕ: для повторяющихся напоминаний используем next_remind_time_utc
        if reminder['repeat_type'] != 'once':
            # Для повторяющихся напоминаний используем следующее время
            remind_time = reminder.get('next_remind_time_utc')
            if remind_time is None:
                # Если нет next_remind_time_utc, используем оригинальное
                remind_time = reminder['remind_time_utc']
        else:
            # Для разовых используем оригинальное время
            remind_time = reminder['remind_time_utc']
        
        # Обработка времени
        if isinstance(remind_time, str):
            try:
                remind_time = datetime.fromisoformat(remind_time)
            except:
                try:
                    remind_time = datetime.strptime(remind_time, '%Y-%m-%d %H:%M:%S')
                except:
                    continue
        
        # Делаем aware UTC
        if remind_time.tzinfo is None:
            remind_time_utc = pytz.UTC.localize(remind_time)
        else:
            remind_time_utc = remind_time.astimezone(pytz.UTC)
        
        # Конвертируем в локальное время пользователя
        remind_time_local = remind_time_utc.astimezone(user_tz)
        
        # Сравниваем с сегодняшней датой
        if remind_time_local.date() == now_local.date():
            formatted_time = format_local_time(remind_time, timezone, language)
            today_reminders.append((reminder, formatted_time, remind_time_local))
    
    if not today_reminders:
        empty_text = {
            'ru': "📅 У вас нет напоминаний на сегодня.",
            'en': "📅 You have no reminders for today."
        }
        await message.answer(empty_text.get(language, empty_text['ru']))
        return
    
    # Сортируем по времени
    today_reminders.sort(key=lambda x: x[2])  # сортируем по remind_time_local
    
    # Формируем заголовок
    if language == 'ru':
        date_str = now_local.strftime('%d.%m.%Y')
        response_text = f"📅 *Напоминания на сегодня ({date_str}):*\n\n"
    else:
        date_str = now_local.strftime("%B %d, %Y")
        response_text = f"📅 *Reminders for today ({date_str}):*\n\n"
    
    # Выводим
    for i, (reminder, formatted_time, _) in enumerate(today_reminders, 1):
        repeat_type = reminder['repeat_type']
        if repeat_type == 'once':
            repeat_symbol = "✅"
            repeat_text = "разовое" if language == 'ru' else "one-time"
        elif repeat_type == 'daily':
            repeat_symbol = "🔄"
            repeat_text = "ежедневное" if language == 'ru' else "daily"
        elif repeat_type == 'weekly':
            repeat_symbol = "📅"
            repeat_text = "еженедельное" if language == 'ru' else "weekly"
        else:
            repeat_symbol = "📌"
            repeat_text = ""
        
        # Извлекаем только время из formatted_time
        # formatted_time: "15 января 2024, 14:30" или "January 15, 2024, 2:30 PM"
        if ',' in formatted_time:
            time_part = formatted_time.split(',')[1].strip()
        else:
            time_part = formatted_time
        
        response_text += f"{i}. {repeat_symbol} *{time_part}* - {reminder['text']}\n"
        response_text += f"   🆔 ID: {reminder['id']} ({repeat_text})\n\n"
    
    if language == 'ru':
        response_text += f"Всего: {len(today_reminders)} напоминаний"
    else:
        response_text += f"Total: {len(today_reminders)} reminders"
    
    await message.answer(response_text, parse_mode="Markdown")


@dp.message(Command("tomorrow"))
@dp.message(F.text.in_(["📆 На завтра", "📆 For tomorrow"]))
async def cmd_tomorrow(message: types.Message):
    """Показать напоминания на завтра - С УЧЕТОМ ПОВТОРЯЮЩИХСЯ"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    timezone = user.get('timezone', 'Europe/Moscow')
    
    reminders = db.get_user_reminders(user_id, active_only=True)
    
    if not reminders:
        empty_text = {
            'ru': "📭 У вас нет активных напоминаний на завтра.",
            'en': "📭 You have no active reminders for tomorrow."
        }
        await message.answer(empty_text.get(language, empty_text['ru']))
        return
    
    user_tz = pytz.timezone(timezone)
    now_utc = datetime.now(pytz.UTC)
    now_local = now_utc.astimezone(user_tz)
    tomorrow_local = now_local + timedelta(days=1)
    
    tomorrow_reminders = []
    
    for reminder in reminders:
        # ВАЖНОЕ ИЗМЕНЕНИЕ: для повторяющихся напоминаний используем next_remind_time_utc
        if reminder['repeat_type'] != 'once':
            # Для повторяющихся напоминаний используем следующее время
            remind_time = reminder.get('next_remind_time_utc')
            if remind_time is None:
                # Если нет next_remind_time_utc, используем оригинальное
                remind_time = reminder['remind_time_utc']
        else:
            # Для разовых используем оригинальное время
            remind_time = reminder['remind_time_utc']
        
        # Обработка времени
        if isinstance(remind_time, str):
            try:
                remind_time = datetime.fromisoformat(remind_time)
            except:
                try:
                    remind_time = datetime.strptime(remind_time, '%Y-%m-%d %H:%M:%S')
                except:
                    continue
        
        # Делаем aware UTC
        if remind_time.tzinfo is None:
            remind_time_utc = pytz.UTC.localize(remind_time)
        else:
            remind_time_utc = remind_time.astimezone(pytz.UTC)
        
        # Конвертируем в локальное время пользователя
        remind_time_local = remind_time_utc.astimezone(user_tz)
        
        # Сравниваем с завтрашней датой
        if remind_time_local.date() == tomorrow_local.date():
            formatted_time = format_local_time(remind_time, timezone, language)
            tomorrow_reminders.append((reminder, formatted_time, remind_time_local))
    
    if not tomorrow_reminders:
        empty_text = {
            'ru': "📆 У вас нет напоминаний на завтра.",
            'en': "📆 You have no reminders for tomorrow."
        }
        await message.answer(empty_text.get(language, empty_text['ru']))
        return
    
    # Сортируем по времени
    tomorrow_reminders.sort(key=lambda x: x[2])  # сортируем по remind_time_local
    
    # Форматируем дату завтра
    if language == 'ru':
        months_ru = [
            'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
            'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'
        ]
        date_str = f"{tomorrow_local.day} {months_ru[tomorrow_local.month - 1]} {tomorrow_local.year}"
        response_text = f"📆 *Напоминания на завтра ({date_str}):*\n\n"
    else:
        date_str = tomorrow_local.strftime("%B %d, %Y")
        response_text = f"📆 *Reminders for tomorrow ({date_str}):*\n\n"
    
    for i, (reminder, formatted_time, _) in enumerate(tomorrow_reminders, 1):
        repeat_type = reminder['repeat_type']
        if repeat_type == 'once':
            repeat_symbol = "✅"
            repeat_text = "разовое" if language == 'ru' else "one-time"
        elif repeat_type == 'daily':
            repeat_symbol = "🔄"
            repeat_text = "ежедневное" if language == 'ru' else "daily"
        elif repeat_type == 'weekly':
            repeat_symbol = "📅"
            repeat_text = "еженедельное" if language == 'ru' else "weekly"
        else:
            repeat_symbol = "📌"
            repeat_text = ""
        
        # Извлекаем только время из formatted_time
        if ',' in formatted_time:
            time_part = formatted_time.split(',')[1].strip()
        else:
            time_part = formatted_time
        
        response_text += f"{i}. {repeat_symbol} *{time_part}* - {reminder['text']}\n"
        response_text += f"   🆔 ID: {reminder['id']} ({repeat_text})\n\n"
    
    if language == 'ru':
        response_text += f"Всего: {len(tomorrow_reminders)} напоминаний"
    else:
        response_text += f"Total: {len(tomorrow_reminders)} reminders"
    
    await message.answer(response_text, parse_mode="Markdown")

# ===== ПРОСМОТР НАПОМИНАНИЙ =====

@dp.message(Command("list"))
@dp.message(F.text.in_(["📋 Мои напоминания", "📋 My reminders"]))
async def cmd_list(message: types.Message):
    """Показать список всех напоминаний пользователя (активных и на паузе)"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    timezone = user.get('timezone', 'Europe/Moscow')
    
    # Получаем ВСЕ напоминания пользователя (активные и на паузе)
    reminders = db.get_user_reminders(user_id, active_only=False)
    
    if not reminders:
        empty_text = {
            'ru': "📭 У вас нет напоминаний.",
            'en': "📭 You have no reminders."
        }
        await message.answer(empty_text.get(language, empty_text['ru']))
        return
    
    # Разделяем на активные и на паузе
    active_reminders = [r for r in reminders if r['is_active']]
    paused_reminders = [r for r in reminders if not r['is_active']]
    
    # Ограничиваем вывод 15 напоминаниями (10 активных + 5 на паузе)
    limited_active = active_reminders[:10]
    limited_paused = paused_reminders[:5]
    
    response_text = {
        'ru': f"📋 *Ваши напоминания*\n\n"
              f"✅ Активных: {len(active_reminders)}\n"
              f"⏸️ На паузе: {len(paused_reminders)}\n"
              f"📊 Всего: {len(reminders)}\n\n",
        'en': f"📋 *Your reminders*\n\n"
              f"✅ Active: {len(active_reminders)}\n"
              f"⏸️ Paused: {len(paused_reminders)}\n"
              f"📊 Total: {len(reminders)}\n\n"
    }.get(language, f"📋 Your reminders:\n\n")
    
    # Активные напоминания
    if limited_active:
        response_text += {
            'ru': "✅ *Активные напоминания:*\n",
            'en': "✅ *Active reminders:*\n"
        }.get(language, "Active reminders:\n")
        
        for i, reminder in enumerate(limited_active, 1):
            # Форматируем время
            remind_time = reminder['remind_time_utc']
            if isinstance(remind_time, str):
                remind_time = datetime.fromisoformat(remind_time)
            
            formatted_time = format_local_time(remind_time, timezone, language)
            
            # Тип повторения
            repeat_type = reminder['repeat_type']
            if repeat_type == 'once':
                repeat_symbol = "✅"
            elif repeat_type == 'daily':
                repeat_symbol = "🔄"
            elif repeat_type == 'weekly':
                repeat_symbol = "📅"
            else:
                repeat_symbol = "📌"
            
            # Обрезаем текст если слишком длинный
            text = reminder['text']
            if len(text) > 40:
                text = text[:37] + "..."
            
            response_text += f"{i}. {repeat_symbol} *ID: {reminder['id']}* - {text}\n"
            response_text += f"   ⏰ {formatted_time}\n\n"
    
    # Напоминания на паузе
    if limited_paused:
        response_text += {
            'ru': "⏸️ *Напоминания на паузе:*\n",
            'en': "⏸️ *Paused reminders:*\n"
        }.get(language, "Paused reminders:\n")
        
        for i, reminder in enumerate(limited_paused, 1):
            # Форматируем время
            remind_time = reminder['remind_time_utc']
            if isinstance(remind_time, str):
                remind_time = datetime.fromisoformat(remind_time)
            
            formatted_time = format_local_time(remind_time, timezone, language)
            
            # Обрезаем текст если слишком длинный
            text = reminder['text']
            if len(text) > 40:
                text = text[:37] + "..."
            
            response_text += f"{i}. ⏸️ *ID: {reminder['id']}* - {text}\n"
            response_text += f"   ⏰ {formatted_time}\n"
            
            # Показываем кнопку возобновления
            response_text += f"   ▶️ Используйте /resume {reminder['id']}\n\n"
    
    # Если есть еще напоминания, показываем информацию
    if len(active_reminders) > 10 or len(paused_reminders) > 5:
        remaining_active = len(active_reminders) - 10
        remaining_paused = len(paused_reminders) - 5
        
        if remaining_active > 0 and remaining_paused > 0:
            response_text += {
                'ru': f"📝 ... и еще {remaining_active} активных и {remaining_paused} на паузе",
                'en': f"📝 ... and {remaining_active} more active, {remaining_paused} more paused"
            }.get(language, f"... and {remaining_active} more")
        elif remaining_active > 0:
            response_text += {
                'ru': f"📝 ... и еще {remaining_active} активных напоминаний",
                'en': f"📝 ... and {remaining_active} more active reminders"
            }.get(language, f"... and {remaining_active} more")
        elif remaining_paused > 0:
            response_text += {
                'ru': f"📝 ... и еще {remaining_paused} напоминаний на паузе",
                'en': f"📝 ... and {remaining_paused} more paused reminders"
            }.get(language, f"... and {remaining_paused} more")
    
    # Добавляем подсказки по управлению
    response_text += {
        'ru': f"\n\n💡 *Управление:*\n"
              f"/delete <ID> - удалить\n"
              f"/pause <ID> - пауза\n"
              f"/resume <ID> - возобновить\n"
              f"/clear - удалить выполненные",
        'en': f"\n\n💡 *Management:*\n"
              f"/delete <ID> - delete\n"
              f"/pause <ID> - pause\n"
              f"/resume <ID> - resume\n"
              f"/clear - delete completed"
    }.get(language, "\n\nUse /delete <ID>, /pause <ID>, /resume <ID>")
    
    await message.answer(response_text, parse_mode="Markdown")
# ===== УДАЛЕНИЕ НАПОМИНАНИЙ =====

@dp.message(Command("delete"))
async def cmd_delete(message: types.Message):
    """Удалить напоминание по ID"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    
    # Получаем аргумент (ID напоминания)
    args = message.text.split()
    if len(args) < 2:
        # Если нет ID, показываем список напоминаний с кнопками для удаления
        await show_reminders_for_deletion(message, user_id, language)
        return
    
    try:
        reminder_id = int(args[1])
    except ValueError:
        error_text = {
            'ru': "❌ ID должен быть числом!",
            'en': "❌ ID must be a number!"
        }
        await message.answer(error_text.get(language, error_text['ru']))
        return
    
    # Пробуем удалить
    success = db.delete_reminder(reminder_id, user_id)
    
    if success:
        success_text = {
            'ru': f"✅ Напоминание *{reminder_id}* удалено!",
            'en': f"✅ Reminder *{reminder_id}* deleted!"
        }
        await message.answer(
            success_text.get(language, success_text['ru']),
            parse_mode="Markdown"
        )
    else:
        error_text = {
            'ru': f"❌ Не удалось удалить напоминание *{reminder_id}*.\n"
                  "Проверьте ID или убедитесь, что напоминание принадлежит вам.",
            'en': f"❌ Failed to delete reminder *{reminder_id}*.\n"
                  "Check the ID or make sure the reminder belongs to you."
        }
        await message.answer(
            error_text.get(language, error_text['ru']),
            parse_mode="Markdown"
        )

async def show_reminders_for_deletion(message: types.Message, user_id: int, language: str):
    """Показать напоминания для выбора удаления"""
    reminders = db.get_user_reminders(user_id, active_only=True)
    
    if not reminders:
        empty_text = {
            'ru': "📭 У вас нет активных напоминаний для удаления.",
            'en': "📭 You have no active reminders to delete."
        }
        await message.answer(empty_text.get(language, empty_text['ru']))
        return
    
    text = {
        'ru': f"🗑️ *Выберите напоминание для удаления:*\n\n",
        'en': f"🗑️ *Select reminder to delete:*\n\n"
    }.get(language, "Select reminder to delete:\n\n")
    
    builder = InlineKeyboardBuilder()
    
    for i, reminder in enumerate(reminders[:10], 1):
        # Форматируем текст
        reminder_text = reminder['text'][:30] + "..." if len(reminder['text']) > 30 else reminder['text']
        text += f"{i}. ID: {reminder['id']} - {reminder_text}\n"
        
        # Добавляем кнопку для удаления
        builder.add(InlineKeyboardButton(
            text=f"🗑️ {reminder['id']}",
            callback_data=f"delete_{reminder['id']}"
        ))
    
    builder.adjust(3)
    
    # Добавляем кнопку отмены
    builder.row(
        InlineKeyboardButton(
            text="❌ Отмена" if language == 'ru' else "❌ Cancel",
            callback_data="delete_cancel"
        )
    )
    
    await message.answer(
        text.get(language, text),
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("delete_"))
async def handle_delete_callback(callback: types.CallbackQuery):
    """Обработка callback для удаления"""
    data = callback.data
    user_id = callback.from_user.id
    user = db.get_user(user_id)
    language = user.get('language_code', 'ru') if user else 'ru'
    
    if data == "delete_cancel":
        await callback.message.delete()
        await callback.answer("Отмена удаления" if language == 'ru' else "Delete cancelled")
        return
    
    try:
        reminder_id = int(data.replace("delete_", ""))
        
        # Пробуем удалить
        success = db.delete_reminder(reminder_id, user_id)
        
        if success:
            await callback.message.edit_text(
                f"✅ Напоминание {reminder_id} удалено!" if language == 'ru' else f"✅ Reminder {reminder_id} deleted!"
            )
        else:
            await callback.message.edit_text(
                f"❌ Не удалось удалить напоминание {reminder_id}" if language == 'ru' else f"❌ Failed to delete reminder {reminder_id}"
            )
    except ValueError:
        await callback.answer("Ошибка ID" if language == 'ru' else "ID error", show_alert=True)
    
    await callback.answer()

@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    """Удалить все выполненные напоминания"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    
    # Получаем все напоминания пользователя
    all_reminders = db.get_user_reminders(user_id, active_only=False)
    
    if not all_reminders:
        empty_text = {
            'ru': "📭 У вас нет напоминаний.",
            'en': "📭 You have no reminders."
        }
        await message.answer(empty_text.get(language, empty_text['ru']))
        return
    
    # Считаем неактивные (выполненные)
    inactive_reminders = [r for r in all_reminders if not r['is_active']]
    
    if not inactive_reminders:
        no_inactive_text = {
            'ru': "✅ У вас нет выполненных напоминаний для удаления.",
            'en': "✅ You have no completed reminders to delete."
        }
        await message.answer(no_inactive_text.get(language, no_inactive_text['ru']))
        return
    
    # Удаляем каждое неактивное напоминание
    deleted_count = 0
    for reminder in inactive_reminders:
        if db.delete_reminder(reminder['id'], user_id):
            deleted_count += 1
    
    result_text = {
        'ru': f"🧹 Удалено {deleted_count} выполненных напоминаний!",
        'en': f"🧹 Deleted {deleted_count} completed reminders!"
    }
    
    await message.answer(result_text.get(language, result_text['ru']))

# ===== ПАУЗА/ВОЗОБНОВЛЕНИЕ =====

@dp.message(Command("pause"))
async def cmd_pause(message: types.Message):
    """Поставить напоминание на паузу"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    
    # Получаем аргумент (ID напоминания)
    args = message.text.split()
    if len(args) < 2:
        # Если нет ID, показываем список напоминаний с кнопками для паузы
        await show_reminders_for_pause(message, user_id, language)
        return
    
    try:
        reminder_id = int(args[1])
    except ValueError:
        error_text = {
            'ru': "❌ ID должен быть числом!",
            'en': "❌ ID must be a number!"
        }
        await message.answer(error_text.get(language, error_text['ru']))
        return
    
    # Пробуем поставить на паузу
    success = db.pause_reminder(reminder_id, user_id)
    
    if success:
        success_text = {
            'ru': f"⏸️ Напоминание *{reminder_id}* поставлено на паузу.",
            'en': f"⏸️ Reminder *{reminder_id}* paused."
        }
        await message.answer(
            success_text.get(language, success_text['ru']),
            parse_mode="Markdown"
        )
    else:
        error_text = {
            'ru': f"❌ Не удалось поставить напоминание *{reminder_id}* на паузу.\n"
                  "Проверьте ID или убедитесь, что напоминание принадлежит вам.",
            'en': f"❌ Failed to pause reminder *{reminder_id}*.\n"
                  "Check the ID or make sure the reminder belongs to you."
        }
        await message.answer(
            error_text.get(language, error_text['ru']),
            parse_mode="Markdown"
        )

async def show_reminders_for_pause(message: types.Message, user_id: int, language: str):
    """Показать напоминания для выбора паузы"""
    reminders = db.get_user_reminders(user_id, active_only=True)
    
    if not reminders:
        empty_text = {
            'ru': "📭 У вас нет активных напоминаний для паузы.",
            'en': "📭 You have no active reminders to pause."
        }
        await message.answer(empty_text.get(language, empty_text['ru']))
        return
    
    text = {
        'ru': f"⏸️ *Выберите напоминание для паузы:*\n\n",
        'en': f"⏸️ *Select reminder to pause:*\n\n"
    }.get(language, "Select reminder to pause:\n\n")
    
    builder = InlineKeyboardBuilder()
    
    for i, reminder in enumerate(reminders[:10], 1):
        # Форматируем текст
        reminder_text = reminder['text'][:30] + "..." if len(reminder['text']) > 30 else reminder['text']
        text += f"{i}. ID: {reminder['id']} - {reminder_text}\n"
        
        # Добавляем кнопку для паузы
        builder.add(InlineKeyboardButton(
            text=f"⏸️ {reminder['id']}",
            callback_data=f"pause_{reminder['id']}"
        ))
    
    builder.adjust(3)
    
    # Добавляем кнопку отмены
    builder.row(
        InlineKeyboardButton(
            text="❌ Отмена" if language == 'ru' else "❌ Cancel",
            callback_data="pause_cancel"
        )
    )
    
    await message.answer(
        text.get(language, text),
        reply_markup=builder.as_markup()
    )

@dp.message(Command("resume"))
async def cmd_resume(message: types.Message):
    """Возобновить напоминание"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    
    # Получаем аргумент (ID напоминания)
    args = message.text.split()
    if len(args) < 2:
        error_text = {
            'ru': "❌ *Использование:* /resume <ID_напоминания>\n\n"
                  "Пример:\n`/resume 5`\n\n"
                  "Используйте /list чтобы увидеть ID ваших напоминаний.",
            'en': "❌ *Usage:* /resume <reminder_id>\n\n"
                  "Example:\n`/resume 5`\n\n"
                  "Use /list to see your reminder IDs."
        }
        await message.answer(
            error_text.get(language, error_text['ru']),
            parse_mode="Markdown"
        )
        return
    
    try:
        reminder_id = int(args[1])
    except ValueError:
        error_text = {
            'ru': "❌ ID должен быть числом!",
            'en': "❌ ID must be a number!"
        }
        await message.answer(error_text.get(language, error_text['ru']))
        return
    
    # Пробуем возобновить
    success = db.resume_reminder(reminder_id, user_id)
    
    if success:
        success_text = {
            'ru': f"▶️ Напоминание *{reminder_id}* возобновлено.",
            'en': f"▶️ Reminder *{reminder_id}* resumed."
        }
        await message.answer(
            success_text.get(language, success_text['ru']),
            parse_mode="Markdown"
        )
    else:
        error_text = {
            'ru': f"❌ Не удалось возобновить напоминание *{reminder_id}*.\n"
                  "Проверьте ID или убедитесь, что напоминание принадлежит вам.",
            'en': f"❌ Failed to resume reminder *{reminder_id}*.\n"
                  "Check the ID or make sure the reminder belongs to you."
        }
        await message.answer(
            error_text.get(language, error_text['ru']),
            parse_mode="Markdown"
        )

# ===== СТАТИСТИКА =====

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """Показать статистику пользователя"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    timezone = user.get('timezone', 'Europe/Moscow')
    
    # Получаем все напоминания пользователя
    reminders = db.get_user_reminders(user_id, active_only=False)
    active_reminders = db.get_user_reminders(user_id, active_only=True)
    
    # Считаем статистику
    total_count = len(reminders)
    active_count = len(active_reminders)
    completed_count = total_count - active_count
    
    # Считаем по типам
    once_count = sum(1 for r in active_reminders if r['repeat_type'] == 'once')
    daily_count = sum(1 for r in active_reminders if r['repeat_type'] == 'daily')
    weekly_count = sum(1 for r in active_reminders if r['repeat_type'] == 'weekly')
    
    # Самые ранние и поздние напоминания
    if active_reminders:
        # Преобразуем времена
        reminder_times = []
        for reminder in active_reminders:
            remind_time = reminder.get('next_remind_time_utc')
            if isinstance(remind_time, str):
                try:
                    remind_time = datetime.fromisoformat(remind_time.replace('Z', '+00:00'))
                    remind_time = pytz.UTC.localize(remind_time) if remind_time.tzinfo is None else remind_time
                    reminder_times.append((reminder, remind_time))
                except:
                    continue
        
        if reminder_times:
            # Сортируем по времени
            reminder_times.sort(key=lambda x: x[1])
            earliest = reminder_times[0]
            latest = reminder_times[-1]
            
            # Конвертируем в локальное время
            user_tz = pytz.timezone(timezone)
            earliest_local = earliest[1].astimezone(user_tz)
            latest_local = latest[1].astimezone(user_tz)
            
            earliest_time = earliest_local.strftime('%d.%m.%Y %H:%M')
            latest_time = latest_local.strftime('%d.%m.%Y %H:%M')
        else:
            earliest_time = latest_time = "-"
    else:
        earliest_time = latest_time = "-"
    
    if language == 'ru':
        stats_text = f"📊 *Ваша статистика*\n\n"
        stats_text += f"📅 Всего напоминаний: {total_count}\n"
        stats_text += f"✅ Активных: {active_count}\n"
        stats_text += f"✓ Выполненных: {completed_count}\n\n"
        stats_text += f"📌 По типам:\n"
        stats_text += f"  • Разовые: {once_count}\n"
        stats_text += f"  • Ежедневные: {daily_count}\n"
        stats_text += f"  • Еженедельные: {weekly_count}\n\n"
        stats_text += f"⏰ Ближайшее напоминание: {earliest_time}\n"
        stats_text += f"⏰ Самое позднее: {latest_time}\n\n"
        stats_text += f"🕒 Часовой пояс: {timezone}"
    else:
        stats_text = f"📊 *Your Statistics*\n\n"
        stats_text += f"📅 Total reminders: {total_count}\n"
        stats_text += f"✅ Active: {active_count}\n"
        stats_text += f"✓ Completed: {completed_count}\n\n"
        stats_text += f"📌 By type:\n"
        stats_text += f"  • One-time: {once_count}\n"
        stats_text += f"  • Daily: {daily_count}\n"
        stats_text += f"  • Weekly: {weekly_count}\n\n"
        stats_text += f"⏰ Earliest reminder: {earliest_time}\n"
        stats_text += f"⏰ Latest reminder: {latest_time}\n\n"
        stats_text += f"🕒 Timezone: {timezone}"
    
    await message.answer(stats_text, parse_mode="Markdown")

# ===== КАЛЕНДАРЬ =====

@dp.message(Command("calendar"))
async def cmd_calendar(message: types.Message):
    """Команда календаря (заглушка)"""
    user = db.get_user(message.from_user.id)
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    
    calendar_text = {
        'ru': "📅 *Интерактивный календарь*\n\n"
              "Функция календаря в разработке.\n"
              "Пока используйте текстовый ввод времени.\n\n"
              "Примеры:\n"
              "• Завтра 10:30\n"
              "• Сегодня в 18:00\n"
              "• 31.12.2024 23:59",
        'en': "📅 *Interactive Calendar*\n\n"
              "Calendar feature is under development.\n"
              "Use text input for now.\n\n"
              "Examples:\n"
              "• Tomorrow 10:30 AM\n"
              "• Today at 6:00 PM\n"
              "• 12/31/2024 11:59 PM"
    }
    
    examples = time_parser.get_examples(language)
    examples_text = "\n".join([f"• {example}" for example in examples[:5]])
    
    full_text = f"{calendar_text.get(language, calendar_text['ru'])}\n\n📋 *Примеры:*\n{examples_text}"
    
    await message.answer(full_text, parse_mode="Markdown")

# ===== ТЕСТОВЫЕ КОМАНДЫ =====

@dp.message(Command("test_time"))
async def cmd_test_time(message: types.Message):
    """Тестовая команда для проверки времени"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    timezone = user.get('timezone', 'Europe/Moscow')
    
    # Текущее время в разных часовых поясах
    now_utc = datetime.now(pytz.UTC)
    user_tz = pytz.timezone(timezone)
    now_local = now_utc.astimezone(user_tz)
    
    test_text = {
        'ru': f"⏰ *Тест времени*\n\n"
              f"🕐 Текущее время UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}\n"
              f"🏠 Ваше местное время ({timezone}): {now_local.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
              f"*Примеры:*\n"
              f"• 'через 5 минут' - напоминание через 5 минут\n"
              f"• '18:30' - сегодня в 18:30\n"
              f"• 'завтра 10:00' - завтра в 10:00",
        'en': f"⏰ *Time Test*\n\n"
              f"🕐 Current UTC time: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}\n"
              f"🏠 Your local time ({timezone}): {now_local.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
              f"*Examples:*\n"
              f"• 'in 5 minutes' - reminder in 5 minutes\n"
              f"• '18:30' - today at 18:30\n"
              f"• 'tomorrow 10:00' - tomorrow at 10:00"
    }
    
    await message.answer(
        test_text.get(language, test_text['en']),
        parse_mode="Markdown"
    )

@dp.message(Command("check_now"))
async def cmd_check_now(message: types.Message):
    """Немедленно проверить и отправить напоминания"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    
    await message.answer("🔍 Проверяю напоминания...")
    
    # Немедленно запускаем проверку
    await check_and_send_reminders()
    
    response = {
        'ru': "✅ Проверка завершена. Смотрите логи бота.",
        'en': "✅ Check completed. See bot logs."
    }
    
    await message.answer(response.get(language, response['en']))

@dp.message(Command("add"))
@dp.message(F.text.in_(["➕ Добавить напоминание", "➕ Add reminder"]))
async def add_reminder_start(message: types.Message, state: FSMContext):
    """Начало добавления напоминания - сначала время!"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    
    # Проверяем лимит
    count = db.get_user_reminder_count(user_id)
    if count >= Config.MAX_REMINDERS_PER_USER:
        limit_text = {
            'ru': f"⚠️ Достигнут лимит в {Config.MAX_REMINDERS_PER_USER} напоминаний!\n"
                  f"У вас {count} активных напоминаний.\n\n"
                  "Удалите старые или поставьте на паузу, чтобы добавить новые.",
            'en': f"⚠️ Reached limit of {Config.MAX_REMINDERS_PER_USER} reminders!\n"
                  f"You have {count} active reminders.\n\n"
                  "Delete old ones or pause them to add new."
        }
        await message.answer(
            limit_text.get(language, limit_text['ru']),
            parse_mode="Markdown"
        )
        return
    
    # Запрашиваем время напоминания
    time_request = {
        'ru': "🕐 *Сначала укажите время напоминания*\n\n"
              "📋 *Примеры:*\n"
              "• Завтра 15:30\n"
              "• Сегодня в 18:00\n"
              "• Через 2 часа\n"
              "• Понедельник в 9 утра\n"
              "• 31.12.2024 23:59\n\n"
              "Или просто время:\n"
              "• 20:30 (сегодня в 20:30)\n"
              "• 8 утра (завтра в 8 утра, если уже позже)",
        
        'en': "🕐 *First, specify the reminder time*\n\n"
              "📋 *Examples:*\n"
              "• Tomorrow 3:30 PM\n"
              "• Today at 6:00 PM\n"
              "• In 2 hours\n"
              "• Monday at 9 AM\n"
              "• 12/31/2024 11:59 PM\n\n"
              "Or just time:\n"
              "• 20:30 (today at 8:30 PM)\n"
              "• 8 AM (tomorrow at 8 AM if it's already later)"
    }
    
    # Получаем примеры из парсера
    examples = time_parser.get_examples(language)
    examples_text = "\n".join([f"• {example}" for example in examples[:8]])
    
    full_text = f"{time_request.get(language, time_request['ru'])}\n\n{examples_text}"
    
    await message.answer(
        full_text,
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(language)
    )
    
    await state.set_state(ReminderState.waiting_for_time)

@dp.message(Command("quick"))
async def cmd_quick(message: types.Message, state: FSMContext):
    """Быстрое создание напоминания в формате "время текст" """
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    timezone = user.get('timezone', 'Europe/Moscow')
    
    # Получаем текст команды без "/quick"
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        help_text = {
            'ru': "⚡ *Быстрое создание напоминания*\n\n"
                  "Формат:\n`/quick завтра 15:30 сходить в музей`\n\n"
                  "Или:\n`/quick через 2 часа позвонить маме`",
            'en': "⚡ *Quick reminder creation*\n\n"
                  "Format:\n`/quick tomorrow 3:30 PM go to museum`\n\n"
                  "Or:\n`/quick in 2 hours call mom`"
        }
        await message.answer(help_text.get(language, help_text['ru']), parse_mode="Markdown")
        return
    
    full_text = args[1]
    
    # Пробуем разделить на время и текст
    time_part, text_part = time_parser.extract_time_and_text(full_text, language)
    
    if not time_part:
        # Не нашли время - просим указать отдельно
        error_text = {
            'ru': "❌ Не удалось найти время в вашем сообщении.\n\n"
                  "Попробуйте:\n`/quick завтра 15:30 текст`\n\n"
                  "Или используйте обычный режим: /add",
            'en': "❌ Could not find time in your message.\n\n"
                  "Try:\n`/quick tomorrow 3:30 PM text`\n\n"
                  "Or use regular mode: /add"
        }
        await message.answer(error_text.get(language, error_text['ru']), parse_mode="Markdown")
        return
    
    if not text_part:
        # Нашли время, но нет текста
        text_request = {
            'ru': f"🕐 *Время распознано:* {time_part}\n\n"
                  "📝 *Введите текст напоминания:*",
            'en': f"🕐 *Time recognized:* {time_part}\n\n"
                  "📝 *Enter reminder text:*"
        }
        
        await state.update_data(quick_time=time_part, timezone=timezone, language_code=language)
        await state.set_state(ReminderState.waiting_for_text)
        await message.answer(text_request.get(language, text_request['ru']), parse_mode="Markdown")
        return
    
    # Есть и время, и текст - парсим время
    parsed_time, parse_type, extra_info = time_parser.parse(time_part, language, timezone)
    
    if not parsed_time:
        error_text = {
            'ru': f"❌ Не удалось распознать время: '{time_part}'",
            'en': f"❌ Could not recognize time: '{time_part}'"
        }
        await message.answer(error_text.get(language, error_text['ru']))
        return
    
    # Показываем подтверждение и спрашиваем про повторения
    await ask_for_repeat_type(message, parsed_time, text_part, timezone, language)
    
    # Сохраняем в состоянии
    await state.update_data(
        parsed_time=parsed_time.isoformat(),
        timezone=timezone,
        text=text_part
    )

@dp.message(ReminderState.waiting_for_time)
async def process_reminder_time(message: types.Message, state: FSMContext):
    """Обработка времени напоминания"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    language = user.get('language_code', 'ru')
    timezone = user.get('timezone', 'Europe/Moscow')
    
    # Проверяем отмену (более широкий список)
    cancel_texts = ["❌ отмена", "❌ cancel", "отмена", "cancel", "/cancel", "отменить", "cancelar"]
    if message.text.lower() in [ct.lower() for ct in cancel_texts]:
        await handle_cancel(message, state, language)
        return
    
    original_time_text = message.text.strip()
    
    # Сначала пробуем распарсить как "11 января 16-00 театр в 18-00"
    # Извлекаем время из строки
    extracted_time, extracted_text = time_parser.extract_best_time_and_text(original_time_text, language)
    
    if extracted_time and not extracted_text:
        # В строке только время (без дополнительного текста)
        time_to_parse = extracted_time
    elif extracted_time and extracted_text:
        # В строке и время, и текст - сохраняем текст для предзаполнения
        time_to_parse = extracted_time
        await state.update_data(prefill_text=extracted_text)
    else:
        # Не нашли время в привычном формате, пробуем парсить всю строку
        time_to_parse = original_time_text
    
    # Парсим время
    parsed_time, parse_type, extra_info = time_parser.parse(
        time_to_parse, language, timezone
    )
    
    if not parsed_time:
        # Не удалось распознать время
        error_text = {
            'ru': f"❌ Не удалось распознать время: '{original_time_text}'\n\n"
                  "Попробуйте другие форматы:\n"
                  "• Завтра 15:30\n"
                  "• 20:00\n"
                  "• Через 2 часа\n"
                  "• 11.01.2024 16:00\n\n"
                  "Или введите /cancel для отмены",
            'en': f"❌ Could not recognize time: '{original_time_text}'\n\n"
                  "Try other formats:\n"
                  "• Tomorrow 3:30 PM\n"
                  "• 8:00 PM\n"
                  "• In 2 hours\n"
                  "• 01/11/2024 4:00 PM\n\n"
                  "Or enter /cancel to cancel"
        }
        
        await message.answer(
            error_text.get(language, error_text['ru']),
            parse_mode="Markdown",
            reply_markup=get_cancel_keyboard(language)
        )
        return
    
    # Проверяем корректность времени
    is_valid, error_msg = time_parser.validate_time(parsed_time)
    if not is_valid:
        error_text = {
            'ru': f"❌ {error_msg}\n\nВведите другое время или /cancel",
            'en': f"❌ {error_msg}\n\nEnter another time or /cancel"
        }
        await message.answer(
            error_text.get(language, error_text['ru']),
            reply_markup=get_cancel_keyboard(language)
        )
        return
    
    # Сохраняем время в состоянии
    await state.update_data(
        parsed_time=parsed_time.isoformat(),
        timezone=timezone,
        parse_type=parse_type
    )
    
    # Показываем пользователю, какое время распознано
    formatted_time = format_local_time(parsed_time, timezone, language)
    
    # Проверяем, есть ли предзаполненный текст
    user_data = await state.get_data()
    prefill_text = user_data.get('prefill_text')
    
    if prefill_text:
        # Есть предзаполненный текст - сразу спрашиваем про повторения
        await ask_for_repeat_type(message, parsed_time, prefill_text, timezone, language)
        # Очищаем prefill_text чтобы не мешал
        await state.update_data(prefill_text=None)
    else:
        # Нет предзаполненного текста - запрашиваем текст
        confirm_text = {
            'ru': f"✅ *Время подтверждено:* {formatted_time}\n\n"
                  "📝 *Теперь введите текст напоминания:*\n\n"
                  "Или введите /cancel для отмены",
            
            'en': f"✅ *Time confirmed:* {formatted_time}\n\n"
                  "📝 *Now enter the reminder text:*\n\n"
                  "Or enter /cancel to cancel"
        }
        
        await message.answer(
            confirm_text.get(language, confirm_text['ru']),
            parse_mode="Markdown",
            reply_markup=get_cancel_keyboard(language)
        )
        
        await state.set_state(ReminderState.waiting_for_text)

@dp.message(ReminderState.waiting_for_text)
async def process_reminder_text(message: types.Message, state: FSMContext):
    """Обработка текста напоминания"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    language = user.get('language_code', 'ru')
    
    # Проверяем отмену
    cancel_texts = ["❌ отмена", "❌ cancel", "отмена", "cancel", "/cancel"]
    if message.text.lower() in [ct.lower() for ct in cancel_texts]:
        await handle_cancel(message, state, language)
        return
    
    user_data = await state.get_data()
    
    # Проверяем, есть ли предзаполненный текст
    prefill_text = user_data.get('prefill_text')
    
    if prefill_text and message.text.strip().lower() in ['да', 'yes', 'ок', 'ok', '✅']:
        # Пользователь подтвердил использование предзаполненного текста
        text = prefill_text
        await state.update_data(prefill_text=None)  # Очищаем
    else:
        # Используем введенный текст (или предзаполненный если это не подтверждение)
        if prefill_text:
            text = prefill_text
            await state.update_data(prefill_text=None)
        else:
            text = message.text.strip()
    
    # Проверяем, пришли ли мы из /quick команды
    if 'quick_time' in user_data:
        # Это /quick режим - время уже есть, парсим его
        timezone = user_data.get('timezone', 'Europe/Moscow')
        language = user_data.get('language_code', 'ru')
        time_part = user_data['quick_time']
        
        parsed_time, parse_type, extra_info = time_parser.parse(time_part, language, timezone)
        
        if parsed_time:
            await state.update_data(
                text=text,
                parsed_time=parsed_time.isoformat(),
                quick_time=None  # Удаляем временный ключ
            )
            
            # Переходим к выбору повторения
            await ask_for_repeat_type(message, parsed_time, text, timezone, language)
        else:
            # Ошибка парсинга
            error_text = {
                'ru': f"❌ Ошибка: не удалось распознать время '{time_part}'",
                'en': f"❌ Error: could not recognize time '{time_part}'"
            }
            await message.answer(error_text.get(language, error_text['ru']))
            await state.clear()
        return
    
    # Обычный режим /add или умное создание
    if not text or len(text) < 2:
        error_text = {
            'ru': "❌ Текст напоминания слишком короткий. Введите снова:",
            'en': "❌ Reminder text is too short. Enter again:"
        }
        await message.answer(error_text.get(language, error_text['ru']))
        return
    
    # Проверяем максимальную длину
    if len(text) > Config.MAX_TEXT_LENGTH:
        error_text = {
            'ru': f"❌ Текст слишком длинный (макс. {Config.MAX_TEXT_LENGTH} символов)",
            'en': f"❌ Text too long (max {Config.MAX_TEXT_LENGTH} characters)"
        }
        await message.answer(error_text.get(language, error_text['ru']))
        return
    
    # Сохраняем текст (если еще не сохранен)
    if 'text' not in user_data:
        await state.update_data(text=text)
    
    # Получаем данные из состояния
    user_data = await state.get_data()
    parsed_time_str = user_data.get('parsed_time')
    timezone = user_data.get('timezone', 'Europe/Moscow')
    
    if parsed_time_str:
        parsed_time = datetime.fromisoformat(parsed_time_str)
        
        # Показываем подтверждение и спрашиваем про повторения
        await ask_for_repeat_type(message, parsed_time, text, timezone, language)
    else:
        # Нет времени в состоянии - ошибка
        error_text = {
            'ru': "❌ Ошибка: время не найдено. Начните заново с /add",
            'en': "❌ Error: time not found. Start over with /add"
        }
        await message.answer(error_text.get(language, error_text['ru']))
        await state.clear()

# ===== ОБРАБОТКА КНОПКИ НАСТРОЕК =====

@dp.message(F.text.in_(["⚙️ Настройки", "⚙️ Settings"]))
async def cmd_settings_button(message: types.Message):
    """Обработка кнопки настроек"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    
    settings_text = {
        'ru': "⚙️ *Настройки*\n\n"
              "Выберите опцию:\n"
              "/language - Сменить язык\n"
              "/timezone - Установить часовой пояс\n"
              "/stats - Статистика\n\n"
              "Текущие настройки:\n"
              f"🌐 Язык: {'Русский' if language == 'ru' else 'English'}\n"
              f"🕒 Часовой пояс: {user.get('timezone', 'Europe/Moscow')}",
        'en': "⚙️ *Settings*\n\n"
              "Choose an option:\n"
              "/language - Change language\n"
              "/timezone - Set timezone\n"
              "/stats - Statistics\n\n"
              "Current settings:\n"
              f"🌐 Language: {'Russian' if language == 'ru' else 'English'}\n"
              f"🕒 Timezone: {user.get('timezone', 'Europe/Moscow')}"
    }
    
    await message.answer(
        settings_text.get(language, settings_text['en']),
        parse_mode="Markdown"
    )

@dp.message(Command("language"))
async def cmd_language(message: types.Message, state: FSMContext):
    """Смена языка"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    
    text = {
        'ru': "🌐 *Выберите язык:*",
        'en': "🌐 *Select language:*"
    }
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru"),
        InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")
    )
    builder.row(
        InlineKeyboardButton(
            text="❌ Отмена" if language == 'ru' else "❌ Cancel",
            callback_data="lang_cancel"
        )
    )
    
    await message.answer(
        text.get(language, text['ru']),
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("set_lang_"))
async def handle_language_selection(callback: types.CallbackQuery):
    """Обработка выбора языка"""
    user_id = callback.from_user.id
    language_code = callback.data.replace("set_lang_", "")
    
    # Обновляем язык пользователя
    db.update_user_language(user_id, language_code)
    
    success_text = {
        'ru': "✅ Язык изменен на русский!",
        'en': "✅ Language changed to English!"
    }
    
    await callback.message.edit_text(
        success_text.get(language_code, success_text['ru'])
    )
    
    # Обновляем главное меню
    await callback.message.answer(
        "Меню:" if language_code == 'ru' else "Menu:",
        reply_markup=get_main_keyboard(language_code)
    )
    
    await callback.answer()

@dp.message(Command("timezone"))
async def cmd_timezone(message: types.Message, state: FSMContext):
    """Смена часового пояса"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    
    instruction = {
        'ru': "🕒 *Установите ваш часовой пояс*\n\n"
              "Введите название часового пояса, например:\n"
              "• Europe/Moscow\n"
              "• America/New_York\n"
              "• Asia/Tokyo\n\n"
              "Или введите /cancel для отмены",
        'en': "🕒 *Set your timezone*\n\n"
              "Enter timezone name, for example:\n"
              "• Europe/Moscow\n"
              "• America/New_York\n"
              "• Asia/Tokyo\n\n"
              "Or enter /cancel to cancel"
    }
    
    await message.answer(
        instruction.get(language, instruction['ru']),
        parse_mode="Markdown",
        reply_markup=get_cancel_keyboard(language)
    )
    
    await state.set_state(SettingsState.waiting_for_timezone)

@dp.message(SettingsState.waiting_for_timezone)
async def process_timezone(message: types.Message, state: FSMContext):
    """Обработка ввода часового пояса"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    language = user.get('language_code', 'ru') if user else 'ru'
    
    # Проверяем отмену
    cancel_texts = ["❌ отмена", "❌ cancel", "отмена", "cancel", "/cancel"]
    if message.text.lower() in [ct.lower() for ct in cancel_texts]:
        await state.clear()
        cancel_text = {
            'ru': "❌ Смена часового пояса отменена.",
            'en': "❌ Timezone change cancelled."
        }
        await message.answer(
            cancel_text.get(language, cancel_text['ru']),
            reply_markup=get_main_keyboard(language)
        )
        return
    
    timezone_input = message.text.strip()
    
    # Проверяем валидность часового пояса
    try:
        
        tz = pytz.timezone(timezone_input)
        
        # Обновляем часовой пояс пользователя
        db.update_user_timezone(user_id, timezone_input)
        
        success_text = {
            'ru': f"✅ Часовой пояс изменен на: {timezone_input}\n\n"
                  f"🕒 Текущее время: {datetime.now(tz).strftime('%H:%M:%S')}",
            'en': f"✅ Timezone changed to: {timezone_input}\n\n"
                  f"🕒 Current time: {datetime.now(tz).strftime('%I:%M:%S %p')}"
        }
        
        await message.answer(
            success_text.get(language, success_text['ru'])
        )
        
    except pytz.exceptions.UnknownTimeZoneError:
        error_text = {
            'ru': f"❌ Неизвестный часовой пояс: {timezone_input}\n\n"
                  "Попробуйте другой, например:\n"
                  "• Europe/Moscow\n"
                  "• America/New_York\n"
                  "• Asia/Tokyo\n"
                  "• UTC",
            'en': f"❌ Unknown timezone: {timezone_input}\n\n"
                  "Try another one, for example:\n"
                  "• Europe/Moscow\n"
                  "• America/New_York\n"
                  "• Asia/Tokyo\n"
                  "• UTC"
        }
        
        await message.answer(
            error_text.get(language, error_text['ru']),
            reply_markup=get_cancel_keyboard(language)
        )
        return
    except Exception as e:
        error_text = {
            'ru': f"❌ Ошибка при смене часового пояса: {e}",
            'en': f"❌ Error changing timezone: {e}"
        }
        await message.answer(error_text.get(language, error_text['ru']))
    
    await state.clear()

# ===== АДМИН-КОМАНДЫ =====

@dp.message(Command("admin"))
@dp.message(F.text.in_(["👑 Админ-панель", "👑 Admin Panel"]))
async def cmd_admin(message: types.Message):
    """Админ-панель"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав администратора.")
        return
    
    user = db.get_user(message.from_user.id)
    language = user.get('language_code', 'ru') if user else 'ru'
    
    admin_text = {
        'ru': """👑 *Админ-панель Reminder Pro*

📊 *Статистика и мониторинг:*
/stats - Общая статистика бота
/users - Список пользователей
/logs - Просмотр логов
/analytics - Аналитика использования

📢 *Управление:*
/broadcast - Рассылка сообщений
/backup - Создать резервную копию
/cleanup - Очистка старых данных

🔧 *Система:*
/restart - Перезапустить проверку напоминаний
/recover - Восстановить пропущенные
/test - Тестовые команды

💬 *Поиск:*
/find_user <id/name> - Найти пользователя
/find_reminder <id> - Найти напоминание

🛠 *Настройки:*
/set_limit <число> - Установить лимит напоминаний
/set_timezone <часовой пояс> - Тест таймзоны""",
        
        'en': """👑 *Admin Panel Reminder Pro*

📊 *Statistics & Monitoring:*
/stats - Bot statistics
/users - User list
/logs - View logs
/analytics - Usage analytics

📢 *Management:*
/broadcast - Send broadcast
/backup - Create backup
/cleanup - Clean old data

🔧 *System:*
/restart - Restart reminder check
/recover - Recover missed reminders
/test - Test commands

💬 *Search:*
/find_user <id/name> - Find user
/find_reminder <id> - Find reminder

🛠 *Settings:*
/set_limit <number> - Set reminder limit
/set_timezone <timezone> - Test timezone"""
    }
    
    # Создаем админ-клавиатуру
    builder = InlineKeyboardBuilder()
    
    if language == 'ru':
        builder.row(
            InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
            InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users"),
        )
        builder.row(
            InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
            InlineKeyboardButton(text="💾 Бэкап", callback_data="admin_backup"),
        )
        builder.row(
            InlineKeyboardButton(text="📋 Логи", callback_data="admin_logs"),
            InlineKeyboardButton(text="🧹 Очистка", callback_data="admin_cleanup"),
        )
        builder.row(
            InlineKeyboardButton(text="🔄 Перезапуск", callback_data="admin_restart"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings"),
        )
    else:
        builder.row(
            InlineKeyboardButton(text="📊 Statistics", callback_data="admin_stats"),
            InlineKeyboardButton(text="👥 Users", callback_data="admin_users"),
        )
        builder.row(
            InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton(text="💾 Backup", callback_data="admin_backup"),
        )
        builder.row(
            InlineKeyboardButton(text="📋 Logs", callback_data="admin_logs"),
            InlineKeyboardButton(text="🧹 Cleanup", callback_data="admin_cleanup"),
        )
        builder.row(
            InlineKeyboardButton(text="🔄 Restart", callback_data="admin_restart"),
            InlineKeyboardButton(text="⚙️ Settings", callback_data="admin_settings"),
        )
    
    await message.answer(
        admin_text.get(language, admin_text['ru']),
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )

@dp.message(Command("stat"))
async def cmd_stat(message: types.Message):
    """Статистика бота (админская)"""
    user_id = message.from_user.id
    logger.info(f"📊 Запрос админской статистики от user_id={user_id}")
    
    # Проверяем права админа вручную
    if not is_admin(user_id):
        logger.warning(f"⛔ Пользователь {user_id} не админ, пытался получить админскую статистику")
        await message.answer("⛔ У вас нет прав администратора.")
        return
    
    await send_admin_stats(user_id, message.chat.id)

@dp.message(Command("users"))
async def cmd_users(message: types.Message):
    """Список пользователей"""
    user_id = message.from_user.id
    logger.info(f"📋 Запрос списка пользователей от user_id={user_id}")
    
    # Проверяем права админа вручную
    if not is_admin(user_id):
        logger.warning(f"⛔ Пользователь {user_id} не админ, пытался получить список пользователей")
        await message.answer("⛔ У вас нет прав администратора.")
        return
    
    await send_users_list(user_id, message.chat.id)
    
# Сохраняем время запуска для статистики
import time
cmd_stat._start_time = time.time()

# Состояния для рассылки
class BroadcastState(StatesGroup):
    waiting_for_message = State()
    waiting_for_confirmation = State()

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, state: FSMContext):
    """Начать рассылку сообщений"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав администратора.")
        return
    
    user = db.get_user(message.from_user.id)
    language = user.get('language_code', 'ru') if user else 'ru'
    
    instruction = {
        'ru': "📢 *Рассылка сообщений*\n\nВведите сообщение для рассылки всем пользователям.\n\nМожно использовать Markdown разметку.\n\nИспользуйте /cancel для отмены.",
        'en': "📢 *Broadcast Message*\n\nEnter message to send to all users.\n\nYou can use Markdown formatting.\n\nUse /cancel to cancel."
    }
    
    await message.answer(
        instruction.get(language, instruction['ru']),
        parse_mode="Markdown"
    )
    await state.set_state(BroadcastState.waiting_for_message)

@dp.message(BroadcastState.waiting_for_message)
async def process_broadcast_message(message: types.Message, state: FSMContext):
    """Обработка сообщения для рассылки"""
    if message.text == '/cancel':
        await state.clear()
        await message.answer("❌ Рассылка отменена.")
        return
    
    # Сохраняем сообщение
    await state.update_data(broadcast_message=message.text, broadcast_mode='text')
    
    user = db.get_user(message.from_user.id)
    language = user.get('language_code', 'ru') if user else 'ru'
    
    # Показываем предварительный просмотр
    preview_text = {
        'ru': f"📋 *Предварительный просмотр:*\n\n{message.text}\n\nОтправить это сообщение всем пользователям?",
        'en': f"📋 *Preview:*\n\n{message.text}\n\nSend this message to all users?"
    }
    
    # Кнопки подтверждения
    builder = InlineKeyboardBuilder()
    if language == 'ru':
        builder.row(
            InlineKeyboardButton(text="✅ Да, отправить", callback_data="broadcast_confirm"),
            InlineKeyboardButton(text="❌ Нет, отменить", callback_data="broadcast_cancel"),
        )
    else:
        builder.row(
            InlineKeyboardButton(text="✅ Yes, send", callback_data="broadcast_confirm"),
            InlineKeyboardButton(text="❌ No, cancel", callback_data="broadcast_cancel"),
        )
    
    await message.answer(
        preview_text.get(language, preview_text['ru']),
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    await state.set_state(BroadcastState.waiting_for_confirmation)

@dp.callback_query(F.data.startswith("broadcast_"))
async def handle_broadcast_confirmation(callback: types.CallbackQuery, state: FSMContext):
    """Обработка подтверждения рассылки"""
    if callback.data == "broadcast_cancel":
        await state.clear()
        await callback.message.edit_text("❌ Рассылка отменена.")
        await callback.answer()
        return
    
    if callback.data == "broadcast_confirm":
        await callback.message.edit_text("🔄 Начинаю рассылку...")
        
        user_data = await state.get_data()
        message_text = user_data.get('broadcast_message', '')
        
        if not message_text:
            await callback.message.edit_text("❌ Ошибка: сообщение не найдено.")
            await state.clear()
            return
        
        # Получаем всех пользователей
        all_users = db.get_all_users(limit=1000)  # Ограничим 1000 пользователей
        
        success_count = 0
        fail_count = 0
        total = len(all_users)
        
        # Отправляем прогресс
        progress_msg = await callback.message.answer(f"📤 Рассылка: 0/{total}")
        
        for i, user in enumerate(all_users, 1):
            try:
                await bot.send_message(
                    user['user_id'],
                    message_text,
                    parse_mode="Markdown"
                )
                success_count += 1
                
                # Обновляем прогресс каждые 10 сообщений
                if i % 10 == 0 or i == total:
                    try:
                        await progress_msg.edit_text(f"📤 Рассылка: {i}/{total} (✓ {success_count} ✗ {fail_count})")
                    except:
                        pass
                
                # Пауза чтобы не превысить лимиты Telegram
                await asyncio.sleep(0.1)
                
            except Exception as e:
                fail_count += 1
                logger.error(f"Failed to send broadcast to {user['user_id']}: {e}")
        
        # Итог
        result_text = f"""✅ *Рассылка завершена*

• Всего пользователей: {total}
• Успешно отправлено: {success_count}
• Не удалось отправить: {fail_count}

📊 Успешных: {success_count/total*100:.1f}%"""
        
        await callback.message.edit_text(result_text, parse_mode="Markdown")
        await state.clear()
        
        # Логируем рассылку
        db.log_event(
            log_type='broadcast',
            user_id=callback.from_user.id,
            message=f"Рассылка сообщения",
            details=f"Отправлено: {success_count}/{total}, текст: {message_text[:100]}..."
        )
        
        await callback.answer()

@dp.message(Command("backup"))
async def cmd_backup(message: types.Message):
    """Создать резервную копию БД"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав администратора.")
        return
    
    try:
        await message.answer("💾 Создаю резервную копию базы данных...")
        
        # Создаем бэкап
        db.backup_database()
        
        # Получаем список бэкапов
        backup_dir = 'backups'
        if os.path.exists(backup_dir):
            backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.db')], reverse=True)
            
            if backups:
                latest = backups[0]
                size = os.path.getsize(os.path.join(backup_dir, latest))
                size_mb = size / 1024 / 1024
                
                text = f"""✅ *Резервная копия создана*

• Файл: `{latest}`
• Размер: {size_mb:.2f} MB
• Всего бэкапов: {len(backups)}

💡 Последние 5 бэкапов:"""
                
                for i, backup in enumerate(backups[:5], 1):
                    backup_time = backup.replace('reminders_backup_', '').replace('.db', '')
                    text += f"\n{i}. {backup_time}"
                
                await message.answer(text, parse_mode="Markdown")
            else:
                await message.answer("✅ Резервная копия создана, но файлы не найдены.")
        else:
            await message.answer("✅ Резервная копия создана.")
            
    except Exception as e:
        logger.error(f"Error creating backup: {e}")
        await message.answer(f"❌ Ошибка создания резервной копии: {e}")

@dp.message(Command("debug_admin"))
async def cmd_debug_admin(message: types.Message):
    """Отладочная команда для проверки админских прав"""
    user_id = message.from_user.id
    
    # Исправляем форматирование - убираем Markdown или экранируем специальные символы
    debug_info = f"""
🔍 *Отладка админских прав*

ID: {user_id}
ADMINS в конфиге: {Config.ADMINS}
Вы в списке ADMINS: {user_id in Config.ADMINS}
Функция is_admin возвращает: {is_admin(user_id)}
    
Проверьте .env файл, там должно быть:
ADMINS={user_id}
    """
    
    # Отправляем без Markdown или исправляем форматирование
    await message.answer(debug_info)  # Убрали parse_mode="Markdown"
    
    # Также проверьте таблицу admins
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM admins WHERE user_id = ?", (user_id,))
        admin_row = cursor.fetchone()
        
        if admin_row:
            await message.answer(f"✅ Найден в таблице admins: {dict(admin_row)}")
        else:
            await message.answer("❌ Не найден в таблице admins")

@dp.callback_query(F.data.startswith("admin_"))
async def handle_admin_buttons(callback: types.CallbackQuery, state: FSMContext):
    """Обработка кнопок админ-панели"""
    user_id = callback.from_user.id
    logger.debug(f"🔍 Проверка админских прав для кнопки: user_id={user_id}, data={callback.data}")
    
    # Сразу отвечаем на callback, чтобы Telegram не показывал "часики"
    await callback.answer()
    
    if not is_admin(user_id):
        logger.warning(f"⛔ Пользователь {user_id} не админ, но пытается использовать админ-кнопку")
        # Ответ уже был отправлен выше, но можно отправить всплывающее сообщение
        await callback.answer("⛔ Нет прав администратора.", show_alert=True)
        return
    
    action = callback.data.replace("admin_", "")
    logger.debug(f"✅ Обработка админ-кнопки: {action} для user_id={user_id}")
    
    user = db.get_user(user_id)
    language = user.get('language_code', 'ru') if user else 'ru'
    
    try:
        if action == "stats":
            # Показываем админскую статистику (команда stat)
            logger.info(f"📊 Админ {user_id} запросил статистику через кнопку")
            await send_admin_stats(user_id, callback.message.chat.id)
            
        elif action == "users":
            # Показываем пользователей
            logger.info(f"👥 Админ {user_id} запросил список пользователей через кнопку")
            await send_users_list(user_id, callback.message.chat.id)
            
        elif action == "broadcast":
            # Запускаем рассылку
            logger.info(f"📢 Админ {user_id} запустил рассылку через кнопку")
            await start_broadcast(user_id, callback.message.chat.id, state)
            
        elif action == "backup":
            # Создаем бэкап
            logger.info(f"💾 Админ {user_id} создал бэкап через кнопку")
            await create_backup(user_id, callback.message.chat.id)
            
        elif action == "logs":
            # Показываем логи (упрощенная версия)
            logger.info(f"📋 Админ {user_id} запросил логи через кнопку")
            await show_logs(callback.message.chat.id)
                
        elif action == "cleanup":
            # Очистка старых данных
            logger.info(f"🧹 Админ {user_id} открыл меню очистки через кнопку")
            await show_cleanup_menu(callback.message, language)
            
        elif action == "restart":
            # Перезапуск проверки напоминаний
            logger.info(f"🔄 Админ {user_id} перезапустил проверку напоминаний через кнопку")
            await restart_reminder_check(callback.message.chat.id)
            
        elif action == "settings":
            # Настройки
            logger.info(f"⚙️ Админ {user_id} запросил настройки через кнопку")
            await show_settings(callback.message.chat.id, language)
            
        elif action == "cancel":
            await callback.message.delete()
            
    except Exception as e:
        logger.error(f"❌ Ошибка обработки админ-кнопки {action}: {e}", exc_info=True)
        await bot.send_message(callback.message.chat.id, f"❌ Ошибка: {e}")

# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ АДМИН-КНОПОК =====

async def send_admin_stats(user_id: int, chat_id: int):
    """Отправить админскую статистику"""
    try:
        # Получаем статистику из БД
        stats = db.get_bot_statistics()
        
        # Получаем системную информацию
        import psutil
        import platform
        
        # Использование памяти
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # Время работы бота
        import time
        start_time = getattr(send_admin_stats, '_start_time', time.time())
        uptime_seconds = time.time() - start_time
        uptime_str = str(timedelta(seconds=int(uptime_seconds)))
        
        user = db.get_user(user_id)
        language = user.get('language_code', 'ru') if user else 'ru'
        
        if language == 'ru':
            stats_text = f"""📊 *Статистика бота (Админ)*

👥 *Пользователи:*
• Всего: {stats.get('total_users', 0)}
• Активных за неделю: {stats.get('active_week', 0)}
• Новых сегодня: {stats.get('new_today', 0)}

🔔 *Напоминания:*
• Всего: {stats.get('total_reminders', 0)}
• Активных: {stats.get('active_reminders', 0)}
• Повторяющихся: {stats.get('repeating_reminders', 0)}
• На паузе: {stats.get('paused_reminders', 0)}
• Создано сегодня: {stats.get('created_today', 0)}

💻 *Система:*
• Время работы: {uptime_str}
• Память: {memory.percent}% ({memory.used//1024//1024}MB/{memory.total//1024//1024}MB)
• Диск: {disk.percent}% ({disk.used//1024//1024}MB/{disk.total//1024//1024}MB)
• ОС: {platform.system()} {platform.release()}

📈 *Лимиты:*
• Макс. напоминаний: {Config.MAX_REMINDERS_PER_USER}
• Часовой пояс по умолчанию: {Config.DEFAULT_TIMEZONE}"""
        else:
            stats_text = f"""📊 *Bot Statistics (Admin)*

👥 *Users:*
• Total: {stats.get('total_users', 0)}
• Active this week: {stats.get('active_week', 0)}
• New today: {stats.get('new_today', 0)}

🔔 *Reminders:*
• Total: {stats.get('total_reminders', 0)}
• Active: {stats.get('active_reminders', 0)}
• Repeating: {stats.get('repeating_reminders', 0)}
• Paused: {stats.get('paused_reminders', 0)}
• Created today: {stats.get('created_today', 0)}

💻 *System:*
• Uptime: {uptime_str}
• Memory: {memory.percent}% ({memory.used//1024//1024}MB/{memory.total//1024//1024}MB)
• Disk: {disk.percent}% ({disk.used//1024//1024}MB/{disk.total//1024//1024}MB)
• OS: {platform.system()} {platform.release()}

📈 *Limits:*
• Max reminders: {Config.MAX_REMINDERS_PER_USER}
• Default timezone: {Config.DEFAULT_TIMEZONE}"""
        
        await bot.send_message(chat_id, stats_text, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error in admin stats: {e}", exc_info=True)
        error_text = {
            'ru': f"❌ Ошибка получения статистики: {e}",
            'en': f"❌ Error getting statistics: {e}"
        }
        user = db.get_user(user_id)
        language = user.get('language_code', 'ru') if user else 'ru'
        await bot.send_message(chat_id, error_text.get(language, error_text['ru']))

# Сохраняем время запуска для статистики
import time
send_admin_stats._start_time = time.time()

async def send_users_list(user_id: int, chat_id: int):
    """Отправить список пользователей"""
    try:
        # Получаем пользователей
        users = db.get_all_users(limit=20)
        
        if not users:
            await bot.send_message(chat_id, "📭 Нет пользователей в базе данных.")
            return
        
        user = db.get_user(user_id)
        language = user.get('language_code', 'ru') if user else 'ru'
        
        # Формируем текст БЕЗ Markdown разметки
        if language == 'ru':
            text = f"👥 Последние 20 пользователей (всего: {len(users)}):\n\n"
            for i, user_data in enumerate(users, 1):
                username = user_data.get('username', '')
                username_display = f"@{username}" if username else "без username"
                
                # Экранируем специальные символы
                first_name = user_data.get('first_name', '')
                first_name = first_name.replace('*', '•').replace('_', ' ')
                
                last_name = user_data.get('last_name', '')
                if last_name:
                    last_name = last_name.replace('*', '•').replace('_', ' ')
                
                reg_date = user_data['registered_at']
                if isinstance(reg_date, str):
                    try:
                        reg_date = datetime.fromisoformat(reg_date)
                    except:
                        pass
                
                if isinstance(reg_date, datetime):
                    reg_str = reg_date.strftime("%d.%m.%Y")
                else:
                    reg_str = str(reg_date)[:10]
                
                text += f"{i}. ID: {user_data['user_id']}\n"
                text += f"   👤 {first_name} {last_name}\n"
                text += f"   📱 {username_display}\n"
                text += f"   🌐 {user_data.get('language_code', 'ru')}\n"
                text += f"   🕒 {user_data.get('timezone', 'UTC')}\n"
                text += f"   📅 Регистрация: {reg_str}\n"
                text += f"   🔔 Напоминаний: {user_data.get('reminder_count', 0)}\n\n"
        else:
            text = f"👥 Last 20 users (total: {len(users)}):\n\n"
            for i, user_data in enumerate(users, 1):
                username = user_data.get('username', '')
                username_display = f"@{username}" if username else "no username"
                
                # Экранируем специальные символы
                first_name = user_data.get('first_name', '')
                first_name = first_name.replace('*', '•').replace('_', ' ')
                
                last_name = user_data.get('last_name', '')
                if last_name:
                    last_name = last_name.replace('*', '•').replace('_', ' ')
                
                reg_date = user_data['registered_at']
                if isinstance(reg_date, str):
                    try:
                        reg_date = datetime.fromisoformat(reg_date)
                    except:
                        pass
                
                if isinstance(reg_date, datetime):
                    reg_str = reg_date.strftime("%b %d, %Y")
                else:
                    reg_str = str(reg_date)[:10]
                
                text += f"{i}. ID: {user_data['user_id']}\n"
                text += f"   👤 {first_name} {last_name}\n"
                text += f"   📱 {username_display}\n"
                text += f"   🌐 {user_data.get('language_code', 'en')}\n"
                text += f"   🕒 {user_data.get('timezone', 'UTC')}\n"
                text += f"   📅 Registered: {reg_str}\n"
                text += f"   🔔 Reminders: {user_data.get('reminder_count', 0)}\n\n"
        
        # Отправляем как обычный текст (без Markdown парсинга)
        await bot.send_message(chat_id, text)
        
    except Exception as e:
        logger.error(f"Error getting users: {e}", exc_info=True)
        await bot.send_message(chat_id, f"❌ Ошибка получения списка пользователей: {e}")

async def start_broadcast(user_id: int, chat_id: int, state: FSMContext):
    """Начать рассылку"""
    # Создаем фиктивное сообщение для запуска рассылки
    from aiogram.types import Message
    fake_message = Message(
        message_id=1,
        date=datetime.now(),
        chat=types.Chat(id=chat_id, type="private"),
        from_user=types.User(id=user_id, is_bot=False, first_name="Admin"),
        text="/broadcast"
    )
    # Привязываем бота к сообщению
    fake_message.bot = bot
    
    await cmd_broadcast(fake_message, state)

async def create_backup(user_id: int, chat_id: int):
    """Создать резервную копию"""
    # Создаем фиктивное сообщение
    from aiogram.types import Message
    fake_message = Message(
        message_id=1,
        date=datetime.now(),
        chat=types.Chat(id=chat_id, type="private"),
        from_user=types.User(id=user_id, is_bot=False, first_name="Admin"),
        text="/backup"
    )
    fake_message.bot = bot
    
    await cmd_backup(fake_message)

async def show_logs(chat_id: int):
    """Показать логи"""
    try:
        if os.path.exists(Config.LOG_FILE):
            with open(Config.LOG_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()[-50:]  # Последние 50 строк
            
            log_text = "".join(lines[-20:])  # Показываем последние 20 строк
            
            if len(log_text) > 4000:
                log_text = log_text[-4000:]
            
            text = f"📋 Последние логи:\n```\n{log_text}\n```"
            await bot.send_message(chat_id, text)
        else:
            await bot.send_message(chat_id, "📭 Файл логов не найден.")
    except Exception as e:
        await bot.send_message(chat_id, f"❌ Ошибка чтения логов: {e}")

async def show_cleanup_menu(message: types.Message, language: str):
    """Показать меню очистки"""
    builder = InlineKeyboardBuilder()
    if language == 'ru':
        builder.row(
            InlineKeyboardButton(text="🗑️ Удалить старые напоминания", callback_data="cleanup_old"),
            InlineKeyboardButton(text="🧹 Очистить логи", callback_data="cleanup_logs"),
        )
        builder.row(
            InlineKeyboardButton(text="📋 Показать размер БД", callback_data="cleanup_stats"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel"),
        )
    else:
        builder.row(
            InlineKeyboardButton(text="🗑️ Delete old reminders", callback_data="cleanup_old"),
            InlineKeyboardButton(text="🧹 Clean logs", callback_data="cleanup_logs"),
        )
        builder.row(
            InlineKeyboardButton(text="📋 Show DB size", callback_data="cleanup_stats"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="admin_cancel"),
        )
    
    text = {
        'ru': "🧹 Очистка данных\n\nВыберите действие:",
        'en': "🧹 Data Cleanup\n\nSelect action:"
    }
    
    await message.edit_text(
        text.get(language, text['ru']),
        reply_markup=builder.as_markup()
    )

async def restart_reminder_check(chat_id: int):
    """Перезапустить проверку напоминаний"""
    await bot.send_message(chat_id, "🔄 Перезапускаю проверку напоминаний...")
    await check_and_send_reminders()
    await bot.send_message(chat_id, "✅ Проверка напоминаний завершена.")

async def show_settings(chat_id: int, language: str):
    """Показать настройки"""
    text = {
        'ru': f"""⚙️ Настройки бота

• Макс. напоминаний на пользователя: {Config.MAX_REMINDERS_PER_USER}
• Часовой пояс по умолчанию: {Config.DEFAULT_TIMEZONE}
• Уровень логов: {Config.LOG_LEVEL}
• Проверка каждые: {Config.CHECK_INTERVAL_MINUTES} мин.
• Режим отладки: {'ВКЛ' if Config.DEBUG else 'ВЫКЛ'}

Команды для изменения:
/set_limit <число> - изменить лимит
/set_timezone <tz> - изменить часовой пояс
/set_loglevel <level> - изменить уровень логов""",
        'en': f"""⚙️ Bot Settings

• Max reminders per user: {Config.MAX_REMINDERS_PER_USER}
• Default timezone: {Config.DEFAULT_TIMEZONE}
• Log level: {Config.LOG_LEVEL}
• Check interval: {Config.CHECK_INTERVAL_MINUTES} min.
• Debug mode: {'ON' if Config.DEBUG else 'OFF'}

Commands to change:
/set_limit <number> - change limit
/set_timezone <tz> - change timezone
/set_loglevel <level> - change log level"""
    }
    
    await bot.send_message(chat_id, text.get(language, text['ru']))

@dp.message(Command("find_user"))
async def cmd_find_user(message: types.Message):
    """Найти пользователя по ID или имени"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав администратора.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /find_user <ID или имя>")
        return
    
    search_term = args[1]
    
    try:
        # Пробуем найти по ID
        if search_term.isdigit():
            user_id = int(search_term)
            user = db.get_user(user_id)
            
            if user:
                await show_user_info(message, user)
                return
        
        # Ищем по имени или username
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM users 
                WHERE username LIKE ? OR first_name LIKE ? OR last_name LIKE ?
                LIMIT 10
            ''', (f'%{search_term}%', f'%{search_term}%', f'%{search_term}%'))
            
            users = cursor.fetchall()
            
            if not users:
                await message.answer(f"🔍 Пользователи по запросу '{search_term}' не найдены.")
                return
            
            if len(users) == 1:
                await show_user_info(message, dict(users[0]))
            else:
                text = f"🔍 *Найдено пользователей: {len(users)}*\n\n"
                for i, user_row in enumerate(users, 1):
                    user = dict(user_row)
                    text += f"{i}. ID: {user['user_id']} - {user['first_name']} {user.get('last_name', '')}"
                    if user['username']:
                        text += f" (@{user['username']})"
                    text += f"\n   Напоминаний: {user.get('reminder_count', 0)}\n\n"
                
                await message.answer(text, parse_mode="Markdown")
                
    except Exception as e:
        logger.error(f"Error finding user: {e}")
        await message.answer(f"❌ Ошибка поиска пользователя: {e}")

async def show_user_info(message: types.Message, user: dict):
    """Показать информацию о пользователе"""
    user_id = user['user_id']
    
    # Получаем напоминания пользователя
    reminders = db.get_user_reminders(user_id, active_only=True)
    all_reminders = db.get_user_reminders(user_id, active_only=False)
    
    # Форматируем дату регистрации
    reg_date = user['registered_at']
    if isinstance(reg_date, str):
        try:
            reg_date = datetime.fromisoformat(reg_date)
        except:
            pass
    
    if isinstance(reg_date, datetime):
        reg_str = reg_date.strftime("%d.%m.%Y %H:%M")
    else:
        reg_str = str(reg_date)
    
    text = f"""👤 *Информация о пользователе*

*ID:* {user_id}
*Имя:* {user['first_name']} {user.get('last_name', '')}
*Username:* @{user['username'] if user['username'] else 'нет'}
*Язык:* {user.get('language_code', 'ru')}
*Часовой пояс:* {user.get('timezone', 'UTC')}

*Статистика:*
• Напоминаний всего: {len(all_reminders)}
• Активных: {len(reminders)}
• На паузе: {sum(1 for r in all_reminders if r.get('is_paused'))}
• Выполнено: {len(all_reminders) - len(reminders)}

*Регистрация:* {reg_str}
*Последняя активность:* {user.get('last_active', 'неизвестно')}"""

    # Кнопки действий
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Напоминания пользователя", callback_data=f"user_reminders_{user_id}"),
        InlineKeyboardButton(text="📢 Отправить сообщение", callback_data=f"user_message_{user_id}"),
    )
    
    await message.answer(text, parse_mode="Markdown", reply_markup=builder.as_markup())

# ===== НОВАЯ ЛОГИКА СОЗДАНИЯ НАПОМИНАНИЙ (время → текст → повторение) =====

# ===== УМНОЕ СОЗДАНИЕ НАПОМИНАНИЙ (без команд) =====

# ===== УМНОЕ СОЗДАНИЕ НАПОМИНАНИЙ (без команд) =====

@dp.message()
async def handle_all_messages(message: types.Message, state: FSMContext):
    """Обработка всех сообщений с правильным порядком"""
    # Сначала проверяем, не команда ли это
    if message.text and message.text.startswith('/'):
        return  # Команды обработаются другими хендлерами
    
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        return  # Пользователь не зарегистрирован
    
    # Проверяем, не в состоянии ли мы уже
    current_state = await state.get_state()
    if current_state:
        return  # Уже в процессе - пропускаем
    
    language = user.get('language_code', 'ru')
    
    # Проверяем, не кнопка ли это главного меню
    menu_buttons_ru = [
        "➕ Добавить напоминание",
        "📋 Мои напоминания",
        "📅 На сегодня",
        "📆 На завтра",
        "⚙️ Настройки",
        "❓ Помощь",
        "❌ Отмена"
    ]
    
    menu_buttons_en = [
        "➕ Add reminder",
        "📋 My reminders",
        "📅 For today",
        "📆 For tomorrow",
        "⚙️ Settings",
        "❓ Help",
        "❌ Cancel"
    ]
    
    all_menu_buttons = menu_buttons_ru + menu_buttons_en
    
    if message.text in all_menu_buttons:
        return  # Это кнопка - пропускаем, ее обработают другие хендлеры
    
    # Теперь проверяем, не хочет ли пользователь создать напоминание
    text = message.text.strip()
    
    if len(text) < 3:
        return  # Слишком короткое сообщение
    
    timezone = user.get('timezone', 'Europe/Moscow')
    
    # Пробуем распознать время в сообщении
    time_part, text_part = time_parser.extract_best_time_and_text(text, language)
    
    if not time_part:
        # Не нашли время - возможно пользователь просто написал текст
        # Спрашиваем, хочет ли он создать напоминание
        ask_text = {
            'ru': f"📝 *'{text[:50]}...'*\n\n"
                  "Хотите создать напоминание с этим текстом?\n"
                  "Введите время для напоминания или /cancel",
            'en': f"📝 *'{text[:50]}...'*\n\n"
                  "Do you want to create a reminder with this text?\n"
                  "Enter time for reminder or /cancel"
        }
        
        await state.update_data(
            prefill_text=text,
            timezone=timezone,
            language_code=language
        )
        
        await message.answer(
            ask_text.get(language, ask_text['ru']),
            parse_mode="Markdown",
            reply_markup=get_cancel_keyboard(language)
        )
        
        await state.set_state(ReminderState.waiting_for_time)
        return
    
    # Нашли время в сообщении
    parsed_time, parse_type, extra_info = time_parser.parse(time_part, language, timezone)
    
    if not parsed_time:
        # Не удалось распознать время
        return
    
    if text_part:
        # Есть и время, и текст - показываем подтверждение
        await ask_for_repeat_type(message, parsed_time, text_part, timezone, language)
        
        # Сохраняем в состоянии
        await state.update_data(
            parsed_time=parsed_time.isoformat(),
            timezone=timezone,
            text=text_part
        )
    else:
        # Есть только время - запрашиваем текст
        formatted_time = format_local_time(parsed_time, timezone, language)
        
        request_text = {
            'ru': f"🕐 *Время распознано:* {formatted_time}\n\n"
                  "📝 *Введите текст напоминания:*",
            'en': f"🕐 *Time recognized:* {formatted_time}\n\n"
                  "📝 *Enter reminder text:*"
        }
        
        await state.update_data(
            parsed_time=parsed_time.isoformat(),
            timezone=timezone,
            parse_type=parse_type
        )
        
        await message.answer(
            request_text.get(language, request_text['ru']),
            parse_mode="Markdown",
            reply_markup=get_cancel_keyboard(language)
        )
        
        await state.set_state(ReminderState.waiting_for_text)






async def ask_for_repeat_type(message: types.Message, parsed_time: datetime, 
                             text: str, timezone: str, language: str):
    """Спросить тип повторения"""
    formatted_time = format_local_time(parsed_time, timezone, language)
    
    confirm_text = {
        'ru': f"📝 *Текст:* {text}\n"
              f"⏰ *Время:* {formatted_time}\n\n"
              "Это повторяющееся напоминание?",
        'en': f"📝 *Text:* {text}\n"
              f"⏰ *Time:* {formatted_time}\n\n"
              "Is this a repeating reminder?"
    }
    
    builder = InlineKeyboardBuilder()
    
    if language == 'ru':
        builder.row(
            InlineKeyboardButton(text="✅ Разовое", callback_data="repeat_once"),
            InlineKeyboardButton(text="🔄 Ежедневное", callback_data="repeat_daily"),
        )
        builder.row(
            InlineKeyboardButton(text="📅 Еженедельное", callback_data="repeat_weekly"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="repeat_cancel")
        )
    else:
        builder.row(
            InlineKeyboardButton(text="✅ One-time", callback_data="repeat_once"),
            InlineKeyboardButton(text="🔄 Daily", callback_data="repeat_daily"),
        )
        builder.row(
            InlineKeyboardButton(text="📅 Weekly", callback_data="repeat_weekly"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="repeat_cancel")
        )
    
    await message.answer(
        confirm_text.get(language, confirm_text['ru']),
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )

# ===== ОБРАБОТКА CALLBACK'ОВ ДЛЯ ПОВТОРЕНИЙ =====

@dp.callback_query(F.data.startswith("repeat_"))
async def handle_repeat_type(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора типа повторения"""
    user_id = callback.from_user.id
    user = db.get_user(user_id)
    language = user.get('language_code', 'ru')
    
    if callback.data == "repeat_cancel":
        # Отмена
        await state.clear()
        cancel_text = {
            'ru': "❌ Создание напоминания отменено",
            'en': "❌ Reminder creation cancelled"
        }
        await callback.message.edit_text(
            cancel_text.get(language, cancel_text['ru'])
        )
        await callback.message.answer(
            "Меню:" if language == 'ru' else "Menu:",
            reply_markup=get_main_keyboard(language)
        )
        await callback.answer()
        return
    
    # Получаем данные из состояния
    user_data = await state.get_data()
    text = user_data.get('text', '')
    parsed_time_str = user_data.get('parsed_time')
    timezone = user_data.get('timezone', 'Europe/Moscow')
    
    if not parsed_time_str:
        await callback.answer("Ошибка: время не найдено", show_alert=True)
        return
    
    parsed_time = datetime.fromisoformat(parsed_time_str)
    
    # Определяем тип повторения
    repeat_type = callback.data.replace("repeat_", "")
    
    if repeat_type == "once":
        # Разовое напоминание - сразу создаем
        await create_reminder(
            user_id, text, parsed_time, timezone,
            repeat_type='once', repeat_days=None,
            callback=callback, language=language
        )
        await state.clear()
        
    elif repeat_type == "daily":
        # Ежедневное - сразу создаем
        await create_reminder(
            user_id, text, parsed_time, timezone,
            repeat_type='daily', repeat_days=None,
            callback=callback, language=language
        )
        await state.clear()
        
    elif repeat_type == "weekly":
        # Еженедельное - нужно выбрать дни недели
        await ask_for_weekdays(callback.message, language, state)
        await callback.answer()

async def ask_for_weekdays(message: types.Message, language: str, state: FSMContext):
    """Запросить выбор дней недели для еженедельного напоминания"""
    weekdays_ru = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    weekdays_en = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    
    weekdays = weekdays_ru if language == 'ru' else weekdays_en
    
    builder = InlineKeyboardBuilder()
    
    # Дни недели (пока не выбраны)
    for i, day in enumerate(weekdays):
        builder.add(InlineKeyboardButton(
            text=f"□ {day}", 
            callback_data=f"weekly_day_{i}"
        ))
    
    builder.adjust(4, 3)
    
    # Кнопки действий
    action_row = []
    if language == 'ru':
        action_row.extend([
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="weekly_confirm"),
            InlineKeyboardButton(text="📅 Все дни", callback_data="weekly_all"),
            InlineKeyboardButton(text="📅 Будни", callback_data="weekly_workdays"),
        ])
    else:
        action_row.extend([
            InlineKeyboardButton(text="✅ Confirm", callback_data="weekly_confirm"),
            InlineKeyboardButton(text="📅 All days", callback_data="weekly_all"),
            InlineKeyboardButton(text="📅 Weekdays", callback_data="weekly_workdays"),
        ])
    
    builder.row(*action_row)
    
    builder.row(
        InlineKeyboardButton(
            text="❌ Отмена" if language == 'ru' else "❌ Cancel",
            callback_data="weekly_cancel"
        )
    )
    
    question_text = {
        'ru': "📅 *Выберите дни недели для повторения:*\n\n"
              "Нажмите на день, чтобы выбрать/отменить.",
        'en': "📅 *Select weekdays for repetition:*\n\n"
              "Click on a day to select/deselect."
    }
    
    await message.answer(
        question_text.get(language, question_text['ru']),
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data.startswith("weekly_"))
async def handle_weekly_selection(callback: types.CallbackQuery, state: FSMContext):
    """Обработка выбора дней недели"""
    user_id = callback.from_user.id
    user = db.get_user(user_id)
    language = user.get('language_code', 'ru')
    
    data = callback.data
    
    if data == "weekly_cancel":
        # Отмена
        await state.clear()
        cancel_text = {
            'ru': "❌ Создание напоминания отменено",
            'en': "❌ Reminder creation cancelled"
        }
        await callback.message.edit_text(
            cancel_text.get(language, cancel_text['ru'])
        )
        await callback.message.answer(
            "Меню:" if language == 'ru' else "Menu:",
            reply_markup=get_main_keyboard(language)
        )
        await callback.answer()
        return
    
    # Получаем текущий выбор из состояния
    user_data = await state.get_data()
    selected_days = user_data.get('weekly_days', [])
    
    if data.startswith("weekly_day_"):
        # Выбор/отмена дня
        day_index = int(data.split("_")[2])
        
        if day_index in selected_days:
            selected_days.remove(day_index)
        else:
            selected_days.append(day_index)
        
        selected_days.sort()
        await state.update_data(weekly_days=selected_days)
        
        # Обновляем клавиатуру
        await update_weekly_keyboard(callback.message, selected_days, language)
        await callback.answer()
        
    elif data == "weekly_all":
        # Выбрать все дни
        selected_days = list(range(7))
        await state.update_data(weekly_days=selected_days)
        await update_weekly_keyboard(callback.message, selected_days, language)
        await callback.answer("Все дни выбраны")
        
    elif data == "weekly_workdays":
        # Выбрать будни (пн-пт)
        selected_days = list(range(5))  # 0-4 = Пн-Пт
        await state.update_data(weekly_days=selected_days)
        await update_weekly_keyboard(callback.message, selected_days, language)
        await callback.answer("Будни выбраны" if language == 'ru' else "Weekdays selected")
        
    elif data == "weekly_confirm":
        # Подтверждение выбора дней
        if not selected_days:
            error_text = {
                'ru': "❌ Нужно выбрать хотя бы один день недели!",
                'en': "❌ Need to select at least one weekday!"
            }
            await callback.answer(
                error_text.get(language, error_text['ru']),
                show_alert=True
            )
            return
        
        # Создаем напоминание
        user_data = await state.get_data()
        text = user_data.get('text', '')
        parsed_time_str = user_data.get('parsed_time')
        timezone = user_data.get('timezone', 'Europe/Moscow')
        
        if not parsed_time_str:
            await callback.answer("Ошибка: время не найдено", show_alert=True)
            return
        
        parsed_time = datetime.fromisoformat(parsed_time_str)
        
        # Преобразуем список дней в строку
        repeat_days = ",".join(str(day) for day in selected_days)
        
        await create_reminder(
            user_id, text, parsed_time, timezone,
            repeat_type='weekly', repeat_days=repeat_days,
            callback=callback, language=language
        )
        
        await state.clear()

async def update_weekly_keyboard(message: types.Message, selected_days: list, language: str):
    """Обновить клавиатуру выбора дней недели"""
    weekdays_ru = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    weekdays_en = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    
    weekdays = weekdays_ru if language == 'ru' else weekdays_en
    
    builder = InlineKeyboardBuilder()
    
    # Обновленные дни недели
    for i, day in enumerate(weekdays):
        if i in selected_days:
            builder.add(InlineKeyboardButton(
                text=f"✅ {day}", 
                callback_data=f"weekly_day_{i}"
            ))
        else:
            builder.add(InlineKeyboardButton(
                text=f"□ {day}", 
                callback_data=f"weekly_day_{i}"
            ))
    
    builder.adjust(4, 3)
    
    # Кнопки действий
    action_row = []
    if language == 'ru':
        action_row.extend([
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="weekly_confirm"),
            InlineKeyboardButton(text="📅 Все дни", callback_data="weekly_all"),
            InlineKeyboardButton(text="📅 Будни", callback_data="weekly_workdays"),
        ])
    else:
        action_row.extend([
            InlineKeyboardButton(text="✅ Confirm", callback_data="weekly_confirm"),
            InlineKeyboardButton(text="📅 All days", callback_data="weekly_all"),
            InlineKeyboardButton(text="📅 Weekdays", callback_data="weekly_workdays"),
        ])
    
    builder.row(*action_row)
    
    builder.row(
        InlineKeyboardButton(
            text="❌ Отмена" if language == 'ru' else "❌ Cancel",
            callback_data="weekly_cancel"
        )
    )
    
    # Обновляем сообщение
    question_text = {
        'ru': f"📅 *Выбрано дней: {len(selected_days)}*\n\n"
              "Нажмите на день, чтобы выбрать/отменить.",
        'en': f"📅 *Selected days: {len(selected_days)}*\n\n"
              "Click on a day to select/deselect."
    }
    
    await message.edit_text(
        question_text.get(language, question_text['ru']),
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )

async def create_reminder(user_id: int, text: str, parsed_time: datetime, 
                         timezone: str, repeat_type: str, repeat_days: str,
                         callback: types.CallbackQuery, language: str):
    """Создать напоминание в БД"""
    try:
        # ВАЖНО: parsed_time уже в правильном часовом поясе пользователя
        # Нужно конвертировать в UTC для хранения
        
        # Создаем часовой пояс пользователя
        user_tz = pytz.timezone(timezone)
        
        # Делаем время aware (с часовым поясом)
        if parsed_time.tzinfo is None:
            # Если время naive, добавляем часовой пояс пользователя
            parsed_time = user_tz.localize(parsed_time)
        else:
            # Если уже есть часовой пояс, конвертируем в часовой пояс пользователя
            parsed_time = parsed_time.astimezone(user_tz)
        
        # ✅ ОБНУЛЯЕМ МИКРОСЕКУНДЫ И СЕКУНДЫ
        # Приводим к целым минутам
        parsed_time = parsed_time.replace(second=0, microsecond=0)
        
        # Конвертируем в UTC
        utc_time = parsed_time.astimezone(pytz.UTC)
        
        # ВАЖНОЕ ОТЛАДОЧНОЕ ЛОГИРОВАНИЕ
        logger.info("=" * 50)
        logger.info("🔍 ОТЛАДКА СОЗДАНИЯ НАПОМИНАНИЯ")
        logger.info(f"  Пользователь: {user_id}")
        logger.info(f"  Текст: {text}")
        logger.info(f"  Часовой пояс пользователя: {timezone}")
        logger.info(f"  Исходное время (parsed_time): {parsed_time}")
        logger.info(f"  Тип parsed_time.tzinfo: {type(parsed_time.tzinfo)}")
        logger.info(f"  UTC время: {utc_time}")
        logger.info(f"  Разница во времени: {(parsed_time - utc_time).total_seconds()/60} минут")
        logger.info(f"  parsed_time.hour: {parsed_time.hour}, parsed_time.minute: {parsed_time.minute}")
        logger.info(f"  utc_time.hour: {utc_time.hour}, utc_time.minute: {utc_time.minute}")
        logger.info("=" * 50)
        
        # Для тестирования: если время в прошлом, добавляем 1 минуту
        now_utc = datetime.now(pytz.UTC).replace(second=0, microsecond=0)
        if utc_time < now_utc and repeat_type == 'once':
            # Для разовых напоминаний в прошлом - добавляем минуту для теста
            utc_time = now_utc + timedelta(minutes=1)
            logger.info(f"  Время в прошлом, смещаем на: {utc_time}")
        
        # Добавляем напоминание в БД
        reminder_id = db.add_reminder(
            user_id=user_id,
            text=text,
            remind_time_utc=utc_time,
            repeat_type=repeat_type,
            repeat_days=repeat_days,
            timezone=timezone
        )
        
        # Форматируем для вывода (в местном времени пользователя)
        formatted_time = format_local_time(parsed_time, timezone, language)
        
        # Текст подтверждения
        if repeat_type == 'once':
            repeat_text = {
                'ru': "✅ Разовое",
                'en': "✅ One-time"
            }.get(language, "✅ One-time")
        elif repeat_type == 'daily':
            repeat_text = {
                'ru': "🔄 Ежедневное",
                'en': "🔄 Daily"
            }.get(language, "🔄 Daily")
        elif repeat_type == 'weekly':
            # Форматируем дни недели
            days_list = [int(d) for d in repeat_days.split(',')] if repeat_days else []
            weekdays_ru = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
            weekdays_en = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            weekdays = weekdays_ru if language == 'ru' else weekdays_en
            
            selected_days = [weekdays[d] for d in days_list]
            days_str = ", ".join(selected_days)
            repeat_text = f"📅 Еженедельное ({days_str})" if language == 'ru' else f"📅 Weekly ({days_str})"
        else:
            repeat_text = ""
        
        success_text = {
            'ru': f"🎉 *Напоминание создано!*\n\n"
                  f"📝 *Текст:* {text}\n"
                  f"⏰ *Время:* {formatted_time}\n"
                  f"🔄 *Тип:* {repeat_text}\n"
                  f"🆔 *ID:* {reminder_id}\n\n"
                  f"Используйте /list для просмотра всех напоминаний.",
            'en': f"🎉 *Reminder created!*\n\n"
                  f"📝 *Text:* {text}\n"
                  f"⏰ *Time:* {formatted_time}\n"
                  f"🔄 *Тип:* {repeat_text}\n"
                  f"🆔 *ID:* {reminder_id}\n\n"
                  f"Use /list to view all reminders."
        }
        
        await callback.message.edit_text(
            success_text.get(language, success_text['en']),
            parse_mode="Markdown"
        )
        
        await callback.message.answer(
            "Меню:" if language == 'ru' else "Menu:",
            reply_markup=get_main_keyboard(language)
        )
        
        await callback.answer()
        
        # Логируем создание
        logger.info(f"Reminder {reminder_id} created for user {user_id}")
        
    except Exception as e:
        error_text = {
            'ru': f"❌ Ошибка при создании напоминания: {str(e)}",
            'en': f"❌ Error creating reminder: {str(e)}"
        }
        
        await callback.message.edit_text(
            error_text.get(language, error_text['ru'])
        )
        
        logger.error(f"Failed to create reminder for user {user_id}: {e}", exc_info=True)
        
# ===== ПЛАНИРОВЩИК =====

def start_scheduler():
    """Запуск планировщика для проверки напоминаний"""
    # Проверяем каждую минуту
    scheduler.add_job(
        check_and_send_reminders,
        'interval',
        minutes=1,
        id='check_reminders'
    )
    
    # Ежедневное резервное копирование в 3:00 UTC
    scheduler.add_job(
        db.backup_database,
        'cron',
        hour=3,
        minute=0,
        id='daily_backup'
    )
    
    scheduler.start()
    logger.info("✅ Планировщик запущен")

# ===== ЗАПУСК БОТА =====

async def on_startup():
    """Действия при запуске бота"""
    logger.info("🤖 Bot is starting...")
    
    # Добавляем админов из конфига
    logger.info(f"👑 Загружены админы из конфига: {Config.ADMINS}")
    
    for admin_id in Config.ADMINS:
        try:
            # Пробуем получить информацию о пользователе
            user = db.get_user(admin_id)
            username = user.get('username') if user else None
            
            db.add_admin(admin_id, username, level=1)
            logger.info(f"✅ Добавлен админ из Config.ADMINS: {admin_id} (@{username})")
            
            # Если пользователя нет в users, добавляем
            if not user:
                logger.warning(f"⚠️ Админ {admin_id} не найден в таблице users")
        except Exception as e:
            logger.error(f"❌ Ошибка добавления админа {admin_id}: {e}")
    
    # Запускаем планировщик
    start_scheduler()
    
    # Отправляем уведомление всем админам о перезапуске
    await notify_admins_about_restart()
    
    logger.info("✅ Bot started successfully")

async def notify_admins_about_restart():
    """Уведомить всех админов о перезапуске бота"""
    try:
        # Получаем всех админов
        admins = db.get_all_admins()
        
        for admin in admins:
            admin_id = admin['user_id']
            try:
                await bot.send_message(
                    admin_id,
                    "🔄 *Бот перезапущен и работает!*\n\n"
                    "✅ Все системы функционируют нормально.\n"
                    "📊 Проверьте работоспособность командой /admin",
                    parse_mode="Markdown"
                )
                logger.info(f"✅ Уведомление о перезапуске отправлено админу {admin_id}")
                await asyncio.sleep(0.1)  # Небольшая пауза между отправками
            except Exception as e:
                logger.error(f"❌ Не удалось отправить уведомление админу {admin_id}: {e}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки уведомлений админам: {e}")
        
async def on_shutdown():
    """Действия при выключении бота"""
    logger.info("🛑 Bot is shutting down...")
    
    # Останавливаем планировщик
    scheduler.shutdown()
    
    # Создаем резервную копию
    db.backup_database()
    
    logger.info("✅ Bot shutdown complete")

async def main():
    """Основная функция запуска бота"""
    try:
        # Действия при запуске
        await on_startup()
        
        # Запускаем бота
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        
    finally:
        # Действия при выключении
        await on_shutdown()

if __name__ == "__main__":
    # Устанавливаем обработчик Ctrl+C
    import signal
    import sys
    
    def signal_handler(signum, frame):
        print(f"\n🛑 Received signal {signum}, shutting down...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Запускаем бота
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
