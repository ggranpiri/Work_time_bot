import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import SPREADSHEET_NAME, DEFAULT_HOURLY_RATE, DEFAULT_LUNCH_TIME, AUTO_CHECK_OUT_TIME, AUTO_CHECK_IN_TIME
from datetime import datetime, timedelta

# Авторизация в Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("../data/credentials.json", scope)
client = gspread.authorize(creds)

# Открываем таблицу
spreadsheet = client.open(SPREADSHEET_NAME)
sheet = client.open(SPREADSHEET_NAME).sheet1  # Лист для событий
sheet_accounts = spreadsheet.worksheet("Счета")  # Лист для счетов
sheet_transaction = spreadsheet.worksheet("Транзакции")  # Лист для истории транзакций


def log_event(user_id, name, event, time=None, work_hours=None, salary=None):
    """Записывает событие в таблицу. Если переданы work_hours и salary — записывает итоговый отчёт по смене."""
    if not time:
        time = datetime.now()  # Получаем текущее время
    time = time.strftime("%d-%m-%Y %H:%M:%S")
    if work_hours is None and salary is None:
        # Обычное событие (Приход, Начал обед, Закончил обед)
        sheet.append_row([time, user_id, name, event])
    else:
        # Специальная запись для "Уход"
        sheet.append_row([time, user_id, name, "Уход", work_hours, salary])

def add_event_transaction(user_id, name, type ,salary, balance):
   time = datetime.now().strftime("%d-%m-%Y %H:%M:%S")  # Получаем текущее время
   sheet_transaction.append_row([time, user_id, name, type, salary, balance])



def get_user_name(user_id):
    """Возвращает имя сотрудника по user_id со второго листа таблицы."""
    records = sheet_accounts.get_all_values()  # Загружаем данные второго листа

    for row in records:
        if row[0] == str(user_id):  # Первый столбец — user_id
            return row[1]  # Второй столбец — имя

    return None  # Если сотрудник не найден

def check_and_fix_records(user_id, user_name, event):
    """Проверяет последнее событие и автоматически добавляет недостающие записи"""
    records = sheet.get_all_values()
    last_event = None
    last_event_type = None

    for row in reversed(records):
        if row[1] == str(user_id):
            last_event = datetime.strptime(row[0], "%d-%m-%Y %H:%M:%S")
            last_event_type = row[3]
            break

    if event == "Приход":
        if last_event_type != "Уход":
            return f'Вы не можете выполнить действие "{event}" после "{last_event_type}". Пожалуйста, выберите другое действие или обратитесь к администратору'

    if event == "Уход":
        if last_event.date() != datetime.now().date():
            return f'"{event}" не может быть выполнено в другой день, чем "{last_event_type}". Пожалуйста, выберите другое действие или обратитесь к администратору'
        if last_event_type not in ["Закончил обед", "Приход"]:
            return f'Вы не можете выполнить действие "{event}" после "{last_event_type}". Пожалуйста, выберите другое действие или обратитесь к администратору'

    if event == "Начал обед":
        if last_event.date() != datetime.now().date():
            return f'"{event}" не может быть выполнено в другой день, чем "{last_event_type}". Пожалуйста, выберите другое действие или обратитесь к администратору'
        if last_event_type not in ["Закончил обед", "Приход"]:
            return f'Вы не можете выполнить действие "{event}" после "{last_event_type}". Пожалуйста, выберите другое действие или обратитесь к администратору'

    if event == "Закончил обед":
        if last_event.date() != datetime.now().date():
            return f'"{event}" не может быть выполнено в другой день, чем "{last_event_type}" . Пожалуйста, выберите другое действие или обратитесь к администратору'
        if last_event_type != "Начал обед":
            return f'Вы не можете выполнить действие "{event}" после "{last_event_type}". Пожалуйста, выберите другое действие или обратитесь к администратору'

    return None






def calculate_work_time(user_id, end_time=None):
    """Вычисляет отработанное время и зарплату. Если задано end_time — используется оно вместо текущего времени."""
    if end_time is None:
        end_time = datetime.now()

    records = sheet.get_all_values()
    last_check_in = None
    lunch_start = None
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
            elif row[3] == "Начал обед":
                lunch_start = time_event
                if lunch_end:
                    total_lunch_time += (lunch_end - lunch_start).total_seconds()
                    lunch_start = None
                    lunch_end = None

    # Если обед начался, но не закончился
    if lunch_start:
        total_lunch_time += DEFAULT_LUNCH_TIME
    if lunch_end:
        total_lunch_time += DEFAULT_LUNCH_TIME

    # Если нет прихода — вернуть 0
    if not last_check_in:
        return 0, 0

    work_time = end_time - last_check_in - timedelta(seconds=total_lunch_time)

    if work_time >= timedelta(hours=8) and total_lunch_time == 0:
        work_time -= timedelta(seconds=DEFAULT_LUNCH_TIME)

    work_hours = round(work_time.total_seconds() / 3600, 2)  # Время в часах

    # Получаем почасовую ставку сотрудника
    accounts = sheet_accounts.get_all_values()
    hourly_rate = DEFAULT_HOURLY_RATE  # Значение по умолчанию

    for row in accounts:
        if row[0] == str(user_id):
            try:
                hourly_rate = float(row[2])
            except (IndexError, ValueError):
                pass
            break

    salary = round(work_hours * hourly_rate, 2)  # Заработок
    return work_hours, salary


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


def get_last_event(user_id):
    """Возвращает тип и время последнего события пользователя"""
    records = sheet.get_all_values()
    for row in reversed(records):
        if row[1] == str(user_id):
            event_time = datetime.strptime(row[0], "%d-%m-%Y %H:%M:%S")
            event_type = row[3]
            return event_type, event_time
    return None, None  # если записей нет
