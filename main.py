#!/usr/bin/env python3
"""
Точка входа для запуска бота
"""

import asyncio
from bot import main

if __name__ == "__main__":
    print("🚀 Запуск Reminder Pro Bot...")
    asyncio.run(main())
