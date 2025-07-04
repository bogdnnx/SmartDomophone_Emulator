import json
import random
import logging
import time
import threading
import requests
import paho.mqtt.client as mqtt
from sqlmodel import Session, create_engine, select
from DomophoneModel import Domophone
#from web_server.models import Domophone as DbDomophone

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Настройки MQTT
BROKER = "mqtt-broker"
PORT = 1883
TOPIC_COMMANDS = "domophone/commands"
TOPIC_STATUS = "domophone/status"
TOPIC_EVENTS = "domophone/events"

# Настройки базы данных
DATABASE_URL = "postgresql://skud_admin:1337@dom_db:5432/domophone_db"
engine = create_engine(DATABASE_URL)

# Загрузка домофонов из базы данных
def load_domophones_from_api():
    for attempt in range(10):
        try:
            response = requests.get("http://web:8000/domophones", timeout=3)
            response.raise_for_status()
            domophones_data = response.json()
            return [
                Domophone(
                    mac_adress=d["mac_adress"],
                    model=d["model"],
                    flats_range=50,
                    adress=d["adress"],
                    status=d["status"] == "online",
                    keys=json.loads(d["keys"]) if d["keys"] else []
                )
                for d in domophones_data
            ]
        except Exception as e:
            print(f"Попытка {attempt+1}: web-сервис недоступен ({e}), жду 3 секунды...")
            time.sleep(3)
    raise RuntimeError("web-сервис так и не стал доступен после 10 попыток")

domophones = load_domophones_from_api()

# MQTT-клиент
client = mqtt.Client(protocol=mqtt.MQTTv5)

# Обработчик подключения
def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        logger.info("Подключено к MQTT-брокеру")
        client.subscribe(TOPIC_COMMANDS)
    else:
        logger.error(f"Ошибка подключения: код {reason_code}")

# Обработчик сообщений
def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        # Находим домофон по маку
        for domophone in domophones:
            if payload.get("mac") == domophone.mac_adress:
                domophone.handle_command(client, payload)
                break
        else:
            logger.warning(f"Домофон не найден для mac {payload.get('mac')}")
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")

# Функция для отправки статусов всех домофонов
def status_loop():
    while True:
        for domophone in domophones:
            domophone.send_status(client)
        time.sleep(30)

# Функция для генерации событий для всех домофонов
def event_loop():
    while True:
        for domophone in domophones:
            event_type = random.choice(["call", "key_used"])
            if event_type == "key_used" and domophone.keys:
                apartments = [a for a in domophone.keys if domophone.keys[a]]
                if apartments:
                    apartment = random.choice(apartments)
                    key_id = random.choice(domophone.keys[apartment])
                    domophone.send_event(client, event_type, apartment=apartment, key_id=key_id)
                else:
                    continue
            else:
                domophone.send_event(client, event_type)
        time.sleep(random.randint(10, 60))

# Главная функция
def main():
    # Подключение обработчиков
    client.on_connect = on_connect
    client.on_message = on_message

    # Подключение к брокеру с повторными попытками
    for attempt in range(5):
        try:
            client.connect(BROKER, PORT, 60)
            logger.info("Успешно подключено к MQTT-брокеру")
            break
        except ConnectionRefusedError as e:
            logger.warning(f"Попытка подключения {attempt+1} не удалась: {e}. Повтор через 5 секунд...")
            time.sleep(5)
    else:
        logger.error("Не удалось подключиться к MQTT-брокеру после 5 попыток")
        return

    # Запуск фонового потока для обработки MQTT
    client.loop_start()

    # Запуск циклов в отдельных потоках
    status_thread = threading.Thread(target=status_loop, daemon=True)
    event_thread = threading.Thread(target=event_loop, daemon=True)
    status_thread.start()
    event_thread.start()

    # Главный цикл для поддержания работы программы
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Завершение работы...")
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()