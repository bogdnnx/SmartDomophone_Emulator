import json
import random
import logging
import time
import threading
import paho.mqtt.client as mqtt
from DomophoneModel import Domophone

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

# Инициализация домофона
domophone = Domophone(
    mac_adress="00:11:22:33:44:55",
    model="TopX",
    flats_range=50,
    adress="ул. Ленина, 10",
    status=True,
    keys=[1234, 5678]
)

# MQTT-клиент
client = mqtt.Client(protocol=mqtt.MQTTv5)

# Обработчик подключения
def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        logger.info("Connected to MQTT broker")
        client.subscribe(TOPIC_COMMANDS)
    else:
        logger.error(f"Connection failed with code {reason_code}")

# Обработчик сообщений
def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        domophone.handle_command(client, payload)
    except Exception as e:
        logger.error(f"Error processing message: {e}")

# Функция для отправки статусов
def status_loop():
    while True:
        domophone.send_status(client)
        time.sleep(30)

# Функция для генерации событий
def event_loop():
    while True:
        event_type = random.choice(["call", "key_used"])
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
            logger.info("Successfully connected to MQTT broker")
            break
        except ConnectionRefusedError as e:
            logger.warning(f"Connection attempt {attempt+1} failed: {e}. Retrying in 5 seconds...")
            time.sleep(5)
    else:
        logger.error("Failed to connect to MQTT broker after 5 attempts")
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
        logger.info("Shutting down...")
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()