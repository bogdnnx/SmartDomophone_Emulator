import asyncio
import json
import random
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Protocol
from datetime import datetime
import paho.mqtt.client as mqtt

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

class EventStrategy(Protocol):
    """Интерфейс для стратегии генерации событий."""
    def generate_event(self, domophone: "Domophone", client: mqtt.Client) -> Dict[str, Any]:
        ...

@dataclass(frozen=True)
class DomophoneConfig:
    """Immutable конфигурация домофона."""
    mac_adress: str
    model: str
    adress: str
    flats_range: range

class CallEventStrategy:
    """Стратегия для события звонка."""
    def generate_event(self, domophone: "Domophone", client: mqtt.Client) -> Dict[str, Any]:
        event = {
            "event": "call",
            "mac": domophone.config.mac_adress,
            "apartment": random.choice(list(domophone.config.flats_range)),
            "timestamp": int(datetime.now().timestamp())
        }
        return event

class KeyUsedEventStrategy:
    """Стратегия для события использования ключа."""
    def generate_event(self, domophone: "Domophone", client: mqtt.Client) -> Dict[str, Any]:
        if not domophone.config.keys:
            logger.warning(f"No keys available for domophone {domophone.config.mac_adress}")
            return {}
        event = {
            "event": "key_used",
            "mac": domophone.config.mac_adress,
            "key_id": random.choice(domophone.config.keys),
            "timestamp": int(datetime.now().timestamp())
        }
        return event

class DoorOpenedEventStrategy:
    """Стратегия для события открытия двери."""
    def generate_event(self, domophone: "Domophone", client: mqtt.Client) -> Dict[str, Any]:
        event = {
            "event": "door_opened",
            "mac": domophone.config.mac_adress,
            "timestamp": int(datetime.now().timestamp())
        }
        return event

class Domophone:
    """Класс для эмуляции домофона с поддержкой MQTT.

    Attributes:
        config: Конфигурация домофона (mac_adress, model, adress, flats_range, keys).
        status: Статус домофона (True - online, False - offline).
        magnit_status: Состояние двери (True - закрыта, False - открыта).
        event_strategies: Словарь стратегий для генерации событий.
    """
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
        self.config = DomophoneConfig(
            mac_adress=mac_adress,
            model=model,
            flats_range=range(1, flats_range + 1),
            adress=adress,
            keys=keys or []
        )
        self.status = status
        self.magnit_status = magnit_status
        self.event_strategies = {
            "call": CallEventStrategy(),
            "key_used": KeyUsedEventStrategy(),
            "door_opened": DoorOpenedEventStrategy()
        }
        logger.info(f"Domophone initialized: {self.config.mac_adress}")

    def check_status(self) -> str:
        """Возвращает строковое представление статуса домофона.

        Returns:
            str: Информация о домофоне (модель, MAC, адрес, статус, состояние двери).
        """
        door_status = "open" if not self.magnit_status else "closed"
        return (f"Панель {self.config.model} {self.config.mac_adress} по адресу {self.config.adress}:\n"
                f"Статус: {'online' if self.status else 'offline'}\n"
                f"Дверь: {door_status}")

    def add_keys(self, keys: List[int]) -> None:
        """Добавляет ключи в список разрешенных ключей.

        Args:
            keys: Список идентификаторов ключей.
        """
        self.config.keys.extend(keys)
        logger.info(f"Added keys {keys} to domophone {self.config.mac_adress}")

    def close_door(self) -> None:
        """Закрывает дверь домофона."""
        self.magnit_status = True
        logger.info(f"Door closed for domophone {self.config.mac_adress}")

    async def open_door(self) -> None:
        """Открывает дверь домофона."""
        self.magnit_status = False

        logger.info(f"Door opened for domophone {self.config.mac_adress}")

    async def open_by_key(self, key_id: int, client: mqtt.Client) -> None:
        """Эмулирует открытие двери ключом с отправкой события.

        Args:
            key_id: Идентификатор ключа.
            client: MQTT-клиент для отправки события.
        """
        if key_id not in self.config.keys:
            logger.warning(f"Key {key_id} not programmed for domophone {self.config.mac_adress}")
            return
        self.open_door()
        await self.send_event(client, "key_used")
        logger.info(f"Domophone {self.config.mac_adress} opened with key {key_id}")

    def call_to_flat(self, flat_number: int, client: mqtt.Client) -> None:
        """Эмулирует звонок в квартиру с отправкой события.

        Args:
            flat_number: Номер квартиры.
            client: MQTT-клиент для отправки события.
        """
        if flat_number not in self.config.flats_range:
            logger.warning(f"Apartment {flat_number} out of range for domophone {self.config.mac_adress}")
            return
        event = {
            "event": "call",
            "mac": self.config.mac_adress,
            "apartment": flat_number,
            "timestamp": int(datetime.now().timestamp())
        }
        try:
            client.publish("domophone/events", json.dumps(event))
            logger.info(f"Call to apartment {flat_number} from domophone {self.config.mac_adress}")
        except Exception as e:
            logger.error(f"Failed to send call event: {e}")

    async def send_status(self, client: mqtt.Client) -> None:
        """Асинхронно отправляет статус домофона в MQTT-топик domophone/status.

        Args:
            client: MQTT-клиент для публикации.
        """
        try:
            door_status = "open" if not self.magnit_status else "closed"
            status_message = {
                "mac": self.config.mac_adress,
                "model": self.config.model,
                "adress": self.config.adress,
                "status": "online" if self.status else "offline",
                "door_status": door_status,
                "timestamp": int(datetime.now().timestamp())
            }
            client.publish("domophone/status", json.dumps(status_message))
            logger.info(f"Sent status for {self.config.mac_adress}: {status_message}")
        except Exception as e:
            logger.error(f"Failed to send status for {self.config.mac_adress}: {e}")

    async def send_event(self, client: mqtt.Client, event_type: str) -> None:
        """Асинхронно отправляет событие в MQTT-топик domophone/events.

        Args:
            client: MQTT-клиент для публикации.
            event_type: Тип события (call, key_used, door_opened).
        """
        try:
            strategy = self.event_strategies.get(event_type)
            if not strategy:
                logger.warning(f"Unknown event type: {event_type}")
                return
            event = strategy.generate_event(self, client)
            if not event:
                return
            client.publish("domophone/events", json.dumps(event))
            logger.info(f"Sent event for {self.config.mac_adress}: {event}")
        except Exception as e:
            logger.error(f"Failed to send event {event_type} for {self.config.mac_adress}: {e}")

    async def handle_command(self, client: mqtt.Client, payload: Dict[str, Any]) -> None:
        """Асинхронно обрабатывает входящую команду из MQTT-топика domophone/commands.

        Args:
            client: MQTT-клиент для отправки подтверждения.
            payload: Словарь с командой.
        """
        try:
            if not isinstance(payload, dict) or "mac" not in payload or "command" not in payload:
                logger.error(f"Invalid command payload: {payload}")
                return
            if payload["mac"] == self.config.mac_adress and payload["command"] == "open_door":
                self.open_door()
                await self.send_event(client, "door_opened")
                logger.info(f"Processed open_door command for {self.config.mac_adress}")
        except Exception as e:
            logger.error(f"Failed to handle command for {self.config.mac_adress}: {e}")