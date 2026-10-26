import socket
import sys
import os
import threading
from rich import print
from rich.markup import escape
from prompt_toolkit import Application
from prompt_toolkit.application import get_app
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings


MAX_NAME_LEN = 32
FORBIDDEN_NAME_CHARS = set(":|\n\r")


# ФУНКЦИЯ очистки
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def get_my_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def valid_name(name):
    """Имя: непустое, до 32 символов, без ':' '|' и переводов строки (иначе ломается протокол)."""
    if not name or len(name) > MAX_NAME_LEN:
        return False
    if not name.isprintable():
        return False
    return not any(c in FORBIDDEN_NAME_CHARS for c in name)


# =============== СЕТЕВАЯ ЛОГИКА КЛИЕНТА ===================
# Адрес сервера. Запрос при запуске убран: сразу показывается логотип с меню.
# Чтобы подключиться к другому компьютеру, поменяйте DEFAULT_SERVER_IP ниже
# или запустите:  python guest.py 192.168.1.5 [PORT]
DEFAULT_SERVER_IP = "192.168.1.109"
SERVER_IP = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SERVER_IP

try:
    SERVER_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 5555
except ValueError:
    print("[bold red][-] Порт должен быть числом.[/bold red]")
    sys.exit()

client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
connected = True


def read_first_line(sock):
    """Читает первую строку от сервера (YOUR_ID) и возвращает (строка, остаток_буфера)."""
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("сервер закрыл соединение")
        buf += chunk
    raw, rest = buf.split(b"\n", 1)
    return raw.decode("utf-8", errors="replace").strip(), rest


try:
    client_socket.settimeout(5)
    client_socket.connect((SERVER_IP, SERVER_PORT))
    first_line, initial_buffer = read_first_line(client_socket)
    client_socket.settimeout(None)
except Exception as e:
    print(f"[bold red][-] Не удалось подключиться к серверу: {escape(str(e))}[/bold red]")
    sys.exit()

if first_line.startswith("YOUR_ID:"):
    server_generated_id = first_line.split(":", 1)[1].strip()
else:
    server_generated_id = "ERROR"


def send_line(text):
    """Отправляет одну команду серверу. ВСЕГДА добавляет \\n (сервер читает построчно)."""
    global connected
    text = text.replace("\r", " ").replace("\n", " ")
    try:
        client_socket.sendall((text + "\n").encode("utf-8"))
        return True
    except OSError:
        connected = False
        notifications.append("[СИСТЕМА] Не удалось отправить: нет соединения с сервером")
        return False


# Переменные
user_name = "Не указано"
has_name = False       # True, когда пользователь сам задал имя
user_ip = get_my_ip()
user_id = server_generated_id
notifications = []
theme = "фиолетовая"
my_channels = []       # [(gid, name), ...]


# Состояние чата
chat_active = False
chat_gid = None
chat_name = ""
chat_msgs = []         # ["имя: текст", ...]

# События, чтобы ждать ответ сервера вместо time.sleep()
my_channels_event = threading.Event()
history_event = threading.Event()
id_event = threading.Event()


def handle_line(line):
    """Разбирает одну строку от сервера."""
    global user_id, chat_gid, chat_name

    if line.startswith("YOUR_ID:"):
        user_id = line.split(":", 1)[1].strip()
        notifications.append(f"[СИСТЕМА] Личность изменена. Новый ID: {user_id}")
        my_channels.clear()
        id_event.set()

    elif line.startswith("NAME_SET:"):
        name = line.split(":", 1)[1]
        notifications.append(f"[СИСТЕМА] Имя в чате: {name}")

    elif line.startswith("GROUP_CREATED:"):
        parts = line.split(":", 2)
        gid = parts[1]
        name = parts[2] if len(parts) == 3 else "?"
        notifications.append(f"[ГРУППА] Создана группа '{name}' с ID: {gid}")

    elif line.startswith("NAME_TAKEN:"):
        name = line.split(":", 1)[1]
        notifications.append(f"[ГРУППА] Имя '{name}' уже занято. Попробуйте другое.")

    elif line.startswith("GROUP_JOINED:"):
        parts = line.split(":", 2)
        gid = parts[1]
        name = parts[2] if len(parts) == 3 else "?"
        notifications.append(f"[ГРУППА] Вы вступили в группу '{name}' ({gid})")

    elif line.startswith("ALREADY_IN:"):
        parts = line.split(":", 2)
        gid = parts[1]
        name = parts[2] if len(parts) == 3 else "?"
        notifications.append(f"[ГРУППА] Вы уже в группе '{name}' ({gid}).")

    elif line.startswith("GROUP_LEFT:"):
        gid = line.split(":", 1)[1]
        notifications.append(f"[ГРУППА] Вы вышли из группы {gid}")

    elif line.startswith("NEED_PASSWORD:"):
        gid = line.split(":", 1)[1]
        notifications.append(f"[ГРУППА] Группа {gid} защищена паролем (или пароль неверный).")

    elif line.startswith("MY_CHANNELS:"):
        raw = line.split(":", 1)[1]
        my_channels.clear()
        for item in raw.split("|"):
            if ":" in item:
                gid, name = item.split(":", 1)
                my_channels.append((gid, name))
        my_channels_event.set()

    elif line == "MY_CHANNELS_EMPTY":
        my_channels.clear()
        notifications.append("[КАНАЛЫ] Вы пока не состоите ни в одной группе.")
        my_channels_event.set()

    elif line.startswith("HISTORY_START:"):
        parts = line.split(":", 2)
        chat_gid = parts[1]
        chat_name = parts[2] if len(parts) == 3 else "?"
        chat_msgs.clear()

    elif line == "HISTORY_END":
        history_event.set()

    elif line.startswith("CHAT:"):
        parts = line.split(":", 3)
        if len(parts) == 4:
            gid, uid, text = parts[1], parts[2], parts[3]
            if chat_active and chat_gid == gid:
                chat_msgs.append(f"{uid}: {text}")
            else:
                notifications.append(f"[{gid}] {uid}: {text}")

    else:
        notifications.append(line)


def receive_message(buffer):
    """Фоновый поток: слушает сервер. buffer — байты, оставшиеся после первой строки."""
    global connected
    while True:
        try:
            data = client_socket.recv(4096)
            if not data:
                notifications.append("[СИСТЕМА] Соединение с сервером потеряно")
                break

            buffer += data
            while b"\n" in buffer:
                raw, buffer = buffer.split(b"\n", 1)
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    handle_line(line)
                except Exception as e:
                    # одна кривая строка не должна убивать приём
                    notifications.append(f"[ОШИБКА] Не удалось разобрать строку: {e}")

        except OSError as e:
            notifications.append(f"[ОШИБКА] {e}")
            break

    connected = False
    # разбудить тех, кто ждёт ответа
    my_channels_event.set()
    history_event.set()
    id_event.set()


threading.Thread(target=receive_message, args=(initial_buffer,), daemon=True).start()
#========================================================


def apply_new_name(new_name):
    """Применяет новое имя и сообщает серверу. Возвращает True/False."""
    global user_name, has_name
    if not valid_name(new_name):
        return False
    user_name = new_name
    has_name = True
    send_line(f"SET_NAME:{new_name}")
    return True


NAME_RULES = f"Имя: до {MAX_NAME_LEN} символов, без символов ':' и '|'."


# ============ ЯЗЫКИ ============
lang = "ru"

TEXT = {
    "ru": {
        "menu_1": "Профиль", "menu_2": "ЛС (Написать по ID)", "menu_3": "Уведомление",
        "menu_4": "Настройки", "menu_5": "Мои группы (чат)", "menu_6": "Создать группу",
        "menu_7": "Все группы", "menu_8": "Сменить личность", "menu_9": "Узнать свой IP",
        "menu_10": "Очистить историю", "menu_11": "О REVENROOM", "menu_12": "Выход",
        "menu_prompt": "Выберите пункт меню [1 - 12]: ",
        "menu_error": "Вы ошиблись, здесь нету такого! Попробуйте ещё раз.",
        "settings_title": "Настройки", "settings_name": "Изменить имя",
        "settings_lang": "Переключить язык (RU / EN)", "settings_theme": "Переключить тему",
        "settings_back": "Назад в меню", "settings_prompt": "Выберите действие: ",
        "settings_error": "Ошибка: выберите верную цифру.",
        "settings_lang_changed": "Язык изменён на: Русский",
        "about_title": "О REVENROOM", "about_back": "Назад в меню",
        "about_body": """
+----------------------------------------------------------------------+
|                        REVENROOM  v1.0                               |
|                    «Ворона в комнате» / "Raven in the Room"          |
+----------------------------------------------------------------------+
|                                                                      |
|  REVENROOM — анонимный мессенджер для терминала.                     |
|                                                                      |
|  Название:  REVEN = ворон (от англ. raven)                           |
|             ROOM = комната (от англ. room)                           |
|             → «Ворона в комнате»                                     |
|                                                                      |
|  Идея: ворон — символ тайны и свободы. Он сидит в комнате,           |
|  но никто не знает, кто он. Так и здесь: вы в чате, но               |
|  ваша личность скрыта. Только ID и IP.                               |
|                                                                      |
+----------------------------------------------------------------------+
|  ВОЗМОЖНОСТИ:                                                        |
|   • Личные сообщения по ID                                           |
|   • Группы (создать / вступить / выйти)                              |
|   • Пароли на группы (мин. 5 символов)                               |
|   • Уникальные имена групп (пока группа активна)                     |
|   • Real-time чат в группах                                          |
|   • Смена личности (новый ID в любой момент)                         |
|   • Уведомления (ЛС, ответы сервера, ошибки)                         |
|   • Два языка: русский / английский                                  |
|   • Смена темы (фиолетовая / красная)                                |
|                                                                      |
+----------------------------------------------------------------------+
|  АВТОР:  no.signal                                                   |
|  ГОД:    2026                                                        |
|  ВЕРСИЯ: 1.0                                                         |
+----------------------------------------------------------------------+
""",
    },
    "en": {
        "menu_1": "Profile", "menu_2": "DM (Message by ID)", "menu_3": "Notifications",
        "menu_4": "Settings", "menu_5": "My groups (chat)", "menu_6": "Create a group",
        "menu_7": "All groups", "menu_8": "Change identity", "menu_9": "My IP",
        "menu_10": "Clear history", "menu_11": "About REVENROOM", "menu_12": "Exit",
        "menu_prompt": "Select menu item [1 - 12]: ",
        "menu_error": "Wrong input! Try again.",
        "settings_title": "Settings", "settings_name": "Change name",
        "settings_lang": "Switch language (RU / EN)", "settings_theme": "Switch theme",
        "settings_back": "Back to menu", "settings_prompt": "Select action: ",
        "settings_error": "Error: choose a valid number.",
        "settings_lang_changed": "Language changed to: English",
        "about_title": "About REVENROOM", "about_back": "Back to menu",
        "about_body": """
+----------------------------------------------------------------------+
|                        REVENROOM  v1.0                               |
|                    "Raven in the Room"                               |
+----------------------------------------------------------------------+
|                                                                      |
|  REVENROOM is an anonymous terminal messenger.                       |
|                                                                      |
|  Name:      REVEN = raven                                            |
|             ROOM  = room                                             |
|             → "Raven in the Room"                                    |
|                                                                      |
|  Idea: a raven is a symbol of mystery and freedom. It sits           |
|  in the room, but nobody knows who it is. Same here: you are         |
|  in the chat, but your identity is hidden. Only ID and IP.           |
|                                                                      |
+----------------------------------------------------------------------+
|  FEATURES:                                                           |
|   • Direct messages by ID                                            |
|   • Groups (create / join / leave)                                   |
|   • Group passwords (min. 5 chars)                                   |
|   • Unique group names (while group is active)                       |
|   • Real-time chat in groups                                         |
|   • Change identity (new ID anytime)                                 |
|   • Notifications (DMs, server replies, errors)                      |
|   • Two languages: Russian / English                                 |
|   • Theme switch (purple / red)                                      |
|                                                                      |
+----------------------------------------------------------------------+
|  AUTHOR:  no.signal                                                  |
|  YEAR:    2026                                                       |
|  VERSION: 1.0                                                        |
+----------------------------------------------------------------------+
""",
    },
}


def t(key):
    return TEXT[lang].get(key, key)


# ============ REAL-TIME ЧАТ ============
app = None


def run_chat(gid, name):
    """Запускает real-time чат на prompt_toolkit."""
    global chat_active, chat_gid, chat_name, app

    chat_active = True
    chat_gid = gid
    chat_name = name
    chat_msgs.clear()

    if has_name:
        send_line(f"SET_NAME:{user_name}")

    # Запрос истории и ожидание ответа (вместо time.sleep)
    history_event.clear()
    send_line(f"HISTORY:{gid}")
    history_event.wait(3)

    # Лента сообщений: показываем столько последних строк, сколько влезает в экран
    def get_messages():
        try:
            rows = get_app().output.get_size().rows
        except Exception:
            rows = 24
        visible = max(rows - 4, 5)
        lines = [f"=== {chat_name} ({chat_gid}) ===  (/exit — выход)", ""]
        lines.extend(chat_msgs[-visible:])
        return "\n".join(lines)

    msg_window = Window(
        content=FormattedTextControl(get_messages),
        wrap_lines=True,
    )

    # Поле ввода
    input_field = TextArea(
        height=1,
        prompt="> ",
        multiline=False,
    )

    # Enter обрабатывается ТОЛЬКО здесь (раньше было дублирование через key binding)
    def send_message(buff):
        text = buff.text.strip()
        if text == "/exit":
            app.exit()
        elif text:
            send_line(f"GMSG:{gid}:{text}")
        return False  # поле очищается

    input_field.accept_handler = send_message

    kb = KeyBindings()

    @kb.add("c-c")
    def _(event):
        event.app.exit()

    root = HSplit([
        msg_window,
        Window(height=1, char="-"),
        input_field,
    ])

    app = Application(
        layout=Layout(root, focused_element=input_field),
        key_bindings=kb,
        full_screen=True,
        refresh_interval=0.3,
    )

    app.run()
    chat_active = False
    clear_screen()


def render_menu():
    """Рисует меню 3x4 в рамке. Отступы считаются, поэтому границы всегда ровные."""
    cols = (28, 34, 28)               # ширина колонок (внутри рамки)
    inner = sum(cols) + 2             # + две вертикальные черты между колонками
    border = "+" + "-" * inner + "+"
    divider = "|" + "-" * inner + "|"
    layout = [(1, 5, 9), (2, 6, 10), (3, 7, 11), (4, 8, 12)]

    lines = [f"[red]{border}[/red]"]
    for r, row in enumerate(layout):
        cells = []
        for n, w in zip(row, cols):
            num = f"[{n}]"
            room = w - len(num) - 2   # место под текст пункта
            text = t(f"menu_{n}")[:room]
            pad = " " * (room - len(text))
            cells.append(f" [#8F3ADB]{escape(num)}[/#8F3ADB] [red]{escape(text)}[/red]{pad}")
        lines.append("[red]|[/red]" + "[red]|[/red]".join(cells) + "[red]|[/red]")
        lines.append(f"[red]{divider if r < len(layout) - 1 else border}[/red]")
    return "\n".join(lines)


# ================= ГЛАВНЫЙ ЦИКЛ =================
while True:
    clear_screen()

    print(r"[#8F3ADB]$$$$$$$\  $$$$$$$$\ $$\    $$\ $$$$$$$$\ $$\   $$\ [/#8F3ADB][red]$$$$$$$\  $$$$$$\   $$$$$$\   $$\      $$\ [/red]")
    print(r"[#8F3ADB]$$  __$$\ $$  _____|$$ |   $$ |$$  _____|$$$\  $$ |[/#8F3ADB][red]$$  __$$\ $$  __$$\ $$  __$$\ $$$\    $$$ |[/red]")
    print(r"[#8F3ADB]$$ |  $$ |$$ |      $$ |   $$ |$$ |      $$$$\ $$ |[/#8F3ADB][red]$$ |  $$ |$$ /  $$ |$$ /  $$ |$$$$\  $$$$ |[/red]")
    print(r"[#8F3ADB]$$$$$$$  |$$$$$\    \$$\  $$  |$$$$$\    $$ $$\$$ |[/#8F3ADB][red]$$$$$$$  |$$ |  $$ |$$ |  $$ |$$\$$\$$ $$ |[/red]")
    print(r"[#8F3ADB]$$  __$$< $$  __|    \$$\$$  / $$  __|   $$ \$$$$ |[/#8F3ADB][red]$$  __$$< $$ |  $$ |$$ |  $$ |$$ \$$$  $$ |[/red]")
    print(r"[#8F3ADB]$$ |  $$ |$$ |        \$$$  /  $$ |      $$ |\$$$ |[/#8F3ADB][red]$$ |  $$ |$$ |  $$ |$$ |  $$ |$$ |\$  /$$ |[/red]")
    print(r"[#8F3ADB]$$ |  $$ |$$$$$$$$\    \$  /   $$$$$$$$\ $$ | \$$ |[/#8F3ADB][red]$$ |  $$ | $$$$$$  | $$$$$$  |$$ | \_/ $$ |[/red]")
    print(r"[#8F3ADB]\__|  \__|\________|    \_/    \________|\__|  \__|[/#8F3ADB][red]\__|  \__| \______/  \______/ \__|     \__|[/red]")
    print("\n\n")

    if not connected:
        print("[bold red][!] Соединение с сервером потеряно. Перезапустите клиент.[/bold red]\n")

    print(render_menu())

    while True:
        choice = input(t("menu_prompt")).strip()
        if choice in [str(i) for i in range(1, 13)]:
            break
        else:
            print(f"[bold][red]{t('menu_error')}[/red][/bold]")

    # ===== 12. ВЫХОД =====
    if choice == '12':
        clear_screen()
        client_socket.close()
        print("[ВЫХОД] Закрытие мессенджера. До встречи!")
        sys.exit()

    # ===== 1. ПРОФИЛЬ =====
    elif choice == '1':
        while True:
            clear_screen()
            print(r"""[#8F3ADB] 
 ____             __ _ _      
|  _ \ _ __ ___  / _(_) | ___ 
| |_) | '__/ _ \| |_| | |/ _ \
|  __/| | | (_) |  _| | |  __/
|_|   |_|  \___/|_| |_|_|\___|
            [/#8F3ADB]""")

            print(f"""[red]
+--------------------------------------------+
|    name    |        ip         |   room    |  
|--------------------------------------------| 
| [/red][#8F3ADB]{escape(f"{user_name:<10}")}[/#8F3ADB][red] | [/red][#8F3ADB]{user_ip:<17}[/#8F3ADB][red] | [/red][#8F3ADB]{user_id:<8}[/#8F3ADB][red]  |                  
+--------------------------------------------+ 
            [/red]""")

            print("[red][1][/red] Изменить имя")
            print("[red][2][/red] Назад в меню")

            prof_choice = input("\nВыберите действие: ").strip()

            if prof_choice == "1":
                new_name = input("Введите новое имя: ").strip()
                if not new_name:
                    pass
                elif apply_new_name(new_name):
                    pass
                else:
                    print(f"[red]Ошибка: {escape(NAME_RULES)}[/red]")
                    input("Нажмите Enter...")
            elif prof_choice == "2":
                break
            else:
                print("[red]Ошибка: выберите верную цифру.[/red]")
                input("Нажмите Enter...")

    # ===== 2. ЛС + ГРУППА =====
    elif choice == "2":
        while True:
            clear_screen()
            print(r"""[#8F3ADB]
 _      ____  
| |    / ___| 
| |    \___ \ 
| |___  ___) |
|_____||____/ 
            [/#8F3ADB]""")

            print("[red][1][/red] Написать сообщение по ID")
            print("[red][2][/red] Написать в группу (быстро)")
            print("[red][3][/red] Назад в меню")

            ls_choice = input("\nВыберите действие: ").strip()

            if ls_choice == "1":
                clear_screen()
                print("[bold #8F3ADB]--- Отправка личного сообщения ---[/bold #8F3ADB]\n")
                target = input("Введите 6-значный ID получателя: ").strip()
                msg = input("Введите ваше сообщение: ").strip()

                if not target or not msg:
                    print("[red]Ошибка: ID или сообщение не могут быть пустыми.[/red]")
                elif not (target.isdigit() and len(target) == 6):
                    print("[red]Ошибка: ID — это ровно 6 цифр.[/red]")
                elif send_line(f"SEND:{target}:{msg}"):
                    print("[green][+] Сообщение отправлено! Ответ сервера (если ошибка) — в уведомлениях.[/green]")
                else:
                    print("[red]Ошибка: нет соединения с сервером.[/red]")

                input("\nНажмите Enter, чтобы продолжить...")

            elif ls_choice == "2":
                clear_screen()
                print("[bold #8F3ADB]--- Отправка в группу ---[/bold #8F3ADB]\n")
                gid = input("Введите ID или имя группы: ").strip()
                msg = input("Введите ваше сообщение: ").strip()

                if not gid or not msg:
                    print("[red]Ошибка: ID группы или сообщение не могут быть пустыми.[/red]")
                elif send_line(f"GMSG:{gid}:{msg}"):
                    print("[green][+] Сообщение отправлено в группу! Ошибки (если есть) — в уведомлениях.[/green]")
                else:
                    print("[red]Ошибка: нет соединения с сервером.[/red]")

                input("\nНажмите Enter, чтобы продолжить...")

            elif ls_choice == "3":
                break
            else:
                print("[red]Ошибка: выберите 1, 2 или 3.[/red]")
                input("Нажмите Enter...")

    # ===== 8. СМЕНА ЛИЧНОСТИ =====
    elif choice == "8":
        clear_screen()
        print("[bold #8F3ADB]--- Смена личности (ID) ---[/bold #8F3ADB]\n")
        print("[yellow]Внимание: вы выйдете из всех групп, а имя на сервере будет сброшено.[/yellow]\n")
        confirm = input("Вы уверены, что хотите сгенерировать НОВЫЙ уникальный ID? (y/n): ").strip().lower()
        if confirm == 'y':
            id_event.clear()
            if send_line("NEW_ID"):
                if id_event.wait(3) and connected:
                    print(f"[green][+] Ваш новый ID: {user_id}[/green]")
                else:
                    print("[red]Сервер не ответил вовремя. Проверьте уведомления.[/red]")
            else:
                print("[red]Ошибка: нет соединения с сервером.[/red]")
        else:
            print("[yellow]Смена личности отменена.[/yellow]")
        input("\nНажмите Enter, чтобы вернуться в меню...")

    # ===== 9. IP =====
    elif choice == "9":
        while True:
            clear_screen()
            print(r"""[#8F3ADB]
 ___ ____  
|_ _|  _ \ 
 | || |_) |
 | ||  __/ 
|___|_|    
            [/#8F3ADB]""")

            print(f"""[red]
+--------------------------------------------+
|       Сетевой интерфейс пользователя       |  
|--------------------------------------------| 
| Твой локальный IP:  [#8F3ADB]{user_ip:<22}[/#8F3ADB] |                  
+--------------------------------------------+ 
            [/red]""")

            print("[red][1][/red] Обновить IP-адрес")
            print("[red][2][/red] Назад в меню")

            ip_choice = input("\nВыберите действие: ").strip()

            if ip_choice == "1":
                user_ip = get_my_ip()
                print("[green][+] IP-адрес успешно обновлен![/green]")
                input("\nНажмите Enter, чтобы продолжить...")
            elif ip_choice == "2":
                break
            else:
                print("[red]Ошибка: выберите 1 или 2.[/red]")
                input("Нажмите Enter...")

    # ===== 10. ОЧИСТКА =====
    elif choice == "10":
        clear_screen()
        print("[bold green][+] Буфер экрана успешно уничтожен. Все следы чата стерты[/bold green]")
        input("\nНажмите Enter, чтобы вернуться в меню...")

    # ===== 3. УВЕДОМЛЕНИЯ =====
    elif choice == "3":
        while True:
            clear_screen()
            print(r"""[#8F3ADB]
 _   _ _   _ _____ 
| | | | | | |  ___|
| | | | | | | |__  
| |_| | |_| |  __| 
 \___/ \___/|_|    
            [/#8F3ADB]""")

            if not notifications:
                print("[yellow]Уведомлений пока нет.[/yellow]\n")
            else:
                print(f"[#8F3ADB]--- Последние уведомления ({len(notifications)})---[/#8F3ADB]\n")
                # Показывает последние 20
                for n in notifications[-20:]:
                    print(f"  • {escape(n)}")
                print()

            print("[red][1][/red] Очистить уведомления")
            print("[red][2][/red] Обновить")
            print("[red][3][/red] Назад в меню")

            u_choice = input("\nВыберите действие:  ").strip()

            if u_choice == "1":
                notifications.clear()
                print("[green][+] Уведомления очищены.[/green]")
                input("Нажмите на Enter, чтобы продолжить...")
            elif u_choice == "2":
                continue
            elif u_choice == "3":
                break
            else:
                print("[red]Ошибка: выберите верную цифру.[/red]")
                input("Нажмите Enter...")

    # ===== 6. СОЗДАТЬ ГРУППУ =====
    elif choice == "6":
        while True:
            clear_screen()
            print(r"""[#8F3ADB]
  ____                       _   
 / ___| _ __ ___  __ _  ___| |_ 
| |   | '__/ _ \/ _` |/ __| __|
| |___| | |  __/ (_| | (__| |_ 
 \____|_|  \___|\__,_|\___|\__|
            [/#8F3ADB]""")

            print("[red][1][/red] Создать новую группу")
            print("[red][2][/red] Назад в меню")

            c_choice = input("\nВыберите действие: ").strip()

            if c_choice == "1":
                # Имя группы — обязательно
                while True:
                    group_name = input("Введите имя группы: ").strip()
                    if not group_name:
                        print("[red]Ошибка: имя не может быть пустым.[/red]")
                        continue
                    if not valid_name(group_name) or group_name.isdigit():
                        print(f"[red]Ошибка: {escape(NAME_RULES)} Имя не должно состоять только из цифр.[/red]")
                        continue
                    break

                # Пароль — опционально, минимум 5 символов
                want_pass = input("Хотите поставить пароль? (y/n): ").strip().lower()
                if want_pass == "y":
                    while True:
                        password = input("Введите пароль (минимум 5 символов): ").strip()
                        if len(password) < 5:
                            print("[red]Ошибка: пароль должен быть не короче 5 символов.[/red]")
                            continue
                        break
                    ok = send_line(f"CREATE_GROUP:{group_name}:{password}")
                elif want_pass == "n":
                    ok = send_line(f"CREATE_GROUP:{group_name}")
                else:
                    print("[red]Ошибка: ответьте y или n.[/red]")
                    input("Нажмите Enter...")
                    continue

                if ok:
                    print("[green][+] Запрос отправлен. Результат — в уведомлениях (кнопка 3).[/green]")
                else:
                    print("[red]Ошибка: нет соединения с сервером.[/red]")
                input("Нажмите Enter...")

            elif c_choice == "2":
                break
            else:
                print("[red]Ошибка: выберите 1 или 2.[/red]")
                input("Нажмите Enter...")

    # ===== 5. МОИ ГРУППЫ (ЧАТ) =====
    elif choice == "5":
        # Запрос моих групп и ожидание ответа
        my_channels_event.clear()
        if not send_line("MY_CHANNELS"):
            clear_screen()
            print("[red]Ошибка: нет соединения с сервером.[/red]")
            input("Нажмите Enter...")
            continue
        my_channels_event.wait(3)

        if not my_channels:
            clear_screen()
            print("[yellow]Вы не состоите ни в одной группе.[/yellow]")
            input("Нажмите Enter...")
            continue

        clear_screen()
        print("[#8F3ADB]Ваши группы:[/#8F3ADB]\n")
        for i, (gid, name) in enumerate(my_channels, 1):
            print(f"  {i}. {escape(name)} (ID: {gid})")

        ch = input("\nВыберите номер (0 — выход): ").strip()
        if not ch.isdigit() or int(ch) == 0:
            continue
        idx = int(ch) - 1
        if idx < 0 or idx >= len(my_channels):
            continue

        gid, name = my_channels[idx]
        run_chat(gid, name)

    # ===== 7. ВСЕ ГРУППЫ =====
    elif choice == "7":
        while True:
            clear_screen()
            print(r"""[#8F3ADB]
  ____                       _       
 / ___|_ __ ___  _   _ _ __ | |_ ___ 
| |  _| '__/ _ \| | | | '_ \| __/ __|
| |_| | | | (_) | |_| | |_) | |_\__ \
 \____|_|  \___/ \__,_| .__/ \__|___/
                      |_|            
            [/#8F3ADB]""")

            print("[red][1][/red] Запросить список групп")
            print("[red][2][/red] Вступить в группу")
            print("[red][3][/red] Выйти из группы")
            print("[red][4][/red] Назад в меню")

            l_choice = input("\nВыберите действие: ").strip()

            if l_choice == "1":
                if send_line("LIST_GROUPS"):
                    print("[green][+] Запрос отправлен. Список — в уведомлениях.[/green]")
                else:
                    print("[red]Ошибка: нет соединения с сервером.[/red]")
                input("Нажмите Enter...")

            elif l_choice == "2":
                target = input("Введите ID или имя группы: ").strip()
                if not target:
                    print("[red]Ошибка: пустой ввод.[/red]")
                    input("Нажмите Enter...")
                    continue
                pw = input("Пароль (Enter, если группа без пароля): ").strip()
                ok = send_line(f"JOIN:{target}:{pw}" if pw else f"JOIN:{target}")
                if ok:
                    print("[green][+] Запрос на вступление отправлен. Ответ — в уведомлениях.[/green]")
                else:
                    print("[red]Ошибка: нет соединения с сервером.[/red]")
                input("Нажмите Enter...")

            elif l_choice == "3":
                gid = input("Введите ID или имя группы для выхода: ").strip()
                if not gid:
                    print("[red]Ошибка: пустой ввод.[/red]")
                    input("Нажмите Enter...")
                    continue

                if send_line(f"LEAVE:{gid}"):
                    print("[green][+] Запрос на выход отправлен. Ответ — в уведомлениях.[/green]")
                else:
                    print("[red]Ошибка: нет соединения с сервером.[/red]")
                input("Нажмите Enter...")

            elif l_choice == "4":
                break
            else:
                print("[red]Ошибка: выберите число от 1 до 4.[/red]")
                input("Нажмите Enter...")

    # ===== 4. НАСТРОЙКИ =====
    elif choice == "4":
        while True:
            clear_screen()
            print(r"""[#8F3ADB]
 ____       _   _            
/ ___|  ___| |_| |_ __ _ ___ 
\___ \ / _ \ __| __/ _` / __|
 ___) |  __/ |_| || (_| \__ \
|____/ \___|\__|\__\__,_|___/
            [/#8F3ADB]""")

            print(f"[#8F3ADB]=== {t('settings_title')} ===[/#8F3ADB]\n")
            print(f"Имя / Name:  [#8F3ADB]{escape(user_name)}[/#8F3ADB]")
            print(f"ID:          [#8F3ADB]{user_id}[/#8F3ADB]")
            print(f"IP:          [#8F3ADB]{user_ip}[/#8F3ADB]")
            print(f"Тема / Theme:[#8F3ADB] {theme}[/#8F3ADB]")
            print(f"Язык / Lang: [#8F3ADB]{lang.upper()}[/#8F3ADB]\n")

            print(f"[red][1][/red] {t('settings_name')}")
            print(f"[red][2][/red] {t('settings_lang')}")
            print(f"[red][3][/red] {t('settings_theme')}")
            print(f"[red][4][/red] {t('settings_back')}")

            s_choice = input(f"\n{t('settings_prompt')}").strip()

            if s_choice == "1":
                new_name = input("Введите новое имя / Enter new name: ").strip()
                if apply_new_name(new_name):
                    print("[green][+] OK[/green]")
                else:
                    print(f"[red]{escape(NAME_RULES)}[/red]")
                input("Нажмите Enter...")

            elif s_choice == "2":
                lang = "en" if lang == "ru" else "ru"
                print(f"[green][+] {t('settings_lang_changed')}[/green]")
                input("Нажмите Enter...")

            elif s_choice == "3":
                theme = "красная" if theme == "фиолетовая" else "фиолетовая"
                print(f"[green][+] Тема: {theme}[/green]")
                input("Нажмите Enter...")

            elif s_choice == "4":
                break
            else:
                print(f"[red]{t('settings_error')}[/red]")
                input("Нажмите Enter...")

    # ============ 11. О REVENROOM ============
    elif choice == "11":
        while True:
            clear_screen()
            print(r"""[#8F3ADB]
  ___    ____  _____ 
 / _ \  |  _ \| ____|
| | | | | |_) |  _|  
| |_| | |  _ <| |___ 
 \___/  |_| \_\_____|
            [/#8F3ADB]""")

            print(f"[red]{t('about_body')}[/red]")

            print(f"[red][1][/red] {t('about_back')}")

            a_choice = input("\nВыберите действие: ").strip()

            if a_choice == "1":
                break
            else:
                print(f"[red]{t('settings_error')}[/red]")
                input("Нажмите Enter...")
