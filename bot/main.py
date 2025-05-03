import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from config import TOKEN, ADMINS_ID
from work_with_sheets import *
from buttons import worker_kb, admin_kb, get_employee_keyboard, PayCallback

# Логирование
logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def start(message: types.Message):
    """Регистрируем сотрудника при первом запуске"""
    user_id = message.from_user.id
    name = message.from_user.full_name

    result = add_user(user_id, name)  # Добавляем пользователя
    buttons = worker_kb
    if user_id in ADMINS_ID:
        buttons = admin_kb
    if result == 1:
        await message.answer("Вы успешно зарегистрированы! Выберите действие:", reply_markup=buttons)
        await notify_admins(f"Сотрудник {name} зарегистрирован")
    else:
        await message.answer("Вы уже зарегистрированы. Выберите действие:", reply_markup=buttons)


async def notify_admins(message: str):
    """Отправляет сообщение всем администраторам"""
    for admin_id in ADMINS_ID:
        try:
            await bot.send_message(admin_id, message, parse_mode="Markdown")
        except Exception as e:
            print(f"Ошибка отправки админу {admin_id}: {e}")


@dp.message(lambda message: message.text == "Просмотреть информацию")
async def show_all_balances(message: types.Message):
    """Показывает балансы всех сотрудников"""
    if message.from_user.id in ADMINS_ID:
        balances = get_all_balances()
        text = "\n".join([f"{name}: {balance} руб." for name, balance in balances])
        await message.answer(f"Балансы сотрудников:\n{text}")
    else:
        await message.answer("У вас нет прав администратора.")


class SalaryPayment(StatesGroup):
    choosing_employee = State()
    entering_amount = State()


@dp.message(lambda message: message.text == "Выдать зарплату")
async def choose_employee(message: types.Message, state: FSMContext):
    """Выбор сотрудника для выдачи зарплаты"""
    if message.from_user.id in ADMINS_ID:
        await message.answer("Выберите сотрудника:", reply_markup=get_employee_keyboard())
        await state.set_state(SalaryPayment.choosing_employee)
    else:
        await message.answer("У вас нет прав администратора.")


@dp.callback_query(StateFilter(SalaryPayment.choosing_employee), PayCallback.filter())
async def enter_salary_amount(call: types.CallbackQuery, state: FSMContext, callback_data: dict):
    """Получаем ID выбранного сотрудника и запрашиваем сумму"""
    user_id = callback_data.user_id  # Получаем ID сотрудника
    name = get_user_name(user_id)
    await state.update_data(user_id=user_id)

    await call.message.answer(f"Введите сумму для выплаты *{name}*:", parse_mode="Markdown")
    await state.set_state(SalaryPayment.entering_amount)


@dp.message(StateFilter(SalaryPayment.entering_amount), lambda message: message.text.isdigit())
async def process_salary_payment(message: types.Message, state: FSMContext):
    """Обрабатываем выплату зарплаты"""
    data = await state.get_data()
    user_id = data["user_id"]  # Получаем ID сотрудника
    name = get_user_name(user_id)
    amount = float(message.text)

    new_balance = update_balance(user_id, -amount)
    if new_balance is not None:
        add_event_transaction(int(user_id), name, "Выплата", amount, new_balance)
        await message.answer(f"Сотруднику *{name}* выплачено *{amount} руб.*\nНовый баланс: *{new_balance} руб.*",
                             parse_mode="Markdown")
        # Отправляем уведомление сотруднику
        try:
            await bot.send_message(user_id, f"Вам выплачено *{amount} руб.*\nНовый баланс: *{new_balance} руб.*",
                                   parse_mode="Markdown")
        except Exception as e:
            await message.answer(f"Не удалось уведомить сотрудника (ID {user_id}). Возможно, у него закрыты ЛС.")

    else:
        await message.answer("Ошибка: сотрудник не найден.")

    await state.clear()


class ManualEntry(StatesGroup):
    choosing_employee = State()
    entering_text = State()
    confirming_event = State()
    entering_time = State()


@dp.message(lambda message: message.text == "Добавить запись в таблицу")
async def start_manual_entry(message: types.Message, state: FSMContext):
    if message.from_user.id in ADMINS_ID:
        await message.answer("Выберите сотрудника для добавления записи:", reply_markup=get_employee_keyboard())
        await state.set_state(ManualEntry.choosing_employee)
    else:
        await message.answer("У вас нет прав администратора.")


from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


@dp.callback_query(StateFilter(ManualEntry.choosing_employee), PayCallback.filter())
async def get_manual_entry_text(call: types.CallbackQuery, state: FSMContext, callback_data: dict):
    """Предлагает логичное следующее событие на основе последнего"""
    user_id = callback_data.user_id
    name = get_user_name(user_id)

    last_type, last_time = get_last_event(user_id)
    await state.update_data(user_id=user_id, name=name)

    # Определим доступные действия
    if last_type is None:
        text = f"У пользователя *{name}* нет активных записей. Что добавить?"
        next_actions = ["Приход"]
    elif last_type == "Приход":
        text = f"Последняя запись: *{last_type}* в {last_time.strftime('%H:%M %d-%m-%Y')}. Что добавить?"
        next_actions = ["Уход", "Начал обед"]
    elif last_type == "Начал обед":
        text = f"Последняя запись: *{last_type}* в {last_time.strftime('%H:%M %d-%m-%Y')}. Что добавить?"
        next_actions = ["Закончил обед"]
    elif last_type == "Закончил обед":
        text = f"Последняя запись: *{last_type}* в {last_time.strftime('%H:%M %d-%m-%Y')}. Что добавить?"
        next_actions = ["Начал обед", "Уход"]
    elif last_type == "Уход":
        text = f"Последняя запись: *{last_type}* в {last_time.strftime('%H:%M %d-%m-%Y')}. Что добавить?"
        next_actions = ["Приход"]
    else:
        text = f"Последняя запись: *{last_type}* в {last_time.strftime('%H:%M %d-%m-%Y')}. Что добавить?"
        next_actions = ["Приход"]

    # Создаём кнопки на основе доступных действий
    buttons = [[InlineKeyboardButton(text=f"✅ {action}", callback_data=f"add_event:{action}")] for action in
               next_actions]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_manual_entry")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await call.message.answer(text, parse_mode="Markdown", reply_markup=keyboard)
    await state.set_state(ManualEntry.confirming_event)


@dp.callback_query(StateFilter(ManualEntry.confirming_event))
async def confirm_manual_entry(call: types.CallbackQuery, state: FSMContext):
    """Переход к вводу времени события"""
    data = await state.get_data()
    name = data["name"]

    if call.data.startswith("add_event:"):
        event = call.data.split(":")[1]
        await state.update_data(event=event)
        await call.message.answer(f"Введите время события для *{name}* (например, `09:00` или `03-05-2025 09:00`):",
                                  parse_mode="Markdown")
        await state.set_state(ManualEntry.entering_time)
    else:
        await call.message.answer("Действие отменено.")
        await state.clear()


@dp.message(StateFilter(ManualEntry.entering_time))
async def enter_event_time(message: types.Message, state: FSMContext):
    """Добавляет событие с заданным временем, включая расчёт для 'Уход'"""
    data = await state.get_data()
    user_id = int(data["user_id"])
    name = data["name"]
    event = data["event"]
    raw_time = message.text.strip()

    try:
        if len(raw_time) <= 5:
            # Только время — используем текущую дату
            time_obj = datetime.strptime(raw_time, "%H:%M")
            event_time = datetime.now().replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
        else:
            # Полная дата и время
            event_time = datetime.strptime(raw_time, "%d-%m-%Y %H:%M")
    except ValueError:
        await message.answer("❌ Неверный формат. Введите `HH:MM` или `ДД-ММ-ГГГГ HH:MM`")
        return

    if event == "Уход":
        work_hours, salary = calculate_work_time(user_id, event_time)
        new_balance = update_balance(user_id, salary)
        log_event(user_id, name, event, time=event_time, work_hours=work_hours, salary=salary)
        add_event_transaction(user_id, name, "Заработок", salary, new_balance)
        text = f"✅ Добавлен *Уход* для *{name}* в {event_time.strftime('%H:%M %d-%m-%Y')}\nОтработано: *{work_hours}* ч\nЗарплата: *{salary}* руб.\nТекущий баланс: *{new_balance}* руб."

    else:
        log_event(user_id, name, event, time=event_time)
        text = f"Добавлено: *{event}* для *{name}* в {event_time.strftime('%H:%M %d-%m-%Y')}"

    await notify_admins(text)
    # Отправляем уведомление сотруднику
    try:
        await bot.send_message(user_id, text, parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"Не удалось уведомить сотрудника (ID {user_id}). Возможно, у него закрыты ЛС.")

    await state.clear()


@dp.message(lambda message: message.text in ["Приход", "Уход", "Начал обед", "Закончил обед"])
async def worker_action(message: types.Message):
    user_id = message.from_user.id
    name = get_user_name(user_id)
    action = message.text
    try:
        # Проверяем и исправляем предыдущее событие
        fix_message = check_and_fix_records(user_id, name, action)
        if fix_message:
            await message.answer(fix_message)
            await notify_admins(f'Сотрудник *{name}* выбрал "{action}"" и получил ошибку: \n'
                                f"_{fix_message}_")
            return

        if action == "Уход":
            work_hours, salary = calculate_work_time(user_id)
            new_balance = update_balance(user_id, salary)
            log_event(user_id, name, action, work_hours=work_hours, salary=salary)
            add_event_transaction(user_id, name, "Заработок", salary, new_balance)
            await message.answer(f"Вы отработали *{work_hours}* часов и заработали *{salary}* руб.\n"
                                 f"Ваш текущий баланс: *{new_balance} руб.*", parse_mode='Markdown')

            # Уведомляем всех администраторов
            await notify_admins(f"Сотрудник *{name}* ушёл с работы.\n"
                                f"Отработано: *{work_hours}* часов\n"
                                f"Зарплата: *{salary}* руб.\n"
                                f"Текущий баланс: *{new_balance}* руб.")
        else:
            log_event(user_id, name, action)
            await message.answer(f"Записано: {action}")
            await notify_admins(f"Сотрудник *{name}* отметил: {action}")
    except Exception as e:
        print(e)
        await bot.send_message(user_id, f"Не получилось выполнить действие. Ошибка: _{e}_", parse_mode="Markdown")


async def main():
    await notify_admins("Бот запущен")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
