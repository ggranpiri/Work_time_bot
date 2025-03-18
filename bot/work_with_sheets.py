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
        sheet.append_row([time, user_id, name, "Уход", f"{work_hours} ч", f"{salary} руб."])

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

    messages = []
    if event == "Приход" and last_event_type != "Уход":
        if last_event.date() < datetime.now().date():
            # Если приход был в прошедший день → закрываем смену в 19:00
            auto_checkout_time = datetime.combine(
                last_event.date(), datetime.strptime(AUTO_CHECK_OUT_TIME, "%H:%M:%S").time()
            )
            log_event(user_id, user_name, "Уход", auto_checkout_time)
            messages.append(
                f"Смена за {last_event.strftime('%d-%m-%Y')} автоматически закрыта в {AUTO_CHECK_OUT_TIME}.")

        elif last_event.date() == datetime.now().date():
            # Если приход был сегодня → закрываем смену сейчас и сразу добавляем новый приход
            current_time = datetime.now()
            log_event(user_id, user_name, "Уход", current_time)

            messages.append(f"Смена закрыта в {current_time.strftime('%H:%M')} и сразу начата новая смена.")



    elif event == "Уход" and last_event_type not in ["Закончил обед"]:
        # Если последнее событие — "Начал обед", но нет "Закончил обед" → добавляем "Закончил обед"
        if last_event_type == "Начал обед":
            time = datetime.now()
            log_event(user_id, user_name, "Закончил обед", time)
            messages.append(f"Автоматически закончен обед в {time.strftime('%H:%M')}")

        if last_event_type == "Уход":
            if last_event.date() != datetime.now().date():
                auto_checkin_time = datetime.combine(datetime.now().date(),
                                                     datetime.strptime(AUTO_CHECK_IN_TIME, "%H:%M:%S").time())

                log_event(user_id, user_name, "Приход", auto_checkin_time)
                messages.append(f"Автоматически открыта смена за {last_event.strftime('%d-%m-%Y')}")
            else:
                current_time = datetime.now()
                log_event(user_id, user_name, "Приход", current_time)
                messages.append(f"Смена автоматически открыта в {current_time.strftime('%H:%M')}")
        if last_event_type == "Приход":
            if last_event.date() != datetime.now().date():
                auto_checkin_time = datetime.combine(datetime.now().date(),
                                                     datetime.strptime(AUTO_CHECK_IN_TIME, "%H:%M:%S").time())
                auto_checkout_time = datetime.combine(last_event.date(),
                                                     datetime.strptime(AUTO_CHECK_OUT_TIME, "%H:%M:%S").time())
                log_event(user_id, user_name, "Уход", auto_checkout_time)
                log_event(user_id, user_name, "Приход", auto_checkin_time)
                messages.append(f"Автоматически закрыта смена за {last_event.strftime('%d-%m-%Y')} и открыта за сегодня")



    elif event in "Начал обед" and last_event_type not in ["Закончил обед", "Приход"]:
        # Если последнее событие — "Начал обед", но нет "Закончил обед" → добавляем "Закончил обед"
        if last_event_type == "Начал обед":
            time = datetime.now() + timedelta(seconds=DEFAULT_LUNCH_TIME)
            log_event(user_id, user_name, "Закончил обед", time)
            messages.append(f"Автоматически закончен обед в {time.strftime('%H:%M')}.")

        if last_event_type == "Уход":
            if last_event.date() != datetime.now().date():
                # Если обед начался в другой день, открываем смену и фиксируем обед
                auto_checkin_time = datetime.combine(datetime.now().date(),
                                                     datetime.strptime(AUTO_CHECK_IN_TIME, "%H:%M:%S").time())

                log_event(user_id, user_name, "Приход", auto_checkin_time)
                messages.append(f"Автоматически открыта смена за {datetime.now().strftime('%d-%m-%Y')} и начат обед в {datetime.now().strftime('%H:%M')}.")
            else:
                current_time = datetime.now()
                log_event(user_id, user_name, "Приход", current_time)
                messages.append(f"Смена автоматически открыта в {current_time.strftime('%H:%M')}")

    elif event == "Закончил обед" and last_event_type not in ["Начал обед"]:
        min_lunch_start_time = datetime.now() - timedelta(seconds=DEFAULT_LUNCH_TIME)

        for row in reversed(records):
            if row[1] == str(user_id) and row[3] == "Приход":
                last_check_in = datetime.strptime(row[0], "%d-%m-%Y %H:%M:%S")
                min_lunch_start_time = min(last_check_in, min_lunch_start_time)
                break

        log_event(user_id, user_name, "Начал обед", min_lunch_start_time)
        messages.append(f"Автоматически добавлено 'Начал обед' в {min_lunch_start_time.strftime('%H:%M')}.")

    return "\n".join(messages) if messages else None


def calculate_work_time(user_id):
    """Вычисляет отработанное время и зарплату"""
    records = sheet.get_all_values()  # Загружаем все записи
    last_check_in = None
    last_check_out = None
    lunch_start = None
    lunch_end = None
    total_lunch_time = 0  # Время обеда в секундах

    for row in reversed(records):  # Читаем таблицу с конца
        if row[1] == str(user_id):  # Запись для пользователя
            time_event = datetime.strptime(row[0], "%d-%m-%Y %H:%M:%S")

            if row[3] == "Приход":
                last_check_in = time_event
                break
            elif row[3] == "Уход":
                last_check_out = time_event
                break
            elif row[3] == "Закончил обед":
                lunch_end = time_event
            elif row[3] == "Начал обед":
                lunch_start = time_event
                if lunch_end:
                    total_lunch_time += (lunch_end - lunch_start).total_seconds()
                    lunch_end = None
                    lunch_start = None


    if lunch_start:
        total_lunch_time += DEFAULT_LUNCH_TIME
    if lunch_end:
        total_lunch_time += DEFAULT_LUNCH_TIME

    work_time = datetime.now() - last_check_in - timedelta(seconds=total_lunch_time)

    if work_time >= timedelta(hours=8) and not total_lunch_time:
        work_time -= timedelta(seconds=DEFAULT_LUNCH_TIME)

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
