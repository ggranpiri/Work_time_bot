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


@dp.callback_query(PayCallback.filter())
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
