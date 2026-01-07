#!/usr/bin/env python3
"""
Reminder Pro Bot - Умная напоминалка с поддержкой timezone
"""

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

# Состояния FSM
class ReminderState(StatesGroup):
    waiting_for_text = State()
    waiting_for_date = State()
    waiting_for_repeat = State()

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
        
        # Проблема: remind_time_utc может быть строкой или datetime
        remind_time = reminder['remind_time_utc']
        if isinstance(remind_time, str):
            remind_time = datetime.fromisoformat(remind_time.replace('Z', '+00:00'))
            # Делаем aware (с часовым поясом UTC)
            remind_time = pytz.UTC.localize(remind_time)
        
        # Если это naive datetime, добавляем UTC
        if remind_time.tzinfo is None:
            remind_time = pytz.UTC.localize(remind_time)
        
        # Конвертируем в местное время пользователя для отображения
        user_tz = pytz.timezone(user_timezone)
        local_time = remind_time.astimezone(user_tz)
        
        logger.info(f"  Время UTC в БД: {remind_time}")
        logger.info(f"  Местное время пользователя: {local_time}")
        
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
        due_reminders = db.get_due_reminders()
        
        if not due_reminders:
            return
        
        logger.info(f"Found {len(due_reminders)} due reminders")
        
        for reminder in due_reminders:
            try:
                await send_reminder_notification(reminder)
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Failed to send reminder {reminder['id']}: {e}")
                # Увеличиваем счетчик ошибок
                with db.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        UPDATE reminders 
                        SET error_count = error_count + 1 
                        WHERE id = ?
                    ''', (reminder['id'],))
            
    except Exception as e:
        logger.error(f"Error in check_and_send_reminders: {e}")

# ===== ОСНОВНЫЕ КОМАНДЫ =====

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
/add - Добавить напоминание
/list - Мои напоминания
/today - Напоминания на сегодня
/tomorrow - На завтра
/calendar - Открыть календарь

*Управление:*
/pause <id> - Пауза напоминания
/resume <id> - Возобновить
/delete <id> - Удалить
/pause_all - Пауза всех
/clear - Удалить выполненные

*Настройки:*
/settings - Настройки
/language - Сменить язык
/timezone - Установить часовой пояс
/export - Экспорт напоминаний
/stats - Статистика

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
/add - Add reminder
/list - My reminders
/today - For today
/tomorrow - For tomorrow
/calendar - Open calendar

*Management:*
/pause <id> - Pause reminder
/resume <id> - Resume
/delete <id> - Delete
/pause_all - Pause all
/clear - Delete completed

*Settings:*
/settings - Settings
/language - Change language
/timezone - Set timezone
/export - Export reminders
/stats - Statistics

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

# ===== СОЗДАНИЕ НАПОМИНАНИЙ =====

async def ask_for_time(message: types.Message, language: str, state: FSMContext):
    """Запросить время у пользователя"""
    date_request = {
        'ru': "📅 *Теперь укажите время напоминания*\n\n"
              "Примеры:\n"
              "• Завтра 10:30\n"
              "• Сегодня в 18:00\n"
              "• Через 2 часа\n"
              "• Понедельник в 9 утра\n"
              "• 31.12.2024 23:59\n\n"
              "Или выберите дату из календаря (/calendar)",
        'en': "📅 *Now specify the reminder time*\n\n"
              "Examples:\n"
              "• Tomorrow 10:30 AM\n"
              "• Today at 6:00 PM\n"
              "• In 2 hours\n"
              "• Monday at 9 AM\n"
              "• 12/31/2024 11:59 PM\n\n"
              "Or choose date from calendar (/calendar)"
    }
    
    examples = time_parser.get_examples(language)
    examples_text = "\n".join([f"• {example}" for example in examples[:5]])
    
    full_text = f"{date_request.get(language, date_request['ru'])}\n\n📋 *Примеры:*\n{examples_text}"
    
    keyboard = get_cancel_keyboard(language)
    
    await message.answer(
        full_text,
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    
    await state.set_state(ReminderState.waiting_for_date)

@dp.message(Command("add"))
@dp.message(F.text.in_(["➕ Добавить напоминание", "➕ Add reminder"]))
async def add_reminder_start(message: types.Message, state: FSMContext):
    """Начало добавления напоминания"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    if not user:
        await cmd_start(message)
        return
    
    language = user.get('language_code', 'ru')
    
    # Проверяем лимит
    from config import Config
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
    
    # Запрашиваем текст напоминания
    text_request = {
        'ru': "📝 *Введите текст напоминания:*\n\n"
              "Примеры:\n"
              "• Позвонить маме\n"
              "• Сходить в магазин\n"
              "• Встреча с клиентом\n\n"
              "Можно сразу указать время:\n"
              "• 'Позвонить маме завтра в 10:30'",
        'en': "📝 *Enter reminder text:*\n\n"
              "Examples:\n"
              "• Call mom\n"
              "• Go to the store\n"
              "• Meeting with client\n\n"
              "You can include time:\n"
              "• 'Call mom tomorrow at 10:30 AM'"
    }
    
    await message.answer(
        text_request.get(language, text_request['ru']),
        parse_mode="Markdown"
    )
    
    await state.set_state(ReminderState.waiting_for_text)

@dp.message(ReminderState.waiting_for_text)
async def process_reminder_text(message: types.Message, state: FSMContext):
    """Обработка текста напоминания"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    language = user.get('language_code', 'ru')
    
    # Извлекаем текст и время
    text_part, time_part = time_parser.extract_reminder_text(message.text, language)
    
    if time_part:
        # Время найдено в тексте
        await state.update_data(text=text_part, extracted_time=time_part)
        
        # Парсим время
        timezone = user.get('timezone', 'Europe/Moscow')
        parsed_time, parse_type, extra_info = time_parser.parse(
            time_part, language, timezone
        )
        
        if parsed_time:
            # Время распознано успешно
            await state.update_data(
                parsed_time=parsed_time.isoformat(),
                timezone=timezone,
                parse_type=parse_type
            )
            
            # Показываем подтверждение
            formatted_time = format_local_time(parsed_time, timezone, language)
            
            confirm_text = {
                'ru': f"✅ *Время распознано*\n\n"
                      f"📝 *Текст:* {text_part}\n"
                      f"⏰ *Время:* {formatted_time}\n\n"
                      "Верно ли распознано время?",
                'en': f"✅ *Time recognized*\n\n"
                      f"📝 *Text:* {text_part}\n"
                      f"⏰ *Time:* {formatted_time}\n\n"
                      "Is the time correct?"
            }
            
            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(
                    text="✅ Да" if language == 'ru' else "✅ Yes",
                    callback_data="time_correct"
                ),
                InlineKeyboardButton(
                    text="❌ Нет" if language == 'ru' else "❌ No",
                    callback_data="time_wrong"
                )
            )
            
            await message.answer(
                confirm_text.get(language, confirm_text['ru']),
                parse_mode="Markdown",
                reply_markup=builder.as_markup()
            )
        else:
            # Не удалось распознать время
            error_text = {
                'ru': f"❌ Не удалось распознать время: '{time_part}'\n\n"
                      "Попробуйте ввести время отдельно:",
                'en': f"❌ Could not recognize time: '{time_part}'\n\n"
                      "Try entering time separately:"
            }
            
            await state.update_data(text=text_part)
            await ask_for_time(message, language, state)
    else:
        # Время не найдено, запрашиваем отдельно
        await state.update_data(text=message.text)
        await ask_for_time(message, language, state)

@dp.message(ReminderState.waiting_for_date)
async def process_reminder_date(message: types.Message, state: FSMContext):
    """Обработка даты и времени напоминания"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    language = user.get('language_code', 'ru')
    timezone = user.get('timezone', 'Europe/Moscow')
    
    # Проверяем отмену
    cancel_texts = ["❌ отмена", "❌ cancel", "отмена", "cancel", "/cancel"]
    if message.text.lower() in [ct.lower() for ct in cancel_texts]:
        await state.clear()
        cancel_text = {
            'ru': "❌ Создание напоминания отменено",
            'en': "❌ Reminder creation cancelled"
        }
        await message.answer(
            cancel_text.get(language, cancel_text['ru']),
            reply_markup=get_main_keyboard(language)
        )
        return
    
    # Парсим время
    parsed_time, parse_type, extra_info = time_parser.parse(
        message.text, language, timezone
    )
    
    if not parsed_time:
        # Не удалось распознать время
        error_text = {
            'ru': "❌ Не удалось распознать время.\n\n"
                  "Попробуйте еще раз или введите /help для примеров.",
            'en': "❌ Could not recognize time.\n\n"
                  "Try again or enter /help for examples."
        }
        
        await message.answer(
            error_text.get(language, error_text['ru']),
            parse_mode="Markdown"
        )
        return
    
    # Проверяем корректность времени
    is_valid, error_msg = time_parser.validate_time(parsed_time)
    if not is_valid:
        error_text = {
            'ru': f"❌ {error_msg}",
            'en': f"❌ {error_msg}"
        }
        await message.answer(error_text.get(language, error_text['ru']))
        return
    
    # Получаем текст из состояния
    user_data = await state.get_data()
    text = user_data.get('text', '')
    
    # Сохраняем время в состоянии
    await state.update_data(
        parsed_time=parsed_time.isoformat(),
        timezone=timezone,
        parse_type=parse_type
    )
    
    # Показываем подтверждение и спрашиваем про повторения
    await ask_for_repeat_type(message, parsed_time, text, timezone, language)

async def ask_for_repeat_type(message: types.Message, parsed_time: datetime, 
                             text: str, timezone: str, language: str):
    """Спросить тип повторения"""
    formatted_time = format_local_time(parsed_time, timezone, language)
    
    confirm_text = {
        'ru': f"✅ *Время подтверждено*\n\n"
              f"📝 *Текст:* {text}\n"
              f"⏰ *Время:* {formatted_time}\n\n"
              "Это повторяющееся напоминание?",
        'en': f"✅ *Time confirmed*\n\n"
              f"📝 *Text:* {text}\n"
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

# ===== ОБРАБОТКА CALLBACK'ОВ =====

@dp.callback_query(F.data.in_(["time_correct", "time_wrong"]))
async def handle_time_confirmation(callback: types.CallbackQuery, state: FSMContext):
    """Обработка подтверждения времени"""
    user_id = callback.from_user.id
    user = db.get_user(user_id)
    language = user.get('language_code', 'ru')
    
    if callback.data == "time_correct":
        # Время верное, спрашиваем про повторения
        user_data = await state.get_data()
        text = user_data.get('text', '')
        parsed_time_str = user_data.get('parsed_time')
        timezone = user_data.get('timezone', 'Europe/Moscow')
        
        if parsed_time_str:
            parsed_time = datetime.fromisoformat(parsed_time_str)
            await ask_for_repeat_type(callback.message, parsed_time, text, timezone, language)
            await callback.answer()
        else:
            await callback.answer("Ошибка: время не найдено", show_alert=True)
    else:
        # Время неверное, запрашиваем заново
        user_data = await state.get_data()
        text = user_data.get('text', '')
        
        await state.update_data(text=text)
        await ask_for_time(callback.message, language, state)
        await callback.answer()

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
        
        # Конвертируем в UTC
        utc_time = parsed_time.astimezone(pytz.UTC)
        
        # Отладочная информация
        logger.info(f"Создание напоминания: пользователь {user_id}")
        logger.info(f"  Местное время: {parsed_time} ({timezone})")
        logger.info(f"  UTC время: {utc_time}")
        
        # Для тестирования: если время в прошлом, добавляем 1 минуту
        now_utc = datetime.now(pytz.UTC)
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
                  f"🔄 *Type:* {repeat_text}\n"
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
        
# ===== ПРОСМОТР НАПОМИНАНИЙ =====

@dp.message(Command("list"))
@dp.message(F.text.in_(["📋 Мои напоминания", "📋 My reminders"]))
async def cmd_list(message: types.Message):
    """Показать список напоминаний пользователя"""
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
            'ru': "📭 У вас нет активных напоминаний.",
            'en': "📭 You have no active reminders."
        }
        await message.answer(empty_text.get(language, empty_text['ru']))
        return
    
    # Ограничиваем вывод 10 напоминаниями
    limited_reminders = reminders[:10]
    
    response_text = {
        'ru': f"📋 *Ваши напоминания ({len(reminders)}):*\n\n",
        'en': f"📋 *Your reminders ({len(reminders)}):*\n\n"
    }.get(language, f"📋 Your reminders ({len(reminders)}):\n\n")
    
    for i, reminder in enumerate(limited_reminders, 1):
        # Форматируем время (с проверкой типа)
        remind_time = reminder['remind_time_utc']
        if isinstance(remind_time, str):
            remind_time = datetime.fromisoformat(remind_time)
        
        formatted_time = format_local_time(remind_time, timezone, language)
        
        # Тип повторения
        repeat_type = reminder['repeat_type']
        if repeat_type == 'once':
            repeat_symbol = "✅"
            repeat_text = "Разовое" if language == 'ru' else "One-time"
        elif repeat_type == 'daily':
            repeat_symbol = "🔄"
            repeat_text = "Ежедневное" if language == 'ru' else "Daily"
        elif repeat_type == 'weekly':
            repeat_symbol = "📅"
            repeat_text = "Еженедельное" if language == 'ru' else "Weekly"
        else:
            repeat_symbol = "📌"
            repeat_text = ""
        
        response_text += f"{i}. *ID: {reminder['id']}*\n"
        response_text += f"   {repeat_symbol} {reminder['text']}\n"
        response_text += f"   ⏰ {formatted_time}\n"
        
        if repeat_text:
            response_text += f"   {repeat_text}\n"
        
        # Для еженедельных показываем дни
        if repeat_type == 'weekly' and reminder.get('repeat_days'):
            days_list = [int(d) for d in reminder['repeat_days'].split(',')] if reminder['repeat_days'] else []
            weekdays_ru = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
            weekdays_en = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            weekdays = weekdays_ru if language == 'ru' else weekdays_en
            
            selected_days = [weekdays[d] for d in days_list]
            days_str = ", ".join(selected_days)
            response_text += f"   📅 ({days_str})\n"
        
        response_text += "\n"
    
    if len(reminders) > 10:
        more_text = {
            'ru': f"\n... и еще {len(reminders) - 10} напоминаний",
            'en': f"\n... and {len(reminders) - 10} more reminders"
        }
        response_text += more_text.get(language, more_text['en'])
    
    await message.answer(response_text, parse_mode="Markdown")

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
    for admin_id in Config.ADMINS:
        db.add_admin(admin_id, level=1)
        logger.info(f"Added admin: {admin_id}")
    
    # Запускаем планировщик
    start_scheduler()
    
    logger.info("✅ Bot started successfully")

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
