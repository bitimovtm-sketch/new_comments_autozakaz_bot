import json, time, logging, requests, re

BITRIX = "https://autozakaz.bitrix24.ru/rest/2968/epstb1ztccf45l0n"
TELEGRAM_TOKEN = "8965670792:AAEvQS2flMY32a9q5BTkTMgzE4QEntW_zCM"
CHAT_ID = "112201829"
PROJECT_ID = 52
STATE_FILE = "last_check_state.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

def check_telegram():
    log.info("=== ПРОВЕРКА TELEGRAM ===")
    r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe", timeout=10)
    if r.ok:
        log.info("✓ Telegram бот: @%s", r.json().get("result",{}).get("username","?"))
    else:
        log.error("✗ Токен неверный: %s", r.text); return False
    r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": "🔧 Бот работает!"}, timeout=10)
    if r.ok:
        log.info("✓ Тест отправки OK (chat_id=%s)", CHAT_ID)
    else:
        log.error("✗ Ошибка отправки: %s", r.text); return False
    return True

def check_bitrix():
    log.info("=== ПРОВЕРКА БИТРИКС24 ===")
    r = requests.post(f"{BITRIX}/profile.json", timeout=10)
    if r.ok:
        d = r.json().get("result", {})
        log.info("✓ Вебхук OK: %s %s (ID=%s)", d.get("NAME","?"), d.get("LAST_NAME","?"), d.get("ID","?"))
    else:
        log.error("✗ Вебхук не работает: %s", r.text[:200]); return False
    r = requests.post(f"{BITRIX}/tasks.task.list.json", json={
        "filter": {"GROUP_ID": PROJECT_ID}, "select": ["ID","TITLE"], "start": 0}, timeout=15)
    tasks = r.json().get("result", {}).get("tasks", [])
    if tasks:
        log.info("✓ Задач в проекте %s: %d", PROJECT_ID, len(tasks))
    else:
        log.error("✗ Задачи не найдены. PROJECT_ID=%s", PROJECT_ID); return False
    return True

def get_tasks():
    tasks, start = [], 0
    while True:
        r = requests.post(f"{BITRIX}/tasks.task.list.json", json={
            "filter": {"GROUP_ID": PROJECT_ID}, "select": ["ID","TITLE","CHAT_ID"], "start": start}, timeout=15)
        batch = r.json().get("result", {}).get("tasks", [])
        tasks.extend(batch)
        if len(batch) < 50: break
        start += 50
    log.info("Всего задач: %d", len(tasks))
    return tasks

def get_chat_id_for_task(task_id):
    r = requests.post(f"{BITRIX}/tasks.task.get.json", json={"taskId": task_id, "select": ["ID","CHAT_ID"]}, timeout=15)
    d = r.json().get("result", {}).get("task", {})
    return d.get("chatId") or d.get("CHAT_ID")

def get_chat_messages(chat_id):
    r = requests.post(f"{BITRIX}/im.dialog.messages.get.json", json={
        "DIALOG_ID": f"chat{chat_id}", "LIMIT": 20}, timeout=15)
    res = r.json().get("result", {})
    msgs = res.get("messages", [])
    users_raw = res.get("users", {})
    # users может прийти как список или как словарь
    if isinstance(users_raw, list):
        users = {str(u.get("id","")): u for u in users_raw if isinstance(u, dict)}
    else:
        users = users_raw
    return (msgs if isinstance(msgs, list) else []), users

def is_system(msg):
    author_id = str(msg.get("author_id", "0"))
    text = msg.get("text", "").strip()
    if author_id == "0": return True, "бот"
    if not text: return True, "пусто"
    if "[USER=" in text and any(x in text for x in ["] изменил","] завершил","] вернул","] назначил","] создал"]):
        return True, "системное действие"
    if "[TIMESTAMP=" in text: return True, "timestamp"
    if text.startswith("NOTIFY"): return True, "NOTIFY"
    return False, ""

def clean(text):
    text = re.sub(r'\[USER=\d+\](.*?)\[/USER\]', r'\1', text)
    text = re.sub(r'\[B\](.*?)\[/B\]', r'*\1*', text)
    text = re.sub(r'\[.*?\]', '', text)
    return text.strip()

def send_tg(text):
    r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
    if not r.ok: log.error("✗ Telegram ошибка: %s", r.text[:200])
    return r.ok

def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f: return json.load(f)
    except: return {}

def save_state(s):
    with open(STATE_FILE, "w", encoding="utf-8") as f: json.dump(s, f, ensure_ascii=False, indent=2)

def main():
    log.info("======== ЗАПУСК ========")
    if not check_telegram() or not check_bitrix():
        log.error("Исправьте ошибки выше"); return

    state = load_state()
    first_run = not bool(state)
    log.info("Первый запуск: %s", first_run)

    tasks = get_tasks()
    new_state = dict(state)
    sent = 0

    for task in tasks:
        task_id = str(task.get("id") or task.get("ID",""))
        task_title = task.get("title") or task.get("TITLE","Без названия")
        if not task_id: continue

        chat_id = task.get("chatId") or task.get("CHAT_ID")
        if not chat_id:
            chat_id = get_chat_id_for_task(task_id)
            time.sleep(0.1)
        if not chat_id: continue

        state_key = f"task_{task_id}"
        last_id = int(state.get(state_key, 0))
        msgs, users = get_chat_messages(chat_id)
        time.sleep(0.2)
        if not msgs: continue

        max_id = last_id
        new_msgs = []
        for msg in msgs:
            mid = int(msg.get("id", 0))
            max_id = max(max_id, mid)
            if mid <= last_id or first_run: continue
            filtered, reason = is_system(msg)
            if filtered:
                log.info("  пропущено [%s]: %s", reason, msg.get("text","")[:60])
                continue
            new_msgs.append((msg, users))

        new_state[state_key] = max_id
        if not new_msgs: continue

        log.info("Задача %s (%s): %d новых", task_id, task_title[:40], len(new_msgs))
        for msg, users in new_msgs:
            aid = str(msg.get("author_id",""))
            ui = users.get(aid, {})
            name = f"{ui.get('first_name','')} {ui.get('last_name','')}".strip() or f"#{aid}"
            text = clean(msg.get("text",""))[:800]
            date = msg.get("date","")
            url = f"https://autozakaz.bitrix24.ru/company/personal/user/0/tasks/task/view/{task_id}/"
            tg = f"💬 <b>Новый комментарий</b>\n\n📋 <a href='{url}'>{task_title}</a>\n👤 {name}  🕐 {date}\n\n{text}"
            log.info("  → %s: «%s»", name, text[:50])
            if send_tg(tg): sent += 1
            time.sleep(0.3)

    save_state(new_state)
    log.info("Готово. Отправлено: %d", sent)
    log.info("========================")

main()
