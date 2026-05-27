import json, time, logging, requests

BITRIX = "https://autozakaz.bitrix24.ru/rest/2968/epstb1ztccf45l0n"
TELEGRAM_TOKEN = "8965670792:AAEvQS2flMY32a9q5BTkTMgzE4QEntW_zCM"
CHAT_ID = "625135175"
PROJECT_ID = 52
STATE_FILE = "last_check_state.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

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
    """Получить ID чата задачи"""
    r = requests.post(f"{BITRIX}/tasks.task.get.json", json={
        "taskId": task_id,
        "select": ["ID", "TITLE", "FORUM_TOPIC_ID", "CHAT_ID"]
    }, timeout=15)
    data = r.json().get("result", {}).get("task", {})
    chat_id = data.get("chatId") or data.get("CHAT_ID")
    return chat_id

def get_chat_messages(chat_id, last_message_id=0):
    """Получить сообщения из чата задачи"""
    r = requests.post(f"{BITRIX}/im.dialog.messages.get.json", json={
        "DIALOG_ID": f"chat{chat_id}",
        "LIMIT": 20
    }, timeout=15)
    data = r.json()
    messages = data.get("result", {}).get("messages", [])
    return messages if isinstance(messages, list) else []

def is_system_message(msg):
    """Фильтр системных сообщений"""
    author_id = str(msg.get("author_id", "0"))
    text = msg.get("text", "").strip()

    # Только явно системные — от бота
    if author_id == "0":
        return True
    if not text:
        return True
    return False

def clean_text(text):
    """Убрать служебные теги Битрикс из текста"""
    import re
    text = re.sub(r'\[USER=\d+\](.*?)\[/USER\]', r'\1', text)
    text = re.sub(r'\[B\](.*?)\[/B\]', r'*\1*', text)
    text = re.sub(r'\[U\](.*?)\[/U\]', r'\1', text)
    text = re.sub(r'\[.*?\]', '', text)
    return text.strip()

def send_tg(text):
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=10
    )
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

def main():
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

        # Получаем chat_id задачи
        chat_id = task.get("chatId") or task.get("CHAT_ID")
        if not chat_id:
            chat_id = get_chat_id_for_task(task_id)
            time.sleep(0.1)

        if not chat_id:
            log.info("Задача %s: чат не найден", task_id)
            continue

        state_key = f"task_{task_id}"
        last_msg_id = int(state.get(state_key, 0))

        messages = get_chat_messages(chat_id, last_msg_id)
        time.sleep(0.2)

        if not messages:
            continue

        max_id = last_msg_id
        new_messages = []

        for msg in messages:
            msg_id = int(msg.get("id", 0))
            max_id = max(max_id, msg_id)

            if msg_id <= last_msg_id or first_run:
                continue
            if is_system_message(msg):
                continue

            new_messages.append(msg)

        new_state[state_key] = max_id

        if not new_messages:
            continue

        log.info("Задача %s (%s): новых сообщений %d", task_id, task_title[:30], len(new_messages))

        for msg in new_messages:
            users = messages[0].get("users", {}) if messages else {}
            author_id = str(msg.get("author_id", ""))
            author_info = users.get(author_id, {})
            first = author_info.get("first_name", "")
            last = author_info.get("last_name", "")
            author_name = f"{first} {last}".strip() or "Сотрудник"

            text = clean_text(msg.get("text", ""))[:800]
            date = msg.get("date", "")
            task_url = f"https://autozakaz.bitrix24.ru/company/personal/user/0/tasks/task/view/{task_id}/"

            tg_text = (
                f"💬 <b>Новый комментарий</b>\n\n"
                f"📋 <a href='{task_url}'>{task_title}</a>\n"
                f"👤 {author_name}  🕐 {date}\n\n"
                f"{text}"
            )
            if send_tg(tg_text):
                sent += 1
            time.sleep(0.3)

    save_state(new_state)
    if first_run:
        log.info("Первый запуск завершён. Новые сообщения будут приходить со следующего запуска.")
    else:
        log.info("Готово. Отправлено: %d", sent)

main()
