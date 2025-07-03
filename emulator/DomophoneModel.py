import json
import random
import logging
import time
from typing import List, Optional, Dict, Any, Protocol
import paho.mqtt.client as mqtt
from click import command

# Настройка логирования
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
    def generate_event(self, domophone, client: mqtt.Client) -> Dict[str, Any]:
        if not domophone.keys:
            logger.warning(f"No keys available for domophone {domophone.mac_adress}")
            return {}
        event = {
            "event": "key_used",
            "mac": domophone.mac_adress,
            "key_id": random.choice(domophone.keys),
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
        keys: Optional[List[int]] = None,
        magnit_status: bool = True
    ):
        self.mac_adress = mac_adress
        self.model = model
        self.flats_range = flats_range
        self.adress = adress
        self.status = status
        self.keys = keys if keys is not None else []
        self.magnit_status = magnit_status
        self.event_strategies = {
            "call": CallEventStrategy(),
            "key_used": KeyUsedEventStrategy(),
            "door_opened": DoorOpenedEventStrategy()
        }
        logger.info(f"Domophone initialized: {self.mac_adress}")


    def add_keys(self, keys: List[int]) -> None:
        self.keys.extend(keys)
        logger.info(f"Added keys {keys} to domophone {self.mac_adress}")


    def close_door(self) -> None:
        self.magnit_status = True
        logger.info(f"Door closed for domophone {self.mac_adress}")

    def open_door(self) -> None:
        self.magnit_status = False
        logger.info(f"Door opened for domophone {self.mac_adress}")

    def open_by_key(self, key_id: int, client: mqtt.Client) -> None:
        if key_id not in self.keys:
            logger.warning(f"Key {key_id} not programmed for domophone {self.mac_adress}")
            return
        self.open_door()
        self.send_event(client, "key_used")
        logger.info(f"Domophone {self.mac_adress} opened with key {key_id}")

    def remove_keys(self, keys, client):
        changed = False
        for key_id in keys:
            if key_id in self.keys:
                self.keys.remove(key_id)
                changed = True
                logger.info(f"Domophone {self.mac_adress} deleted key {key_id}")
        if changed:
            self.send_status(client)

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
                "keys": self.keys,
                "door_status": door_status,
                "timestamp": int(time.time())
            }
            client.publish("domophone/status", json.dumps(status_message))
            logger.info(f"Sent status for {self.mac_adress}: {status_message}")
        except Exception as e:
            logger.error(f"Failed to send status for {self.mac_adress}: {e}")

    def send_event(self, client: mqtt.Client, event_type: str) -> None:
        try:
            strategy = self.event_strategies.get(event_type)
            if not strategy:
                logger.warning(f"Unknown event type: {event_type}")
                return
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

                elif payload["command"] == "add_keys" and "keys" in payload:
                    keys = payload["keys"]
                    if not isinstance(keys, list) or not all(isinstance(k, int) for k in keys):
                        logger.warning(f"Invalid keys format: {keys}")
                        return
                    self.add_keys(keys)
                    self.send_status(client)
                    self.send_event(client, "keys_added")
                    logger.info(f"Processed add_keys command for {self.mac_adress}, keys {keys}")


                elif payload["command"] == "remove_keys" and "keys" in payload:
                    keys = payload["keys"]
                    if not isinstance(keys, list) or not all(isinstance(k, int) for k in keys):
                        logger.warning(f"Invalid keys format: {keys}")
                        return
                    self.remove_keys(keys, client)
                    logger.info(f"Processed remove_keys command for {self.mac_adress}, keys {keys}")

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