import json, time, logging, requests, re

BITRIX = "https://autozakaz.bitrix24.ru/rest/2968/epstb1ztccf45l0n"
TELEGRAM_TOKEN = "8965670792:AAEvQS2flMY32a9q5BTkTMgzE4QEntW_zCM"
CHAT_ID = "112201829"
PROJECT_ID = 52
STATE_FILE = "last_check_state.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)


# ─── ДИАГНОСТИКА ───────────────────────────────────────────

def check_telegram():
    log.info("=== ПРОВЕРКА TELEGRAM ===")
    try:
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe", timeout=10)
        if r.ok:
            name = r.json().get("result", {}).get("username", "?")
            log.info("✓ Telegram бот работает: @%s", name)
        else:
            log.error("✗ Telegram токен неверный: %s", r.text)
            return False
    except Exception as e:
        log.error("✗ Telegram недоступен: %s", e)
        return False

    # Тест отправки
    r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
        "chat_id": CHAT_ID, "text": "🔧 Диагностика: бот работает!"
    }, timeout=10)
    if r.ok:
        log.info("✓ Тестовое сообщение отправлено в Telegram (chat_id=%s)", CHAT_ID)
    else:
        log.error("✗ Не удалось отправить в Telegram: %s", r.text)
        log.error("  Скорее всего неверный CHAT_ID. Напишите боту /start и проверьте getUpdates")
        return False
    return True


def check_bitrix():
    log.info("=== ПРОВЕРКА БИТРИКС24 ===")
    try:
        r = requests.post(f"{BITRIX}/profile.json", timeout=10)
        if r.ok:
            data = r.json().get("result", {})
            log.info("✓ Вебхук работает. Пользователь: %s %s (ID=%s)",
                     data.get("NAME","?"), data.get("LAST_NAME","?"), data.get("ID","?"))
        else:
            log.error("✗ Вебхук не работает: %s", r.text[:200])
            return False
    except Exception as e:
        log.error("✗ Битрикс недоступен: %s", e)
        return False

    # Проверка задач
    r = requests.post(f"{BITRIX}/tasks.task.list.json", json={
        "filter": {"GROUP_ID": PROJECT_ID}, "select": ["ID","TITLE"], "start": 0
    }, timeout=15)
    tasks = r.json().get("result", {}).get("tasks", [])
    if tasks:
        log.info("✓ Найдено задач в проекте %s: %d (первая: %s)",
                 PROJECT_ID, len(tasks), tasks[0].get("title") or tasks[0].get("TITLE","?"))
    else:
        log.error("✗ Задачи не найдены. Проверьте PROJECT_ID=%s", PROJECT_ID)
        return False
    return True


# ─── ОСНОВНЫЕ ФУНКЦИИ ──────────────────────────────────────

def get_tasks():
    tasks = []
    start = 0
    while True:
        r = requests.post(f"{BITRIX}/tasks.task.list.json", json={
            "filter": {"GROUP_ID": PROJECT_ID},
            "select": ["ID", "TITLE", "CHAT_ID"],
            "start": start
        }, timeout=15)
        batch = r.json().get("result", {}).get("tasks", [])
        tasks.extend(batch)
        if len(batch) < 50:
            break
        start += 50
    log.info("Найдено задач: %d", len(tasks))
    return tasks


def get_chat_id_for_task(task_id):
    r = requests.post(f"{BITRIX}/tasks.task.get.json", json={
        "taskId": task_id, "select": ["ID", "CHAT_ID"]
    }, timeout=15)
    data = r.json().get("result", {}).get("task", {})
    return data.get("chatId") or data.get("CHAT_ID")


def get_chat_messages(chat_id):
    r = requests.post(f"{BITRIX}/im.dialog.messages.get.json", json={
        "DIALOG_ID": f"chat{chat_id}", "LIMIT": 20
    }, timeout=15)
    result = r.json().get("result", {})
    msgs = result.get("messages", [])
    users = result.get("users", {})
    return msgs if isinstance(msgs, list) else [], users


def is_system_message(msg):
    author_id = str(msg.get("author_id", "0"))
    text = msg.get("text", "").strip()
    if author_id == "0":
        return True, "автор = бот (id=0)"
    if not text:
        return True, "пустой текст"
    if "[USER=" in text and any(x in text for x in ["] изменил", "] завершил", "] вернул", "] назначил", "] создал"]):
        return True, "системное действие"
    if "[TIMESTAMP=" in text:
        return True, "содержит timestamp"
    if text.startswith("NOTIFY"):
        return True, "NOTIFY сообщение"
    return False, ""


def clean_text(text):
    text = re.sub(r'\[USER=\d+\](.*?)\[/USER\]', r'\1', text)
    text = re.sub(r'\[B\](.*?)\[/B\]', r'*\1*', text)
    text = re.sub(r'\[.*?\]', '', text)
    return text.strip()


def send_tg(text):
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=10
    )
    if not r.ok:
        log.error("✗ Ошибка отправки в Telegram: %s", r.text[:200])
    return r.ok


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ─── ГЛАВНАЯ ФУНКЦИЯ ───────────────────────────────────────

def main():
    log.info("========================================")
    log.info("ЗАПУСК БОТА")
    log.info("========================================")

    # Диагностика при каждом запуске
    tg_ok = check_telegram()
    bx_ok = check_bitrix()

    if not tg_ok or not bx_ok:
        log.error("Исправьте ошибки выше и запустите снова")
        return

    log.info("=== ПРОВЕРКА НОВЫХ СООБЩЕНИЙ ===")

    state = load_state()
    first_run = not bool(state)
    log.info("Первый запуск: %s", first_run)

    tasks = get_tasks()
    new_state = dict(state)
    sent = 0

    for task in tasks:
        task_id = str(task.get("id") or task.get("ID", ""))
        task_title = task.get("title") or task.get("TITLE", "Без названия")
        if not task_id:
            continue

        chat_id = task.get("chatId") or task.get("CHAT_ID")
        if not chat_id:
            chat_id = get_chat_id_for_task(task_id)
            time.sleep(0.1)

        if not chat_id:
            continue

        state_key = f"task_{task_id}"
        last_msg_id = int(state.get(state_key, 0))

        msgs, users = get_chat_messages(chat_id)
        time.sleep(0.2)

        if not msgs:
            continue

        max_id = last_msg_id
        new_msgs = []

        for msg in msgs:
            msg_id = int(msg.get("id", 0))
            max_id = max(max_id, msg_id)
            if msg_id <= last_msg_id or first_run:
                continue
            filtered, reason = is_system_message(msg)
            if filtered:
                log.info("  [%s] пропущено (%s): %s", task_id, reason, msg.get("text","")[:60])
                continue
            new_msgs.append((msg, users))

        new_state[state_key] = max_id

        if not new_msgs:
            continue

        log.info("Задача %s (%s): новых сообщений %d", task_id, task_title[:40], len(new_msgs))

        for msg, users in new_msgs:
            author_id = str(msg.get("author_id", ""))
            author_info = users.get(author_id, {})
            first = author_info.get("first_name", "")
            last = author_info.get("last_name", "")
            author_name = f"{first} {last}".strip() or f"Пользователь #{author_id}"

            text = clean_text(msg.get("text", ""))[:800]
            date = msg.get("date", "")
            task_url = f"https://autozakaz.bitrix24.ru/company/personal/user/0/tasks/task/view/{task_id}/"

            tg_text = (
                f"💬 <b>Новый комментарий</b>\n\n"
                f"📋 <a href='{task_url}'>{task_title}</a>\n"
                f"👤 {author_name}  🕐 {date}\n\n"
                f"{text}"
            )
            log.info("  Отправляю: %s — «%s»", author_name, text[:50])
            if send_tg(tg_text):
                sent += 1
            time.sleep(0.3)

    save_state(new_state)
    log.info("========================================")
    if first_run:
        log.info("Первый запуск завершён. Новые сообщения будут приходить со следующего запуска.")
    else:
        log.info("Готово. Отправлено уведомлений: %d", sent)
    log.info("========================================")


main()
