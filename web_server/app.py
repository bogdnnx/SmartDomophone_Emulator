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
from models import Domophone, Event

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

# # Список домофонов (для начальной инициализации и интерфейса)
# DOMOPHONES = [
#     {"mac_adress": "00:11:22:33:44:55", "name": "Домофон 1 "},
#     {"mac_adress": "00:11:22:33:44:66", "name": "Домофон 2 "},
#     {"mac_adress": "00:11:22:33:44:77", "name": "Домофон 3 "}
# ]

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
                        domophone.is_active = True
                    session.add(domophone)
                    session.commit()
                    logger.info(f"Сохранён статус для {mac}: {payload}")
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
def check_inactive_domophones():
    while True:
        with Session(engine) as session:
            for domophone in session.exec(select(Domophone)).all():
                if domophone.last_seen < datetime.now() - timedelta(minutes=2):
                    domophone.is_active = False
                    session.add(domophone)
            session.commit()
        time.sleep(60)

# Инициализация
def init():
    SQLModel.metadata.create_all(engine)
    for domophone in DOMOPHONES:
        with Session(engine) as session:
            if not session.exec(select(Domophone).where(Domophone.mac_adress == domophone["mac_adress"])).first():
                session.add(Domophone(
                    mac_adress=domophone["mac_adress"],
                    model="Unknown",
                    adress=domophone["name"].split("(")[1][:-1],
                    status="offline",
                    door_status="closed",
                    keys="[]",
                    last_seen=datetime.now(),
                    is_active=False
                ))
                session.commit()
    client.on_connect = on_connect
    client.on_message = on_message
    for attempt in range(5):
        try:
            client.connect(BROKER, PORT, 60)
            logger.info("Веб-приложение успешно подключено к MQTT-брок ngu")
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
    return templates.TemplateResponse("index.html", {
        "request": request,
        "domophones": domophones,
        "events": events,
        "domophone_names": {d["mac_adress"]: d["name"] for d in DOMOPHONES}
    })

@app.post("/command")
def send_command(mac_adress: str = Form(...), command: str = Form(...)):
    try:
        if mac_adress not in [d["mac_adress"] for d in DOMOPHONES]:
            return JSONResponse({"error": "Выбран неверный домофон"}, status_code=400)
        # if command != "open_door":
        #     return JSONResponse({"error": "Поддерживается только команда open_door"}, status_code=400)
        payload = {"mac": mac_adress, "command": command}
        client.publish(TOPIC_COMMANDS, json.dumps(payload))
        logger.info(f"Отправлена команда: {payload}")
        return JSONResponse({"status": "Команда отправлена"})
    except Exception as e:
        logger.error(f"Ошибка отправки команды: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)