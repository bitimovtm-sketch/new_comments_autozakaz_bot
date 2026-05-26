"""
Битрикс24 → Telegram: проверка новых комментариев к задачам проекта.
Все настройки берутся из переменных окружения (GitHub Secrets).
"""

import os, json, time, logging, requests

# Настройки из GitHub Secrets (заполняете один раз в интерфейсе GitHub)
BITRIX_WEBHOOK_URL = os.environ["BITRIX_WEBHOOK_URL"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
PROJECT_ID         = int(os.environ["PROJECT_ID"])

STATE_FILE = "last_check_state.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def bitrix(method, params):
    url = f"{BITRIX_WEBHOOK_URL.rstrip('/')}/{method}"
    try:
        r = requests.post(url, json=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            log.error("Битрикс ошибка: %s %s", data.get("error"), data.get("error_description"))
            return {}
        return data.get("result", {})
    except Exception as e:
        log.error("Ошибка запроса %s: %s", method, e)
        return {}


def send_tg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=10)
        return r.ok
    except Exception as e:
        log.error("Telegram ошибка: %s", e)
        return False


def get_tasks():
    tasks, start = [], 0
    while True:
        result = bitrix("tasks.task.list", {
            "filter": {"GROUP_ID": PROJECT_ID},
            "select": ["ID", "TITLE"],
            "start": start
        })
        batch = result.get("tasks", []) if result else []
        tasks.extend(batch)
        if len(batch) < 50:
            break
        start += 50
    log.info("Задач 'В работе': %d", len(tasks))
    return tasks


def get_comments(task_id):
    result = bitrix("task.commentitem.getlist", {
        "TASKID": task_id,
        "ORDER": {"ID": "ASC"}
    })
    return result if isinstance(result, list) else []


def is_system(comment):
    author_id = str(comment.get("AUTHOR_ID", "0"))
    msg = comment.get("POST_MESSAGE", "").strip()
    if author_id == "0" or not msg or "[HISTORY]" in msg:
        return True
    system_words = ["изменил", "изменила", "изменили", "deadline", "status changed", "description changed"]
    msg_low = msg.lower()
    words = [w for w in msg.split() if len(w) > 3]
    if len(words) < 5 and len(msg) < 120 and any(p in msg_low for p in system_words):
        return True
    return False


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def main():
    state = load_state()
    tasks = get_tasks()

    if not tasks:
        log.warning("Задачи не найдены. Проверьте PROJECT_ID и права вебхука.")
        return

    first_run = not os.path.exists(STATE_FILE)
    new_state = dict(state)
    sent = 0
    base_url = BITRIX_WEBHOOK_URL.split("/rest/")[0]

    for task in tasks:
        task_id = str(task["ID"])
        comments = get_comments(int(task_id))
        last_id = int(state.get(task_id, 0))
        max_id = last_id

        for c in comments:
            cid = int(c.get("ID", 0))
            max_id = max(max_id, cid)
            if cid <= last_id or first_run:
                continue
            if is_system(c):
                continue

            author = c.get("AUTHOR", {})
            name = f"{author.get('NAME','')} {author.get('LAST_NAME','')}".strip() or "Сотрудник"
            msg = c.get("POST_MESSAGE", "").strip()[:800]
            date = c.get("POST_DATE", "")
            task_url = f"{base_url}/company/personal/user/0/tasks/task/view/{task_id}/"

            text = (
                f"💬 <b>Новый комментарий</b>\n\n"
                f"📋 <a href='{task_url}'>{task['TITLE']}</a>\n"
                f"👤 <b>{name}</b>  🕐 {date}\n\n"
                f"{msg}"
            )
            if send_tg(text):
                sent += 1
                log.info("Отправлено: задача %s, комментарий #%d", task_id, cid)
            time.sleep(0.3)

        new_state[task_id] = max_id

    save_state(new_state)
    if first_run:
        log.info("Первый запуск — состояние инициализировано. Новые комментарии будут приходить со следующего запуска.")
    else:
        log.info("Готово. Отправлено уведомлений: %d", sent)


if __name__ == "__main__":
    main()
