from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters.callback_data import CallbackData
from work_with_sheets import get_all_accounts

# Кнопки для сотрудников
worker_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Приход"), KeyboardButton(text="Уход")],
        [KeyboardButton(text="Начал обед"), KeyboardButton(text="Закончил обед")]
    ],
    resize_keyboard=True
)

# Кнопки для админа
admin_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Выдать зарплату"), KeyboardButton(text="Просмотреть информацию")]
    ],
    resize_keyboard=True
)


# Определяем CallbackData-класс
class PayCallback(CallbackData, prefix="pay"):
    user_id: str
    name: str

def get_employee_keyboard():
    """Создаёт выпадающий список сотрудников (имя отображается, но передаётся ID)"""
    accounts = get_all_accounts()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{name} ({balance} руб.)", callback_data=PayCallback(user_id=user_id, name=name).pack())]
            for user_id, name, state, balance in accounts
        ]
    )
    return keyboard