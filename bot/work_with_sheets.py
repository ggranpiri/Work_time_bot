import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import SPREADSHEET_NAME, DEFAULT_HOURLY_RATE
from datetime import datetime, timedelta

# Авторизация в Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("../data/credentials.json", scope)
client = gspread.authorize(creds)

# Открываем таблицу
spreadsheet = client.open(SPREADSHEET_NAME)
sheet = client.open(SPREADSHEET_NAME).sheet1  # Лист для событий
sheet_accounts = spreadsheet.worksheet("Счета")  # Лист для счетов


def log_event(user_id, name, event, work_hours=None, salary=None):
    """Записывает событие в таблицу. Если переданы work_hours и salary — записывает итоговый отчёт по смене."""
    timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")  # Получаем текущее время
    if work_hours is None and salary is None:
        # Обычное событие (Приход, Начал обед, Закончил обед)
        sheet.append_row([timestamp, user_id, name, event])
    else:
        # Специальная запись для "Уход"
        sheet.append_row([timestamp, user_id, name, "Уход", f"{work_hours} ч", f"{salary} руб."])


def calculate_work_time(user_id):
    """Вычисляет отработанное время и зарплату"""
    records = sheet.get_all_values()  # Загружаем все записи
    last_check_in = None
    lunch_end = None
    total_lunch_time = 0  # Время обеда в секундах

    for row in reversed(records):  # Читаем таблицу с конца
        if row[1] == str(user_id):  # Запись для пользователя
            time_event = datetime.strptime(row[0], "%d-%m-%Y %H:%M:%S")

            if row[3] == "Приход":
                last_check_in = time_event
                break
            elif row[3] == "Закончил обед":
                lunch_end = time_event
            elif row[3] == "Начал обед" and lunch_end:
                total_lunch_time += (lunch_end - time_event).total_seconds()
                lunch_end = None

    if last_check_in:
        now = datetime.now()
        work_time = now - last_check_in - timedelta(seconds=total_lunch_time)
        work_hours = round(work_time.total_seconds() / 3600, 2)  # Время в часах

        # Получаем почасовую ставку сотрудника
        accounts = sheet_accounts.get_all_values()
        hourly_rate = DEFAULT_HOURLY_RATE  # Значение по умолчанию

        for row in accounts:
            if row[0] == str(user_id):  # Найден сотрудник
                hourly_rate = float(row[2])  # Берём ставку из таблицы
                break

        salary = round(work_hours * hourly_rate, 2)  # Заработок
        return work_hours, salary
    return 0, 0


def add_user(user_id, name):
    """Добавляет нового пользователя в таблицу 'Счета'.
       Возвращает сообщение о результате."""
    accounts = sheet_accounts.get_all_values()

    # Проверяем, есть ли уже пользователь
    for row in accounts:
        if row and row[0] == str(user_id):
            return 0  # Пользователь уже существует

    # Если пользователя нет, добавляем
    sheet_accounts.append_row([user_id, name, DEFAULT_HOURLY_RATE, 0])
    return 1  # Пользователь успешно добавлен


def get_balance(user_id):
    """Возвращает текущий баланс сотрудника"""
    accounts = sheet_accounts.get_all_values()
    for row in accounts:
        if row[0] == str(user_id):
            return float(row[3])  # Возвращаем баланс
    return 0  # Если сотрудника нет, возвращаем 0


def update_balance(user_id, amount):
    """Добавляет сумму из баланса сотрудника"""
    accounts = sheet_accounts.get_all_values()
    for i, row in enumerate(accounts):
        if row[0] == str(user_id):
            current_balance = float(row[3])
            new_balance = current_balance + amount
            sheet_accounts.update_cell(i + 1, 4, new_balance)  # Обновляем баланс
            return new_balance
    return None  # Если сотрудника нет

def get_all_balances():
    """Возвращает список сотрудников с их балансами"""
    accounts = sheet_accounts.get_all_values()[1:]  # Пропускаем заголовки
    return [[row[1], row[3]] for row in accounts]

def get_all_accounts():
    return sheet_accounts.get_all_values()[1:]



