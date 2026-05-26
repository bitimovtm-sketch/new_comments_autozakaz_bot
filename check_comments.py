import json, time, logging, requests

BITRIX = "https://autozakaz.bitrix24.ru/rest/2968/zvtlkvgkhnf7xwuu"
TELEGRAM_TOKEN = "8965670792:AAEvQS2flMY32a9q5BTkTMgzE4QEntW_zCM"
CHAT_ID = "625135175"
PROJECT_ID = 52
STATE_FILE = "last_check_state.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

def get_tasks():
    url = f"{BITRIX}/tasks.task.list.json"
    r = requests.post(url, json={"filter": {"GROUP_ID": PROJECT_ID}, "select": ["ID","TITLE"]}, timeout=15)
    log.info("tasks response status: %s", r.status_code)
    log.info("tasks response: %s", r.text[:300])
    data = r.json()
    return data.get("result", {}).get("tasks", [])

def get_comments(task_id):
    url = f"{BITRIX}/task.commentitem.getlist.json"
    r = requests.post(url, json={"TASKID": task_id, "ORDER": {"ID": "ASC"}}, timeout=15)
    data = r.json()
    result = data.get("result", [])
    return result if isinstance(result, list) else []

def is_system(comment):
    author_id = str(comment.get("AUTHOR_ID", "0"))
    msg = comment.get("POST_MESSAGE", "").strip()
    if author_id == "0" or not msg or "[HISTORY]" in msg:
        return True
    system_words = ["изменил", "изменила", "изменили", "deadline", "status changed"]
    msg_low = msg.lower()
    words = [w for w in msg.split() if len(w) > 3]
    if len(words) < 5 and len(msg) < 120 and any(p in msg_low for p in system_words):
        return True
    return False

def send_tg(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    log.info("telegram response: %s %s", r.status_code, r.text[:200])
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
    log.info("Найдено задач: %d", len(tasks))

    new_state = dict(state)
    sent = 0

    for task in tasks:
        task_id = str(task["ID"])
        comments = get_comments(int(task_id))
        log.info("Задача %s (%s): комментариев %d", task_id, task.get("TITLE","")[:30], len(comments))

        last_id = int(state.get(task_id, 0))
        max_id = last_id

        for c in comments:
            cid = int(c.get("ID", 0))
            max_id = max(max_id, cid)
            if cid <= last_id or first_run:
                continue
            if is_system(c):
                log.info("  пропущен системный комментарий #%d", cid)
                continue

            author = c.get("AUTHOR", {})
            name = f"{author.get('NAME','')} {author.get('LAST_NAME','')}".strip() or "Сотрудник"
            msg = c.get("POST_MESSAGE", "").strip()[:800]
            date = c.get("POST_DATE", "")

            text = f"💬 <b>Новый комментарий</b>\n\n📋 <b>{task['TITLE']}</b>\n👤 {name}  🕐 {date}\n\n{msg}"
            if send_tg(text):
                sent += 1
            time.sleep(0.3)

        new_state[task_id] = max_id

    save_state(new_state)
    if first_run:
        log.info("Первый запуск завершён — состояние сохранено. Новые комментарии будут приходить со следующего запуска.")
    else:
        log.info("Готово. Отправлено: %d", sent)

main()
