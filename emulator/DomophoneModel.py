"""
Модуль модели домофона.

Содержит классы для эмуляции домофона, включая основную модель
Domophone и стратегии генерации событий.
"""

import json
import logging
import random
import time
from typing import Any, Dict, List, Optional, Protocol

import paho.mqtt.client as mqtt

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class EventStrategy(Protocol):
    """Базовый протокол для стратегий генерации событий."""
    
    def generate_event(
        self, domophone, client: mqtt.Client
    ) -> Dict[str, Any]:
        """
        Генерирует событие для домофона.
        
        Args:
            domophone: Экземпляр домофона
            client: MQTT-клиент
            
        Returns:
            Dict[str, Any]: Словарь с данными события
        """
        ...


class CallEventStrategy:
    """Стратегия для генерации события звонка."""
    
    def generate_event(
        self, domophone, client: mqtt.Client
    ) -> Dict[str, Any]:
        """
        Генерирует событие звонка в случайную квартиру.
        
        Args:
            domophone: Экземпляр домофона
            client: MQTT-клиент
            
        Returns:
            Dict[str, Any]: Словарь с данными события звонка
        """
        event = {
            "event": "call",
            "mac": domophone.mac_adress,
            "apartment": random.choice(
                list(range(1, domophone.flats_range + 1))
            ),
            "timestamp": int(time.time())
        }
        return event


class KeyUsedEventStrategy:
    """Стратегия для генерации события использования ключа."""
    
    def generate_event(
        self, domophone, client: mqtt.Client, 
        apartment: int = None, key_id: int = None
    ) -> Dict[str, Any]:
        """
        Генерирует событие использования ключа.
        
        Args:
            domophone: Экземпляр домофона
            client: MQTT-клиент
            apartment: Номер квартиры (если не указан, выбирается случайно)
            key_id: ID ключа (если не указан, выбирается случайно)
            
        Returns:
            Dict[str, Any]: Словарь с данными события использования ключа
        """
        # Если параметры не переданы, выбираем случайно
        if not domophone.keys:
            logger.warning(
                f"No keys available for domophone {domophone.mac_adress}"
            )
            return {}
        if apartment is None or key_id is None:
            # Выбираем случайную квартиру и ключ
            apartments = [
                a for a in domophone.keys if domophone.keys[a]
            ]
            if not apartments:
                logger.warning(
                    f"No apartments with keys for domophone "
                    f"{domophone.mac_adress}"
                )
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
        """
        Инициализирует домофон.
        
        Args:
            mac_adress: MAC-адрес домофона
            model: Модель домофона
            flats_range: Диапазон номеров квартир
            adress: Адрес установки домофона
            status: Статус домофона (True - онлайн, False - оффлайн)
            keys: Словарь ключей по квартирам {apartment: [key_id, ...]}
            magnit_status: Статус магнитного замка (True - закрыт, False - открыт)
        """
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
        }
        logger.info(f"Domophone initialized: {self.mac_adress}")

    def add_keys(self, apartment: int, key_ids: List[int]) -> None:
        """
        Добавляет ключи для указанной квартиры.
        
        Args:
            apartment: Номер квартиры
            key_ids: Список ID ключей для добавления
        """
        if apartment not in self.keys:
            self.keys[apartment] = []
        for key_id in key_ids:
            if key_id not in self.keys[apartment]:
                self.keys[apartment].append(key_id)
        logger.info(
            f"Added keys {key_ids} to apartment {apartment} "
            f"for domophone {self.mac_adress}"
        )

    def remove_keys(
        self, apartment: int, key_ids: List[int], client: mqtt.Client
    ) -> None:
        """
        Удаляет ключи для указанной квартиры.
        
        Args:
            apartment: Номер квартиры
            key_ids: Список ID ключей для удаления
            client: MQTT-клиент для отправки обновленного статуса
        """
        if apartment in self.keys:
            self.keys[apartment] = [
                k for k in self.keys[apartment] if k not in key_ids
            ]
            if not self.keys[apartment]:
                del self.keys[apartment]
            logger.info(
                f"Removed keys {key_ids} from apartment {apartment} "
                f"for domophone {self.mac_adress}"
            )
            self.send_status(client)

    def close_door(self) -> None:
        """Закрывает дверь (активирует магнитный замок)."""
        self.magnit_status = True
        logger.info(f"Door closed for domophone {self.mac_adress}")

    def open_door(self) -> None:
        """Открывает дверь (деактивирует магнитный замок)."""
        self.magnit_status = False
        logger.info(f"Door opened for domophone {self.mac_adress}")

    def call_to_flat(self, apartment: int, client: mqtt.Client) -> None:
        """
        Выполняет звонок в указанную квартиру.
        
        Args:
            apartment: Номер квартиры для звонка
            client: MQTT-клиент для отправки события
        """
        event = {
            "event": "call",
            "mac": self.mac_adress,
            "apartment": apartment,
            "timestamp": int(time.time())
        }
        try:
            client.publish("domophone/events", json.dumps(event))
            logger.info(
                f"Call to apartment {apartment} from domophone "
                f"{self.mac_adress}"
            )
        except Exception as e:
            logger.error(f"Failed to send call event: {e}")

    def make_unactive(self, client: mqtt.Client) -> None:
        """
        Деактивирует домофон (переводит в оффлайн).
        
        Args:
            client: MQTT-клиент для отправки статуса
        """
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

    def make_active(self, client: mqtt.Client) -> None:
        """
        Активирует домофон (переводит в онлайн).
        
        Args:
            client: MQTT-клиент для отправки статуса
        """
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
        logger.info(f"Domophone {self.mac_adress} is active")

    def send_status(self, client: mqtt.Client) -> None:
        """
        Отправляет текущий статус домофона через MQTT.
        
        Args:
            client: MQTT-клиент для отправки статуса
        """
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
            logger.info(
                f"Sent status for {self.mac_adress}: {status_message}"
            )
        except Exception as e:
            logger.error(f"Failed to send status for {self.mac_adress}: {e}")

    def send_event(
        self, client: mqtt.Client, event_type: str, **kwargs
    ) -> None:
        """
        Отправляет событие через MQTT.
        
        Args:
            client: MQTT-клиент для отправки события
            event_type: Тип события
            **kwargs: Дополнительные параметры события
        """
        try:
            strategy = self.event_strategies.get(event_type)
            if not strategy:
                logger.warning(f"Unknown event type: {event_type}")
                return
            # Для key_used пробрасываем параметры
            if event_type == "key_used":
                event = strategy.generate_event(
                    self, client, 
                    kwargs.get("apartment"), 
                    kwargs.get("key_id")
                )
            else:
                event = strategy.generate_event(self, client)
            if not event:
                return
            client.publish("domophone/events", json.dumps(event))
            logger.info(f"Sent event for {self.mac_adress}: {event}")
        except Exception as e:
            logger.error(
                f"Failed to send event {event_type} for "
                f"{self.mac_adress}: {e}"
            )

    def handle_command(
        self, client: mqtt.Client, payload: Dict[str, Any]
    ) -> None:
        """
        Обрабатывает команду, полученную через MQTT.
        
        Args:
            client: MQTT-клиент для отправки ответов
            payload: Словарь с данными команды
        """
        try:
            if (not isinstance(payload, dict) or 
                "mac" not in payload or 
                "command" not in payload):
                logger.error(f"Invalid command payload: {payload}")
                return
            if payload["mac"] == self.mac_adress:
                if payload["command"] == "open_door":
                    self.open_door()
                    self.send_status(client)
                    # Отправляем событие открытия двери
                    event = {
                        "event": "door_opened",
                        "mac": self.mac_adress,
                        "timestamp": int(time.time())
                    }
                    client.publish("domophone/events", json.dumps(event))
                    logger.info(
                        f"Processed open_door command for {self.mac_adress}"
                    )
                elif payload["command"] == "close_door":
                    self.close_door()
                    self.send_status(client)
                    # Отправляем событие закрытия двери
                    event = {
                        "event": "door_closed",
                        "mac": self.mac_adress,
                        "timestamp": int(time.time())
                    }
                    client.publish("domophone/events", json.dumps(event))
                    logger.info(
                        f"Processed close_door command for {self.mac_adress}"
                    )
                elif (payload["command"] == "call_to_flat" and 
                      "flat_number" in payload):
                    flat_number = payload["flat_number"]
                    self.call_to_flat(flat_number, client)
                    logger.info(
                        f"Processed call_to_flat command for "
                        f"{self.mac_adress}, apartment {flat_number}"
                    )
                elif (payload["command"] == "add_keys" and 
                      "apartment" in payload and 
                      "keys" in payload):
                    apartment = int(payload["apartment"])
                    keys = payload["keys"]
                    if (not isinstance(keys, list) or 
                        not all(isinstance(k, int) for k in keys)):
                        logger.warning(f"Invalid keys format: {keys}")
                        return
                    self.add_keys(apartment, keys)
                    self.send_status(client)
                    # Отправляем событие добавления ключей
                    event = {
                        "event": "keys_added",
                        "mac": self.mac_adress,
                        "apartment": apartment,
                        "keys": keys,
                        "timestamp": int(time.time())
                    }
                    client.publish("domophone/events", json.dumps(event))
                    logger.info(
                        f"Processed add_keys command for {self.mac_adress}, "
                        f"apartment {apartment}, keys {keys}"
                    )
                elif (payload["command"] == "remove_keys" and 
                      "apartment" in payload and 
                      "keys" in payload):
                    apartment = int(payload["apartment"])
                    keys = payload["keys"]
                    if (not isinstance(keys, list) or 
                        not all(isinstance(k, int) for k in keys)):
                        logger.warning(f"Invalid keys format: {keys}")
                        return
                    self.remove_keys(apartment, keys, client)
                    # Отправляем событие удаления ключей
                    event = {
                        "event": "keys_removed",
                        "mac": self.mac_adress,
                        "apartment": apartment,
                        "keys": keys,
                        "timestamp": int(time.time())
                    }
                    client.publish("domophone/events", json.dumps(event))
                    logger.info(
                        f"Processed remove_keys command for "
                        f"{self.mac_adress}, apartment {apartment}, "
                        f"keys {keys}"
                    )
                elif payload["command"] == "make_unactive":
                    self.make_unactive(client)
                    # Отправляем событие деактивации домофона
                    event = {
                        "event": "domophone_deactivated",
                        "mac": self.mac_adress,
                        "timestamp": int(time.time())
                    }
                    client.publish("domophone/events", json.dumps(event))
                    logger.info(
                        f"Processed make_unactive command for "
                        f"{self.mac_adress}"
                    )
                elif payload["command"] == "make_active":
                    self.make_active(client)
                    # Отправляем событие активации домофона
                    event = {
                        "event": "domophone_activated",
                        "mac": self.mac_adress,
                        "timestamp": int(time.time())
                    }
                    client.publish("domophone/events", json.dumps(event))
                    logger.info(
                        f"Processed make_active command for "
                        f"{self.mac_adress}"
                    )
                else:
                    logger.warning(f"Unknown command: {payload['command']}")
        except Exception as e:
            logger.error(f"Failed to handle command for {self.mac_adress}: {e}")