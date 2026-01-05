#!/usr/bin/env python3
"""
Reminder Pro Bot - Умная напоминалка с поддержкой timezone
"""

import asyncio
import logging
import sys
from datetime import datetime

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import Config
from database import Database
from timezone_handler import TimezoneHandler
from reminder_manager import ReminderManager
from admin_panel import AdminPanel
from recovery_system import RecoverySystem
from utils.time_parser import TimeParser

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
timezone_handler = TimezoneHandler()
reminder_manager = ReminderManager(db, bot)
admin_panel = AdminPanel(db, bot)
recovery_system = RecoverySystem(db, bot)

# После других инициализаций
time_parser = TimeParser()

# Состояния FSM
class ReminderState(StatesGroup):
    waiting_for_text = State()
    waiting_for_date = State()
    waiting_for_time = State()
    waiting_for_repeat = State()

class SettingsState(StatesGroup):
    waiting_for_language = State()
    waiting_for_timezone = State()



# ===== ОСНОВНЫЕ КОМАНДЫ =====

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start - начало работы"""
    user = message.from_user
    
    # Определяем часовой пояс
    timezone_name, offset = timezone_handler.get_user_timezone(user)
    
    # Регистрируем/обновляем пользователя
    db.add_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language_code=user.language_code or 'ru',
        timezone_offset=offset
    )
    
    # Обновляем часовой пояс, если определили
    db.update_user_timezone(user.id, timezone_name, offset)
    
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
    
    timezone_display = timezone_handler.get_timezone_display_name(timezone_name, user_lang)
    
    # Создаем клавиатуру
    from keyboards.main_menu import get_main_keyboard
    keyboard = get_main_keyboard(user_lang)
    
    await message.answer(
        welcome_text[user_lang].format(timezone=timezone_display),
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    
    logger.info(f"User {user.id} started the bot")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Команда /help - помощь"""
    user_lang = db.get_user(message.from_user.id).get('language_code', 'ru')
    
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

# ===== НАЧАЛО ДОБАВЛЕНИЯ НАПОМИНАНИЯ =====

@dp.message(Command("add"))
@dp.message(F.text.in_(["➕ Добавить напоминание", "➕ Add reminder"]))
async def add_reminder_start(message: types.Message, state: FSMContext):
    """Начало добавления напоминания"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
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
            limit_text.get(user.get('language_code', 'ru'), limit_text['ru']),
            parse_mode="Markdown"
        )
        return
    
    # Запрашиваем текст напоминания
    text_request = {
        'ru': "📝 *Введите текст напоминания:*\n\n"
              "Примеры:\n"
              "• Позвонить маме\n"
              "• Сходить в магазин\n"
              "• Встреча с клиентом",
        'en': "📝 *Enter reminder text:*\n\n"
              "Examples:\n"
              "• Call mom\n"
              "• Go to the store\n"
              "• Meeting with client"
    }
    
    await message.answer(
        text_request.get(user.get('language_code', 'ru'), text_request['ru']),
        parse_mode="Markdown"
    )
    
    await state.set_state(ReminderState.waiting_for_text)

@dp.message(ReminderState.waiting_for_text)
async def process_reminder_text(message: types.Message, state: FSMContext):
    """Обработка текста напоминания"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    
    # Сохраняем текст напоминания
    await state.update_data(text=message.text)
    
    # Пробуем извлечь время из текста
    language = user.get('language_code', 'ru')
    text_part, time_part = time_parser.extract_reminder_text(message.text, language)
    
    if time_part:
        # Время найдено в тексте
        await state.update_data(text=text_part, extracted_time=time_part)
        
        # Запрашиваем подтверждение времени
        confirm_text = {
            'ru': f"📝 *Текст напоминания:* {text_part}\n\n"
                  f"⏰ *Распознанное время:* {time_part}\n\n"
                  "Верно ли распознано время?",
            'en': f"📝 *Reminder text:* {text_part}\n\n"
                  f"⏰ *Recognized time:* {time_part}\n\n"
                  "Is the time correct?"
        }
        
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        
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
        
        await state.set_state(ReminderState.waiting_for_date)
    else:
        # Время не найдено, запрашиваем отдельно
        await state.update_data(text=message.text)
        
        date_request = {
            'ru': "📅 *Теперь укажите время напоминания*\n\n"
                  "Примеры:\n"
                  "• Завтра 10:30\n"
                  "• Сегодня в 18:00\n"
                  "• Через 2 часа\n"
                  "• Понедельник в 9 утра\n\n"
                  "Или выберите дату из календаря:",
            'en': "📅 *Now specify the reminder time*\n\n"
                  "Examples:\n"
                  "• Tomorrow 10:30 AM\n"
                  "• Today at 6:00 PM\n"
                  "• In 2 hours\n"
                  "• Monday at 9 AM\n\n"
                  "Or choose date from calendar:"
        }
        
        from keyboards.main_menu import get_cancel_keyboard
        keyboard = get_cancel_keyboard(language)
        
        await message.answer(
            date_request.get(language, date_request['ru']),
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        
        await state.set_state(ReminderState.waiting_for_date)

@dp.message(ReminderState.waiting_for_date)
async def process_reminder_date(message: types.Message, state: FSMContext):
    """Обработка даты и времени напоминания"""
    user_id = message.from_user.id
    user = db.get_user(user_id)
    language = user.get('language_code', 'ru')
    timezone = user.get('timezone', 'Europe/Moscow')
    
    # Проверяем отмену
    cancel_texts = ["❌ отмена", "❌ cancel", "отмена", "cancel"]
    if message.text.lower() in [ct.lower() for ct in cancel_texts]:
        await state.clear()
        from keyboards.main_menu import get_main_keyboard
        await message.answer(
            "❌ Создание напоминания отменено" if language == 'ru' else "❌ Reminder creation cancelled",
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
                  "Попробуйте еще раз:\n"
                  "• Завтра 10:30\n"
                  "• Сегодня в 18:00\n"
                  "• Через 2 часа\n"
                  "• 31.12.2024 23:59",
            'en': "❌ Could not recognize time.\n\n"
                  "Try again:\n"
                  "• Tomorrow 10:30 AM\n"
                  "• Today at 6:00 PM\n"
                  "• In 2 hours\n"
                  "• 12/31/2024 11:59 PM"
        }
        
        await message.answer(
            error_text.get(language, error_text['en']),
            parse_mode="Markdown"
        )
        return
    
    # Проверяем корректность времени
    is_valid, error_msg = time_parser.validate_time(parsed_time)
    if not is_valid:
        await message.answer(f"❌ {error_msg}")
        return
    
    # Сохраняем время в состоянии
    user_data = await state.get_data()
    text = user_data.get('text', '')
    
    # Обновляем данные в состоянии
    await state.update_data(
        parsed_time=parsed_time.isoformat(),
        timezone=timezone
    )
    
    # Показываем подтверждение
    formatted_time = time_parser.format_local_time(parsed_time, timezone, language)
    
    confirm_text = {
        'ru': f"✅ *Время распознано*\n\n"
              f"📝 *Текст:* {text}\n"
              f"⏰ *Время:* {formatted_time}\n\n"
              "Это повторяющееся напоминание?",
        'en': f"✅ *Time recognized*\n\n"
              f"📝 *Text:* {text}\n"
              f"⏰ *Time:* {formatted_time}\n\n"
              "Is this a repeating reminder?"
    }
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    
    builder = InlineKeyboardBuilder()
    
    if language == 'ru':
        builder.row(
            InlineKeyboardButton(text="✅ Разовое", callback_data="repeat_once"),
            InlineKeyboardButton(text="🔄 Ежедневное", callback_data="repeat_daily"),
            InlineKeyboardButton(text="📅 Еженедельное", callback_data="repeat_weekly")
        )
        builder.row(
            InlineKeyboardButton(text="❌ Отмена", callback_data="repeat_cancel")
        )
    else:
        builder.row(
            InlineKeyboardButton(text="✅ One-time", callback_data="repeat_once"),
            InlineKeyboardButton(text="🔄 Daily", callback_data="repeat_daily"),
            InlineKeyboardButton(text="📅 Weekly", callback_data="repeat_weekly")
        )
        builder.row(
            InlineKeyboardButton(text="❌ Cancel", callback_data="repeat_cancel")
        )
    
    await message.answer(
        confirm_text.get(language, confirm_text['ru']),
        parse_mode="Markdown",
        reply_markup=builder.as_markup()
    )
    
    await state.set_state(ReminderState.waiting_for_repeat)
# ===== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====

async def send_reminder_notification(reminder: dict):
    """Отправить уведомление о напоминании"""
    try:
        user_timezone = reminder['timezone']
        user_lang = reminder.get('language_code', 'ru')
        
        # Форматируем время для пользователя
        remind_time = datetime.fromisoformat(reminder['remind_time_utc'])
        formatted_time = timezone_handler.format_local_time(
            remind_time, user_timezone, user_lang
        )
        
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
        
        # Помечаем как отправленное
        db.mark_reminder_sent(reminder['id'])
        
        logger.info(f"Sent reminder {reminder['id']} to user {reminder['user_id']}")
        
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

async def check_and_send_reminders():
    """Проверить и отправить напоминания, которые подошли по времени"""
    try:
        due_reminders = db.get_due_reminders()
        
        if not due_reminders:
            return
        
        logger.info(f"Found {len(due_reminders)} due reminders")
        
        # Отправляем каждое напоминание
        for reminder in due_reminders:
            await send_reminder_notification(reminder)
            await asyncio.sleep(0.1)  # Чтобы не превысить лимиты Telegram
            
    except Exception as e:
        logger.error(f"Error in check_and_send_reminders: {e}")

# ===== ЗАПУСК ПЛАНИРОВЩИКА =====

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
    
    # Проверяем пропущенные напоминания
    await recovery_system.check_missed_reminders()
    
    # Уведомляем админов о запуске
    await admin_panel.notify_admins_about_start()
    
    logger.info("✅ Bot started successfully")

async def on_shutdown():
    """Действия при выключении бота"""
    logger.info("🛑 Bot is shutting down...")
    
    # Останавливаем планировщик
    scheduler.shutdown()
    
    # Создаем резервную копию
    db.backup_database()
    
    # Уведомляем админов о выключении
    await admin_panel.notify_admins_about_shutdown()
    
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
