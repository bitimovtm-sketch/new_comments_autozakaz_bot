import json, time, logging, requests, re

BITRIX = "https://autozakaz.bitrix24.ru/rest/2968/epstb1ztccf45l0n"
TELEGRAM_TOKEN = "8965670792:AAEvQS2flMY32a9q5BTkTMgzE4QEntW_zCM"
CHAT_ID = "112201829"
PROJECT_ID = 52
STATE_FILE = "last_check_state.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

log.info("=== СТАРТ ===")
log.info("Проверяю Telegram...")

r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getMe", timeout=10)
log.info("Telegram getMe: %s %s", r.status_code, r.text[:100])

r2 = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
    json={"chat_id": CHAT_ID, "text": "тест отправки"}, timeout=10)
log.info("Telegram sendMessage: %s %s", r2.status_code, r2.text[:200])
