import json
import random
import logging
import time
from typing import List, Optional, Dict, Any, Protocol
import paho.mqtt.client as mqtt
from click import command

# Настройка логированияё    !
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class EventStrategy(Protocol):
    """Базовый класс для стратегий генерации событий."""
    def generate_event(self, domophone, client: mqtt.Client) -> Dict[str, Any]:
        ...

class CallEventStrategy:
    """Стратегия для события звонка."""
    def generate_event(self, domophone, client: mqtt.Client) -> Dict[str, Any]:
        event = {
            "event": "call",
            "mac": domophone.mac_adress,
            "apartment": random.choice(list(range(1, domophone.flats_range + 1))),
            "timestamp": int(time.time())
        }
        return event

class KeyUsedEventStrategy:
    """Стратегия для события использования ключа."""
    def generate_event(self, domophone, client: mqtt.Client, apartment: int = None, key_id: int = None) -> Dict[str, Any]:
        # Если параметры не переданы, выбираем случайно
        if not domophone.keys:
            logger.warning(f"No keys available for domophone {domophone.mac_adress}")
            return {}
        if apartment is None or key_id is None:
            # Выбираем случайную квартиру и ключ
            apartments = [a for a in domophone.keys if domophone.keys[a]]
            if not apartments:
                logger.warning(f"No apartments with keys for domophone {domophone.mac_adress}")
                return {}
            apartment = random.choice(apartments)
            key_id = random.choice(domophone.keys[apartment])
        event = {
            "event": "key_used",
            "mac": domophone.mac_adress,
            "apartment": apartment,
            "key_id": key_id,
            "timestamp": int(time.time())
        }
        return event

class DoorOpenedEventStrategy:
    """Стратегия для события открытия двери."""
    def generate_event(self, domophone, client: mqtt.Client) -> Dict[str, Any]:
        event = {
            "event": "door_opened",
            "mac": domophone.mac_adress,
            "timestamp": int(time.time())
        }
        return event

class Domophone:
    """Класс для эмуляции домофона с поддержкой MQTT."""
    def __init__(
        self,
        mac_adress: str,
        model: str,
        flats_range: int,
        adress: str,
        status: bool = False,
        keys: Optional[Dict[int, List[int]]] = None,
        magnit_status: bool = True
    ):
        self.mac_adress = mac_adress
        self.model = model
        self.flats_range = flats_range
        self.adress = adress
        self.status = status
        self.keys = keys if keys is not None else {}  # {apartment: [key_id, ...]}
        self.magnit_status = magnit_status
        self.event_strategies = {
            "call": CallEventStrategy(),
            "key_used": KeyUsedEventStrategy(),
            "door_opened": DoorOpenedEventStrategy()
        }
        logger.info(f"Domophone initialized: {self.mac_adress}")

    def add_keys(self, apartment: int, key_ids: List[int]) -> None:
        if apartment not in self.keys:
            self.keys[apartment] = []
        for key_id in key_ids:
            if key_id not in self.keys[apartment]:
                self.keys[apartment].append(key_id)
        logger.info(f"Added keys {key_ids} to apartment {apartment} for domophone {self.mac_adress}")

    def remove_keys(self, apartment: int, key_ids: List[int], client):
        if apartment in self.keys:
            self.keys[apartment] = [k for k in self.keys[apartment] if k not in key_ids]
            if not self.keys[apartment]:
                del self.keys[apartment]
            logger.info(f"Removed keys {key_ids} from apartment {apartment} for domophone {self.mac_adress}")
            self.send_status(client)

    # def open_by_key(self, apartment: int, key_id: int, client: mqtt.Client) -> None:
    #     if apartment not in self.keys or key_id not in self.keys[apartment]:
    #         logger.warning(f"Key {key_id} not programmed for apartment {apartment} in domophone {self.mac_adress}")
    #         return
    #     self.open_door()
    #     self.send_event(client, "key_used", apartment=apartment, key_id=key_id)
    #     logger.info(f"Domophone {self.mac_adress} opened with key {key_id} for apartment {apartment}")

    def close_door(self) -> None:
        self.magnit_status = True
        logger.info(f"Door closed for domophone {self.mac_adress}")

    def open_door(self) -> None:
        self.magnit_status = False
        logger.info(f"Door opened for domophone {self.mac_adress}")

    def call_to_flat(self, apartment: int, client: mqtt.Client) -> None:
        event = {
            "event": "call",
            "mac": self.mac_adress,
            "apartment": apartment,
            "timestamp": int(time.time())
        }
        try:
            client.publish("domophone/events", json.dumps(event))
            logger.info(f"Call to apartment {apartment} from domophone {self.mac_adress}")
        except Exception as e:
            logger.error(f"Failed to send call event: {e}")

    def make_unactive(self, client: mqtt.Client):
        self.status = False
        door_status = "open" if not self.magnit_status else "closed"
        status_message = {
            "mac": self.mac_adress,
            "model": self.model,
            "adress": self.adress,
            "status": "offline",
            "door_status": door_status,
            "timestamp": int(time.time())
        }
        client.publish("domophone/status", json.dumps(status_message))
        logger.info(f"Domophone {self.mac_adress} is unactive")

    def make_active(self, client: mqtt.Client):
        self.status = True
        door_status = "open" if not self.magnit_status else "closed"
        status_message = {
            "mac": self.mac_adress,
            "model": self.model,
            "adress": self.adress,
            "status": "online",
            "door_status": door_status,
            "timestamp": int(time.time())
        }
        client.publish("domophone/status", json.dumps(status_message))
        logger.info(f"Domophone {self.mac_adress} is unactive")

    def send_status(self, client: mqtt.Client) -> None:
        try:
            door_status = "open" if not self.magnit_status else "closed"
            status_message = {
                "mac": self.mac_adress,
                "model": self.model,
                "adress": self.adress,
                "status": "online" if self.status else "offline",
                "keys": self.keys,  # dict
                "door_status": door_status,
                "timestamp": int(time.time())
            }
            client.publish("domophone/status", json.dumps(status_message))
            logger.info(f"Sent status for {self.mac_adress}: {status_message}")
        except Exception as e:
            logger.error(f"Failed to send status for {self.mac_adress}: {e}")

    def send_event(self, client: mqtt.Client, event_type: str, **kwargs) -> None:
        try:
            strategy = self.event_strategies.get(event_type)
            if not strategy:
                logger.warning(f"Unknown event type: {event_type}")
                return
            # Для key_used пробрасываем параметры
            if event_type == "key_used":
                event = strategy.generate_event(self, client, kwargs.get("apartment"), kwargs.get("key_id"))
            else:
                event = strategy.generate_event(self, client)
            if not event:
                return
            client.publish("domophone/events", json.dumps(event))
            logger.info(f"Sent event for {self.mac_adress}: {event}")
        except Exception as e:
            logger.error(f"Failed to send event {event_type} for {self.mac_adress}: {e}")

    def handle_command(self, client: mqtt.Client, payload: Dict[str, Any]) -> None:
        try:
            if not isinstance(payload, dict) or "mac" not in payload or "command" not in payload:
                logger.error(f"Invalid command payload: {payload}")
                return
            if payload["mac"] == self.mac_adress:
                if payload["command"] == "open_door":
                    self.open_door()
                    self.send_status(client)
                    self.send_event(client, "door_opened")
                    logger.info(f"Processed open_door command for {self.mac_adress}")
                elif payload["command"] == "close_door":
                    self.close_door()
                    self.send_status(client)
                    logger.info(f"Processed close_door command for {self.mac_adress}")
                elif payload["command"] == "call_to_flat" and "flat_number" in payload:
                    flat_number = payload["flat_number"]
                    self.call_to_flat(flat_number, client)
                    logger.info(f"Processed call_to_flat command for {self.mac_adress}, apartment {flat_number}")
                elif payload["command"] == "add_keys" and "apartment" in payload and "keys" in payload:
                    apartment = int(payload["apartment"])
                    keys = payload["keys"]
                    if not isinstance(keys, list) or not all(isinstance(k, int) for k in keys):
                        logger.warning(f"Invalid keys format: {keys}")
                        return
                    self.add_keys(apartment, keys)
                    self.send_status(client)
                    self.send_event(client, "keys_added")
                    logger.info(f"Processed add_keys command for {self.mac_adress}, apartment {apartment}, keys {keys}")
                elif payload["command"] == "remove_keys" and "apartment" in payload and "keys" in payload:
                    apartment = int(payload["apartment"])
                    keys = payload["keys"]
                    if not isinstance(keys, list) or not all(isinstance(k, int) for k in keys):
                        logger.warning(f"Invalid keys format: {keys}")
                        return
                    self.remove_keys(apartment, keys, client)
                    logger.info(f"Processed remove_keys command for {self.mac_adress}, apartment {apartment}, keys {keys}")
                elif payload["command"] == "make_unactive":
                    self.make_unactive(client)
                    logger.info(f"Processed make_unactive command for {self.mac_adress}")
                elif payload["command"] == "make_active":
                    self.make_active(client)
                    logger.info(f"Processed make_unactive command for {self.mac_adress}")
                else:
                    logger.warning(f"Unknown command: {payload['command']}")
        except Exception as e:
            logger.error(f"Failed to handle command for {self.mac_adress}: {e}")