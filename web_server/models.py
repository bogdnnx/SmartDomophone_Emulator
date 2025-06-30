from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime

class Domophone(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    mac_adress: str = Field(unique=True, index=True)
    model: str
    adress: str
    status: str
    door_status: str
    keys: str  # Храним список ключей как JSON-строку
    last_seen: datetime
    is_active: bool = Field(default=True)

class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    mac_adress: str = Field(index=True)
    event_type: str  # call, key_used, door_opened
    apartment: Optional[int] = None
    key_id: Optional[int] = None
    timestamp: datetime