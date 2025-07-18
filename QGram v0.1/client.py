import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
import logging
import threading
from queue import Empty
from sqlalchemy.orm import sessionmaker, scoped_session
from models import Base, engine, Chat, Message
from datetime import datetime, timezone

# --- Глобальные переменные ---
client_instance = None
is_running = False
update_queue = None

# Настройка сессии SQLAlchemy
Session = scoped_session(sessionmaker(bind=engine))

async def setup_client(credential, queue, api_id=26596117, api_hash="30ac501bec4f6bb1c8f5fcf09c6f5a28"):
    global client_instance, is_running, update_queue
    update_queue = queue
    
    if is_running:
        logging.warning("Клиент уже запущен.")
        return
        
    try:
        if credential:
            token = credential
            logging.info("Попытка входа как бот (новый токен).")
            client_instance = Client(
                "my_bot_session",
                api_id=api_id,
                api_hash=api_hash,
                bot_token=token
            )
        else:
            logging.info("Попытка входа как бот (использую сохраненную сессию).")
            client_instance = Client(
                "my_bot_session",
                api_id=api_id,
                api_hash=api_hash,
            )

        await client_instance.start()
        is_running = True
        logging.info("Клиент Telegram успешно запущен!")
        
        await get_all_chats()

        @client_instance.on_message()
        async def message_handler(client, message: Message):
            db_session = Session()
            try:
                chat_id = message.chat.id
                
                # Проверяем, существует ли чат в базе данных
                chat_obj = db_session.query(Chat).filter_by(id=chat_id).first()
                if not chat_obj:
                    # Если чата нет, создаем его
                    chat_info = await get_chat_info(client, chat_id)
                    if chat_info:
                        chat_obj = Chat(
                            id=chat_info['id'],
                            title=chat_info['title'],
                            chat_type=chat_info['chat_type']
                        )
                        db_session.add(chat_obj)
                        db_session.commit()
                        update_queue.put_nowait({"type": "chat_list", "chats": await get_all_chats_from_db()})

                # Сохраняем новое сообщение
                new_message = Message(
                    chat_id=chat_id,
                    text=message.text,
                    direction="incoming",
                    status="received",
                    timestamp=datetime.now(timezone.utc),
                    message_id=message.id
                )
                db_session.add(new_message)
                db_session.commit()
                
                sender_name = message.from_user.first_name if message.from_user else "Неизвестно"
                update_queue.put_nowait({
                    "type": "new_message",
                    "chat_id": chat_id,
                    "text": message.text,
                    "sender": sender_name,
                    "direction": "incoming"
                })
            finally:
                Session.remove()
            
        await handle_gui_commands()

    except Exception as e:
        logging.error(f"Критическая ошибка клиента: {e}", exc_info=True)
        update_queue.put_nowait({"type": "error", "message": str(e)})
    finally:
        is_running = False
        if client_instance and client_instance.is_connected:
            await client_instance.stop()
        logging.info("Клиент Telegram остановлен.")
        Session.remove()

async def get_chat_info(bot_instance, chat_id):
    try:
        chat_obj = await bot_instance.get_chat(chat_id)
        if chat_obj.type == 'private':
            name = chat_obj.first_name
            if chat_obj.last_name:
                name += f" {chat_obj.last_name}"
            return {
                'id': chat_obj.id,
                'title': name,
                'chat_type': 'private'
            }
        elif chat_obj.type in ['group', 'supergroup', 'channel']:
            return {
                'id': chat_obj.id,
                'title': chat_obj.title,
                'chat_type': chat_obj.type
            }
        else:
            return None
    except Exception as e:
        logging.error(f"Не удалось получить информацию о чате {chat_id}: {e}")
        return None

async def get_all_chats_from_db():
    db_session = Session()
    try:
        chats = db_session.query(Chat).all()
        chats_list = []
        for chat in chats:
            chats_list.append({
                "id": chat.id,
                "title": chat.title,
                "chat_type": chat.chat_type
            })
        return chats_list
    finally:
        Session.remove()

async def get_all_chats():
    chats_list = await get_all_chats_from_db()
    update_queue.put_nowait({"type": "chat_list", "chats": chats_list})

async def handle_gui_commands():
    while is_running:
        try:
            item = update_queue.get_nowait()
            
            if item["type"] == "get_chat_list":
                chats_list = await get_all_chats_from_db()
                update_queue.put_nowait({"type": "chat_list", "chats": chats_list})
            
            elif item["type"] == "get_chat_history":
                db_session = Session()
                try:
                    chat_id = item["chat_id"]
                    messages_list = []
                    messages = db_session.query(Message).filter_by(chat_id=chat_id).order_by(Message.timestamp.asc()).all()
                    for message in messages:
                        messages_list.append({
                            "chat_id": message.chat_id,
                            "text": message.text,
                            "sender": "Вы" if message.direction == "outgoing" else "Собеседник",
                            "direction": message.direction
                        })
                    update_queue.put_nowait({"type": "chat_history", "messages": messages_list})
                finally:
                    Session.remove()

            elif item["type"] == "send_message":
                db_session = Session()
                try:
                    chat_id = item["chat_id"]
                    text = item["text"]
                    sent_message = await client_instance.send_message(chat_id, text)
                    
                    new_message = Message(
                        chat_id=chat_id,
                        text=text,
                        direction="outgoing",
                        status="sent",
                        timestamp=datetime.now(timezone.utc),
                        message_id=sent_message.id
                    )
                    db_session.add(new_message)
                    db_session.commit()

                    sender_name = sent_message.from_user.first_name if sent_message.from_user else "Вы"
                    update_queue.put_nowait({
                        "type": "new_message",
                        "chat_id": chat_id,
                        "text": text,
                        "sender": sender_name,
                        "direction": "outgoing"
                    })
                except Exception as e:
                    logging.error(f"Ошибка при отправке сообщения: {e}", exc_info=True)
                    update_queue.put_nowait({"type": "error", "message": f"Ошибка при отправке сообщения: {e}"})
                finally:
                    Session.remove()
            
        except Empty:
            await asyncio.sleep(0.1)
        except Exception as e:
            logging.error(f"Ошибка в цикле команд: {e}", exc_info=True)
            update_queue.put_nowait({"type": "error", "message": f"Критическая ошибка в цикле команд: {e}"})

def is_client_connected():
    return is_running and client_instance and client_instance.is_connected
