"""
Валидаторы для данных бота
"""

import re
from datetime import datetime
from typing import Tuple, Optional

class Validators:
    @staticmethod
    def validate_text(text: str, max_length: int = 500) -> Tuple[bool, str]:
        """Валидация текста напоминания"""
        if not text or not text.strip():
            return False, "Текст не может быть пустым"
        
        if len(text.strip()) > max_length:
            return False, f"Текст слишком длинный (максимум {max_length} символов)"
        
        # Проверка на запрещенные символы
        forbidden_patterns = [
            r'<script.*?>.*?</script>',  # XSS защита
            r'javascript:',  # JS инъекции
            r'on\w+=',  # HTML события
        ]
        
        for pattern in forbidden_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return False, "Текст содержит недопустимые символы"
        
        return True, "OK"
    
    @staticmethod
    def validate_timezone(timezone: str) -> Tuple[bool, str]:
        """Валидация часового пояса"""
        try:
            import pytz
            pytz.timezone(timezone)
            return True, "OK"
        except:
            return False, "Неверный часовой пояс"
    
    @staticmethod
    def validate_language(lang: str) -> Tuple[bool, str]:
        """Валидация языка"""
        valid_langs = ['ru', 'en']
        if lang in valid_langs:
            return True, "OK"
        return False, f"Неподдерживаемый язык. Доступно: {', '.join(valid_langs)}"
