from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder

def get_main_keyboard(language: str = 'ru') -> ReplyKeyboardMarkup:
    """Получить главное меню"""
    builder = ReplyKeyboardBuilder()
    
    if language == 'ru':
        builder.row(
            KeyboardButton(text="➕ Добавить напоминание"),
            KeyboardButton(text="📋 Мои напоминания")
        )
        builder.row(
            KeyboardButton(text="📅 На сегодня"),
            KeyboardButton(text="📆 На завтра")
        )
        builder.row(
            KeyboardButton(text="⚙️ Настройки"),
            KeyboardButton(text="❓ Помощь")
        )
    else:
        builder.row(
            KeyboardButton(text="➕ Add reminder"),
            KeyboardButton(text="📋 My reminders")
        )
        builder.row(
            KeyboardButton(text="📅 For today"),
            KeyboardButton(text="📆 For tomorrow")
        )
        builder.row(
            KeyboardButton(text="⚙️ Settings"),
            KeyboardButton(text="❓ Help")
        )
    
    return builder.as_markup(resize_keyboard=True)

def get_cancel_keyboard(language: str = 'ru') -> ReplyKeyboardMarkup:
    """Получить клавиатуру с кнопкой отмены"""
    builder = ReplyKeyboardBuilder()
    
    if language == 'ru':
        builder.add(KeyboardButton(text="❌ Отмена"))
    else:
        builder.add(KeyboardButton(text="❌ Cancel"))
    
    return builder.as_markup(resize_keyboard=True)
