from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from sqlalchemy.orm import sessionmaker, scoped_session
from models import Base, Message, Chat, engine
import logging
from datetime import datetime, timezone
import asyncio
from threading import Thread
import os
import webbrowser
import json
import time

# --- ВСТАВЬТЕ ВАШ ТОКЕН СЮДА ---
BOT_TOKEN = ""

# Используем aiogram
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

# Эта функция будет получать информацию о пользователях и чатах
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

# --- Flask Configuration ---
app = Flask(__name__)
app.secret_key = 'your_super_secret_and_long_key_here'
app.config['UPLOAD_FOLDER'] = 'static/media'
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# --- Database Configuration ---
Session = scoped_session(sessionmaker(bind=engine))
Base.metadata.create_all(engine)

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Global Variables for Bot ---
bot = None
dp = None
bot_thread = None

# --- Bot Runner Function ---
def run_bot(token):
    global bot, dp
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher()

        @dp.message()
        async def handle_incoming_telegram_message(message: types.Message):
            db_session = Session()
            try:
                existing_message = db_session.query(Message).filter_by(message_id=message.message_id).first()
                if existing_message:
                    logging.info(f"Сообщение {message.message_id} уже существует в базе. Пропускаем.")
                    return

                chat_id = message.chat.id
                chat_title = message.chat.title or message.chat.first_name or f'ID: {chat_id}'
                
                text = message.text
                media_path = None
                media_type = None

                if message.photo:
                    file_id = message.photo[-1].file_id
                    file_info = await bot.get_file(file_id)
                    file_name = os.path.basename(file_info.file_path)
                    media_path = os.path.join('media', file_name)
                    media_type = 'photo'
                    await bot.download_file(file_info.file_path, os.path.join(app.config['UPLOAD_FOLDER'], file_name))
                elif message.video:
                    file_id = message.video.file_id
                    file_info = await bot.get_file(file_id)
                    file_name = os.path.basename(file_info.file_path)
                    media_path = os.path.join('media', file_name)
                    media_type = 'video'
                    await bot.download_file(file_info.file_path, os.path.join(app.config['UPLOAD_FOLDER'], file_name))
                
                chat = db_session.query(Chat).filter_by(id=chat_id).first()
                if not chat:
                    chat = Chat(id=chat_id, title=chat_title, updated=datetime.now(timezone.utc), unread=0)
                    db_session.add(chat)
                
                chat.last_message = text or f"[{media_type}]"
                chat.updated = datetime.now(timezone.utc)
                chat.unread = (chat.unread or 0) + 1

                # Сохраняем имя отправителя
                sender_name = message.from_user.first_name or message.from_user.username or "Неизвестный"
                
                new_message = Message(chat_id=chat_id, text=text, direction='incoming', status='sent', media_path=media_path, media_type=media_type, message_id=message.message_id, sender_name=sender_name)
                db_session.add(new_message)
                db_session.commit()
                logging.info(f"Получено и сохранено сообщение от {chat_title}: {text or media_type}")

            except Exception as e:
                logging.error(f"Ошибка при обработке сообщения: {e}")
                db_session.rollback()
            finally:
                Session.remove()

        async def send_pending_messages():
            while True:
                db_session = Session()
                try:
                    pending_messages = db_session.query(Message).filter_by(direction='outgoing', status='pending').all()
                    for msg in pending_messages:
                        try:
                            if bot is None:
                                logging.warning("Бот не подключен. Пропускаю отправку исходящих сообщений.")
                                continue
                            
                            if msg.media_path and os.path.exists(os.path.join('static', msg.media_path)):
                                with open(os.path.join('static', msg.media_path), 'rb') as f:
                                    if msg.media_type == 'photo':
                                        await bot.send_photo(chat_id=msg.chat_id, photo=types.BufferedInputFile(f.read(), filename=os.path.basename(msg.media_path)), caption=msg.text or '')
                                    elif msg.media_type == 'video':
                                        await bot.send_video(chat_id=msg.chat_id, video=types.BufferedInputFile(f.read(), filename=os.path.basename(msg.media_path)), caption=msg.text or '')
                                    else:
                                        await bot.send_document(chat_id=msg.chat_id, document=types.BufferedInputFile(f.read(), filename=os.path.basename(msg.media_path)), caption=msg.text or '')
                            else:
                                await bot.send_message(chat_id=msg.chat_id, text=msg.text)
                                
                            msg.status = 'sent'
                            logging.info(f"Отправлено исходящее сообщение в чат {msg.chat_id}: {msg.text or msg.media_type}")
                            db_session.commit()
                        except TelegramBadRequest as e:
                             logging.error(f"TelegramBadRequest: {e}. Сообщение {msg.id} не было отправлено.")
                             db_session.rollback()
                        except Exception as e:
                            logging.error(f"Ошибка при отправке исходящего сообщения {msg.id}: {e}")
                            db_session.rollback()
                
                except Exception as e:
                    logging.error(f"Ошибка при проверке исходящих сообщений: {e}")
                    db_session.rollback()
                finally:
                    Session.remove()
                
                await asyncio.sleep(2)

        try:
            logging.info("Поток бота запущен. Запускаю опрос...")
            loop.run_until_complete(asyncio.gather(
                dp.start_polling(bot),
                send_pending_messages()
            ))
        except Exception as e:
            logging.error(f"Ошибка в потоке бота: {e}")
        finally:
            loop.close()
            logging.info("Поток бота остановлен.")
    except Exception as e:
        logging.error(f"Критическая ошибка при запуске бота: {e}", exc_info=True)


# --- Flask Routes ---
@app.route('/')
def index():
    db_session = Session()
    try:
        chats_data = db_session.query(Chat).order_by(Chat.updated.desc()).all()
        return render_template('chats.html', chats=chats_data)
    finally:
        Session.remove()

@app.route('/chat/<chat_id>', methods=['GET', 'POST'])
def chat(chat_id):
    db_session = Session()
    try:
        chat_id_int = int(chat_id)
        
        chat_obj = db_session.query(Chat).filter_by(id=chat_id_int).first()
        if not chat_obj:
            return "Чат не найден", 404

        if request.method == 'POST':
            text = request.form.get('text')
            media_file = request.files.get('media')
            
            if not text and not media_file:
                return jsonify({'status': 'error', 'message': 'Пустое сообщение'}), 400

            try:
                media_path = None
                media_type = None

                if media_file:
                    filename = media_file.filename
                    file_ext = filename.split('.')[-1].lower()
                    
                    if file_ext in ['jpg', 'jpeg', 'png', 'gif']:
                        media_type = 'photo'
                    elif file_ext in ['mp4', 'mov', 'avi']:
                        media_type = 'video'
                    else:
                        media_type = 'document'
                    
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    media_file.save(filepath)
                    media_path = os.path.join('media', filename)
                
                # Добавляем имя отправителя для исходящих сообщений
                sender_name = "Вы"
                
                msg = Message(chat_id=chat_id_int, text=text, direction='outgoing', status='pending', media_path=media_path, media_type=media_type, sender_name=sender_name)
                db_session.add(msg)
                db_session.commit()
                
                return jsonify({
                    'status': 'success', 
                    'text': text, 
                    'media_path': media_path, 
                    'media_type': media_type,
                    'timestamp': datetime.now(timezone.utc).strftime('%H:%M'),
                    'sender_name': sender_name
                }), 200

            except Exception as e:
                logging.error(f"Ошибка при сохранении сообщения: {e}")
                return jsonify({'status': 'error', 'message': 'Ошибка сохранения сообщения'}), 500
            
        messages = db_session.query(Message).filter_by(chat_id=chat_id_int).order_by(Message.timestamp).all()
        
        if chat_obj:
            chat_obj.unread = 0
            db_session.commit()
        
        return render_template('chat.html', messages=messages, chat=chat_obj)
    finally:
        Session.remove()

# --- НОВЫЙ МАРШРУТ ДЛЯ ОБНОВЛЕНИЙ ЧАТА ---
@app.route('/api/chat/<int:chat_id>/updates')
def get_new_messages(chat_id):
    db_session = Session()
    try:
        last_message_id = request.args.get('last_message_id', 0, type=int)
        
        new_messages = db_session.query(Message).filter(
            Message.chat_id == chat_id,
            Message.id > last_message_id
        ).order_by(Message.timestamp).all()

        messages_list = []
        for msg in new_messages:
            messages_list.append({
                'id': msg.id,
                'text': msg.text,
                'direction': msg.direction,
                'status': msg.status,
                'timestamp': msg.timestamp.strftime('%H:%M'),
                'media_path': msg.media_path,
                'media_type': msg.media_type,
                'sender_name': msg.sender_name # Добавляем имя отправителя в ответ API
            })
        
        return jsonify(messages_list)
    finally:
        Session.remove()

if __name__ == '__main__':
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logging.error("Токен бота не задан. Пожалуйста, вставьте ваш токен в переменную BOT_TOKEN.")
    else:
        # Запускаем бота в отдельном потоке
        bot_thread = Thread(target=run_bot, args=(BOT_TOKEN,), daemon=True)
        bot_thread.start()
    
    # Запускаем веб-сервер Flask
    webbrowser.open('http://127.0.0.1:5000')
    app.run(debug=True, use_reloader=False)
