from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import os

# Используйте SQLite для простоты
# Base.db создастся автоматически в папке с проектом
db_path = 'base.db'
engine = create_engine(f'sqlite:///{db_path}', echo=True)

Base = declarative_base()

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, index=True)
    text = Column(Text, nullable=True)
    direction = Column(String)  # 'incoming' or 'outgoing'
    status = Column(String)     # 'pending', 'sent', 'delivered'
    media_path = Column(String, nullable=True)
    media_type = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    message_id = Column(Integer, nullable=True, unique=True)
    sender_name = Column(String, nullable=True) # НОВОЕ ПОЛЕ ДЛЯ ИМЕНИ ОТПРАВИТЕЛЯ

class Chat(Base):
    __tablename__ = 'chats'
    id = Column(Integer, primary_key=True)
    title = Column(String)
    updated = Column(DateTime, default=datetime.utcnow)
    last_message = Column(String, nullable=True)
    unread = Column(Integer, default=0)
