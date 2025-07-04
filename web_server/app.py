from fastapi import FastAPI, Form, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from sqlmodel import SQLModel, Session, create_engine, select
import paho.mqtt.client as mqtt
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional
from models import Domophone, Event, DomophoneLog
from sqlmodel import Field

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Настройки базы данных
DATABASE_URL = "postgresql://skud_admin:1337@dom_db:5432/domophone_db"
engine = create_engine(DATABASE_URL)

# Настройки MQTT
BROKER = "mqtt-broker"
PORT = 1883
TOPIC_COMMANDS = "domophone/commands"
TOPIC_STATUS = "domophone/status"
TOPIC_EVENTS = "domophone/events"

# MQTT-клиент
client = mqtt.Client(protocol=mqtt.MQTTv5)

# Обработчик подключения
def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        logger.info("Веб-приложение подключено к MQTT-брокеру")
        client.subscribe(TOPIC_STATUS)
        client.subscribe(TOPIC_EVENTS)
    else:
        logger.error(f"Ошибка подключения веб-приложения: код {reason_code}")

# Обработчик сообщений
def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        with Session(engine) as session:
            if msg.topic == TOPIC_STATUS:
                mac = payload.get("mac")
                if mac:
                    domophone = session.exec(select(Domophone).where(Domophone.mac_adress == mac)).first()
                    if not domophone:
                        domophone = Domophone(
                            mac_adress=mac,
                            model=payload.get("model", "Unknown"),
                            adress=payload.get("adress", "Unknown"),
                            status=payload.get("status", "offline"),
                            door_status=payload.get("door_status", "closed"),
                            keys=json.dumps(payload.get("keys", [])),
                            last_seen=datetime.fromtimestamp(payload.get("timestamp", int(time.time()))),
                            is_active=True
                        )
                    else:
                        domophone.model = payload.get("model", domophone.model)
                        domophone.adress = payload.get("adress", domophone.adress)
                        domophone.status = payload.get("status", domophone.status)
                        domophone.door_status = payload.get("door_status", domophone.door_status)
                        domophone.keys = json.dumps(payload.get("keys", json.loads(domophone.keys)))
                        domophone.last_seen = datetime.fromtimestamp(payload.get("timestamp", int(time.time())))
                        # if payload.get("status") == "offline":
                        #     domophone.is_active = False
                        # else:
                        #     domophone.is_active = True
                    session.add(domophone)
                    session.commit()
                    logger.info(f"Сохранён статус для {mac}: {payload}")
                    log = DomophoneLog(
                        mac_adress=mac,
                        log_time=datetime.now(),
                        status=payload.get("status", "unknown"),
                        door_status=payload.get("door_status", "unknown"),
                        keys=json.dumps(payload.get("keys", [])),
                        message=str(payload)
                    )
                    session.add(log)
                    session.commit()
            elif msg.topic == TOPIC_EVENTS:
                mac = payload.get("mac")
                event_type = payload.get("event")
                if mac and event_type:
                    event = Event(
                        mac_adress=mac,
                        event_type=event_type,
                        apartment=payload.get("apartment"),
                        key_id=payload.get("key_id"),
                        timestamp=datetime.fromtimestamp(payload.get("timestamp", int(time.time())))
                    )
                    session.add(event)
                    session.commit()
                    logger.info(f"Сохранено событие для {mac}: {payload}")
    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")

# Проверка неактивных домофонов
status_offline_since = {}  # Словарь для отслеживания времени перехода в "offline"

def check_inactive_domophones():
    while True:
        with Session(engine) as session:
            for domophone in session.exec(select(Domophone)).all():
                if not domophone.status:
                    # Если домофон только что перешёл в "offline", фиксируем время
                    if domophone.mac_adress not in status_offline_since:
                        status_offline_since[domophone.mac_adress] = time.time()
                    # Проверяем, прошло ли более 120 секунд
                    elif time.time() - status_offline_since[domophone.mac_adress] > 120:
                        domophone.is_active = False
                        session.add(domophone)  # Добавляем изменения в сессию
                        # Публикуем событие
                        client.publish("domophone/events", payload=json.dumps({"event": "check_unactivity", "mac": domophone.mac_adress}))
                else:
                    # Если домофон "online", убираем его из словаря
                    if domophone.mac_adress in status_offline_since:
                        status_offline_since.pop(domophone.mac_adress)
            session.commit()  # Сохраняем изменения в базе данных
        time.sleep(5)

# Инициализация
def init():
    SQLModel.metadata.create_all(engine)
    client.on_connect = on_connect
    client.on_message = on_message
    for attempt in range(5):
        try:
            client.connect(BROKER, PORT, 60)
            logger.info("Веб-приложение успешно подключено к MQTT-брокеру")
            break
        except ConnectionRefusedError as e:
            logger.warning(f"Попытка подключения {attempt+1} не удалась: {e}. Повтор через 5 секунд...")
            time.sleep(5)
    else:
        logger.error("Не удалось подключиться к MQTT-брокеру после 5 попыток")
    client.loop_start()
    import threading
    threading.Thread(target=check_inactive_domophones, daemon=True).start()

@app.on_event("startup")
def on_startup():
    init()

@app.get("/")
def index(request: Request):
    with Session(engine) as session:
        domophones = session.exec(select(Domophone).order_by(Domophone.model)).all()
        events = session.exec(select(Event).order_by(Event.timestamp.desc()).limit(25)).all()
        logs = session.exec(select(DomophoneLog).order_by(DomophoneLog.log_time.desc()).limit(12)).all()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "domophones": domophones,
        "events": events,
        "logs": logs
    })


@app.get("/domophones")
def get_all_domophones():
    with Session(engine) as session:
        domophones = session.exec(select(Domophone)).all()
    return domophones

@app.post("/command")
def send_command(mac_adress: str = Form(...), command: str = Form(...), keys: str = Form(None), flat_number: str = Form(None), apartment: str = Form(None)):
    try:
        payload = {"mac": mac_adress, "command": command}
        if payload["command"] == "add_keys":
            if not keys or not apartment:
                return JSONResponse({"error": "Не указаны квартира или ключи"}, status_code=400)
            try:
                apartment_int = int(apartment)
                if apartment_int < 1:
                    raise ValueError
                keys_list = [int(k.strip()) for k in keys.split(",") if k.strip()]
            except Exception:
                return JSONResponse({"error": "Квартира и ключи должны быть числами, ключи через запятую"}, status_code=400)
            payload["apartment"] = apartment_int
            payload["keys"] = keys_list
        elif payload["command"] == "remove_keys":
            if not keys or not apartment:
                return JSONResponse({"error": "Не указаны квартира или ключи для удаления"}, status_code=400)
            try:
                apartment_int = int(apartment)
                if apartment_int < 1:
                    raise ValueError
                keys_list = [int(k.strip()) for k in keys.split(",") if k.strip()]
            except Exception:
                return JSONResponse({"error": "Квартира и ключи должны быть числами, ключи через запятую"}, status_code=400)
            payload["apartment"] = apartment_int
            payload["keys"] = keys_list
        elif payload["command"] == "call_to_flat":
            if not flat_number:
                return JSONResponse({"error": "Не указан номер квартиры"}, status_code=400)
            try:
                flat_number_int = int(flat_number)
                if flat_number_int < 1:
                    raise ValueError
            except Exception:
                return JSONResponse({"error": "Номер квартиры должен быть положительным целым числом"}, status_code=400)
            payload["flat_number"] = flat_number_int
        client.publish(TOPIC_COMMANDS, json.dumps(payload))
        logger.info(f"Отправлена команда: {payload}")
        return JSONResponse({"status": "Команда отправлена"})
    except Exception as e:
        logger.error(f"Ошибка отправки команды: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)