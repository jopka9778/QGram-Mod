import customtkinter as ctk
import threading
import logging
import time
from queue import Empty

class App(ctk.CTk):
    def __init__(self, run_telegram_client_func, is_client_connected_func, queue, is_logged_in):
        super().__init__()
        self.run_telegram_client_func = run_telegram_client_func
        self.is_client_connected_func = is_client_connected_func
        self.queue = queue
        self.telegram_thread = None
        self.current_chat_id = None
        self.current_chat_name = ""
        self.api_mode = "bot"

        self.title("QGram - Telegram Client")
        self.geometry("800x600")

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        self.login_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.login_frame.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        self.login_frame.grid_columnconfigure(0, weight=1)
        
        self.login_label = ctk.CTkLabel(self.login_frame, text="Введите токен бота:", font=ctk.CTkFont(size=16))
        self.login_label.pack(pady=10)
        
        self.entry_frame = ctk.CTkFrame(self.login_frame, fg_color="transparent")
        self.entry_frame.pack(pady=10)

        self.entry_field = ctk.CTkEntry(self.entry_frame, placeholder_text="123456:ABC-DEF", width=300)
        self.entry_field.pack(side="left", padx=(20, 5), fill="x", expand=True)
        
        self.paste_button = ctk.CTkButton(self.entry_frame, text="Вставить", command=self.paste_from_clipboard)
        self.paste_button.pack(side="left", padx=(0, 20))

        self.login_button = ctk.CTkButton(self.login_frame, text="Войти", command=self.start_login)
        self.login_button.pack(pady=10)

        self.status_label = ctk.CTkLabel(self.login_frame, text="", text_color="yellow")
        self.status_label.pack(pady=5)
        
        self.main_app_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_app_frame.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        self.main_app_frame.grid_remove()
        
        self.main_app_frame.grid_columnconfigure(0, weight=1)
        self.main_app_frame.grid_columnconfigure(1, weight=3)
        self.main_app_frame.grid_rowconfigure(0, weight=1)

        self.chat_list_frame = ctk.CTkFrame(self.main_app_frame, width=200)
        self.chat_list_frame.grid(row=0, column=0, padx=(0, 10), sticky="nsew")
        self.chat_list_frame.grid_rowconfigure(0, weight=1)

        self.chat_list_label = ctk.CTkLabel(self.chat_list_frame, text="Чаты", font=ctk.CTkFont(size=18, weight="bold"))
        self.chat_list_label.pack(pady=10)

        self.chat_list_scrollable_frame = ctk.CTkScrollableFrame(self.chat_list_frame)
        self.chat_list_scrollable_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.message_frame = ctk.CTkFrame(self.main_app_frame)
        self.message_frame.grid(row=0, column=1, sticky="nsew")
        self.message_frame.grid_rowconfigure(0, weight=1)
        self.message_frame.grid_columnconfigure(0, weight=1)

        self.chat_title_label = ctk.CTkLabel(self.message_frame, text="Выберите чат", font=ctk.CTkFont(size=18, weight="bold"))
        self.chat_title_label.pack(pady=10)
        
        self.message_scrollable_frame = ctk.CTkScrollableFrame(self.message_frame)
        self.message_scrollable_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.message_entry = ctk.CTkEntry(self.message_frame, placeholder_text="Напишите сообщение...")
        self.message_entry.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=(0, 10))
        
        self.send_button = ctk.CTkButton(self.message_frame, text="Отправить", width=100, command=self.send_message)
        self.send_button.pack(side="left", padx=(0, 10), pady=(0, 10))
        
        self.logout_button = ctk.CTkButton(self.main_app_frame, text="Выйти", command=self.logout)
        self.logout_button.grid(row=1, column=0, columnspan=2, pady=(10, 0))

        self.after(100, self.poll_queue)

    def run_client_with_session(self):
        self.run_telegram_client_func(credential=None, q=self.queue)
        self.after(500, self.check_login_status)

    def paste_from_clipboard(self):
        try:
            text = self.clipboard_get()
            self.entry_field.delete(0, ctk.END)
            self.entry_field.insert(0, text)
        except ctk.TclError:
            self.status_label.configure(text="Не удалось получить данные из буфера обмена.", text_color="red")

    def start_login(self):
        credential = self.entry_field.get()
        
        if not credential:
            self.status_label.configure(text="Поле не может быть пустым!", text_color="red")
            return
            
        if self.telegram_thread and self.telegram_thread.is_alive():
            logging.info("Клиент Telegram уже запущен.")
            return

        logging.info(f"Запускаю клиента в режиме: {self.api_mode}")
        self.status_label.configure(text="Выполняется вход...")
            
        self.telegram_thread = threading.Thread(
            target=self.run_telegram_client_func,
            args=(credential, self.queue),
            daemon=True
        )
        self.telegram_thread.start()
        
        self.after(500, self.check_login_status)
    
    def check_login_status(self):
        if self.is_client_connected_func():
            self.show_main_app()
        else:
            self.after(500, self.check_login_status)

    def show_main_app(self):
        self.login_frame.grid_remove()
        self.main_app_frame.grid()
        self.status_label.configure(text="")
        
        self.queue.put_nowait({"type": "get_chat_list"})
        
    def logout(self):
        # TODO: Добавить логику остановки клиента Pyrogram
        logging.info("Выход...")
        self.main_app_frame.grid_remove()
        self.login_frame.grid()
        self.status_label.configure(text="")
        self.entry_field.delete(0, ctk.END)
        self.current_chat_id = None
        
    def poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                logging.info(f"GUI: Получен элемент из очереди: {item['type']}")
                self.process_queue_item(item)
        except Empty:
            pass
        self.after(100, self.poll_queue)

    def process_queue_item(self, item):
        logging.info(f"GUI: Обрабатываю элемент типа: {item['type']}")
        if item["type"] == "chat_list":
            self.update_chat_list(item["chats"])
        elif item["type"] == "new_message":
            self.add_message_to_view(item)
        elif item["type"] == "chat_history":
            self.display_chat_history(item["messages"])
        elif item["type"] == "error":
            logging.error(f"Ошибка от клиента: {item['message']}")
            self.status_label.configure(text=f"Ошибка: {item['message']}", text_color="red")
        elif item["type"] == "request_code":
            logging.info("GUI: Вызываю request_code_popup()...")
            self.request_code_popup()
    
    def update_chat_list(self, chats):
        for widget in self.chat_list_scrollable_frame.winfo_children():
            widget.destroy()
        
        for chat in chats:
            chat_button = ctk.CTkButton(
                self.chat_list_scrollable_frame,
                text=chat["title"],
                command=lambda chat=chat: self.select_chat(chat)
            )
            chat_button.pack(fill="x", pady=2, padx=5)

    def select_chat(self, chat):
        self.current_chat_id = chat["id"]
        self.current_chat_name = chat["title"]
        self.chat_title_label.configure(text=self.current_chat_name)
        
        for widget in self.message_scrollable_frame.winfo_children():
            widget.destroy()
        
        self.queue.put_nowait({"type": "get_chat_history", "chat_id": self.current_chat_id})

    def display_chat_history(self, messages):
        for widget in self.message_scrollable_frame.winfo_children():
            widget.destroy()

        for msg in messages:
            self.add_message_to_view(msg)
        self.message_scrollable_frame._parent_canvas.yview_moveto(1.0)
    
    def add_message_to_view(self, message):
        if message["chat_id"] != self.current_chat_id:
            return

        is_outgoing = message["direction"] == "outgoing"
        
        message_label = ctk.CTkLabel(
            self.message_scrollable_frame,
            text=f"{message['sender']}: {message['text']}",
            justify="left",
            wraplength=400,
            fg_color=ctk.ThemeManager.theme['CTkButton']['fg_color'] if is_outgoing else "gray40",
            corner_radius=10
        )
        message_label.pack(anchor="e" if is_outgoing else "w", pady=5, padx=5)

    def send_message(self):
        text = self.message_entry.get()
        if text and self.current_chat_id:
            self.queue.put_nowait({"type": "send_message", "chat_id": self.current_chat_id, "text": text})
            self.message_entry.delete(0, ctk.END)
