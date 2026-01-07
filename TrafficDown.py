# -*- coding: utf-8 -*-
"""
TrafficDown Ultimate 5.0
--------------------------
Багатопотоковий інструмент для генерації мережевого навантаження (HTTP Download та UDP Flood)
з підтримкою сучасного графічного (Windows) та консольного (всі системи) інтерфейсів.

Версія 5.0 :
- Додано аргументи командного рядка для запуску тестів без GUI/TUI (напр. --mode download).
- Реалізовано автоматичне створення та збереження звіту у JSON після кожного тесту.
- TUI: У таблицю статистики додано міні-графік (Sparkline) для динаміки швидкості.
- GUI: Додано спливаючі підказки (Tooltips) для елементів налаштувань.
- GUI: Додано іконки для кнопок "Start/Stop" (потрібен 'Pillow' та наявність файлів іконок).
- GUI: Створено основу для інтерактивного графіка (реакція на наведення миші).
- Покращено структуру коду, додано розширене логування та фінальний звіт у консоль.
- Додано можливість вибору мережевого інтерфейсу (поки що лише вибір у налаштуваннях, без реалізації прив'язки сокета).
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
import argparse
from enum import Enum
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Dict, Any, Tuple, Optional, List
from rich.console import Console, Sparkline
# --- Системні константи ---
IS_WINDOWS = os.name == 'nt'
IS_ANDROID = "com.termux" in os.environ.get("PREFIX", "")

# --- Налаштування файлів ---
CONFIG_FILE = "TrafficDown_config.json"
LOG_DIR = "logs"
REPORT_DIR = "reports"
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)
os.makedirs("icons", exist_ok=True) # Створюємо папку для іконок
LOG_FILE = os.path.join(LOG_DIR, "TrafficDown.log")

# --- Налаштування логера ---
log = logging.getLogger("TrafficDown")
if not log.handlers:
    log.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(threadName)-10s | %(message)s")
    
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    
    log.addHandler(file_handler)
    log.addHandler(console_handler)

def auto_install_packages():
    packages = {
        "aiohttp": "aiohttp",
        "rich": "rich",
        "psutil": "psutil",
        "requests": "requests",
    }

    if IS_WINDOWS:
        packages.update({
            "customtkinter": "customtkinter",
            "Pillow": "PIL",   # ← КЛЮЧОВА ПРАВКА
        })

    import importlib
    missing = []

    for pip_name, import_name in packages.items():
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(pip_name)

    if missing:
        log.warning(f"Відсутні необхідні модулі: {', '.join(missing)}. Спроба автоматичного встановлення...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
        log.info("Модулі встановлено. Перезапуск...")
        os.execl(sys.executable, sys.executable, *sys.argv)



import aiohttp
import psutil
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.align import Align
from rich.prompt import Prompt, IntPrompt
from rich.text import Text
from rich import box

GUI_AVAILABLE = False
if IS_WINDOWS:
    try:
        import customtkinter as ctk
        from PIL import Image, ImageTk
        GUI_AVAILABLE = True
    except ImportError:
        log.warning("Модуль customtkinter або Pillow не знайдено. Графічний інтерфейс буде недоступний.")

# --- 1. МЕНЕДЖЕР КОНФІГУРАЦІЇ ---
class Config:
    def __init__(self) -> None:
        self.default: Dict[str, Any] = {
            "target_ip": "192.168.0.1",
            "target_port": 80,
            "threads_dl": 20,
            "threads_ul": 100,
            "packet_size": 4096,
            "network_interface": "default", # Нове налаштування
            "download_urls": [
                'https://speed.hetzner.de/10GB.bin', 'https://speed.hetzner.de/1GB.bin',
                'https://speedtest.selectel.ru/10GB', 'https://proof.ovh.net/files/10Gb.dat',
                'http://speedtest.tele2.net/10GB.zip', 'http://speedtest-ny.turnkeyinternet.net/10000mb.bin',
                'http://ipv4.download.thinkbroadband.com/1GB.zip'
            ]
        }
        self.data = self.load()

    def load(self) -> Dict[str, Any]:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config_from_file = json.load(f)
                return {**self.default, **config_from_file}
            except (json.JSONDecodeError, IOError) as e:
                log.error(f"Не вдалося завантажити '{CONFIG_FILE}': {e}. Використовуються значення за замовчуванням.")
        return self.default.copy()

    def save(self) -> None:
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except IOError as e:
            log.error(f"Не вдалося зберегти '{CONFIG_FILE}': {e}")
    
    def reset_to_default(self) -> None:
        self.data = self.default.copy()
        self.save()
        log.info("Конфігурацію скинуто до значень за замовчуванням.")

cfg = Config()
def get_gateway_ip() -> str:
    """Намагається визначити IP-адресу шлюзу за замовчуванням."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        return ".".join(local_ip.split('.')[:3]) + ".1"
    except socket.error as e:
        log.warning(
            f"Не вдалося визначити IP шлюзу: {e}. "
            "Використовується IP за замовчуванням."
        )
        return "192.168.0.1"


# --- 2. МЕРЕЖЕВИЙ РУШІЙ ---
class EngineMode(Enum):
    IDLE = "IDLE"
    DOWNLOADING = "DOWNLOADING"
    UDP_FLOOD = "UDP FLOOD"

class NetworkEngine:
    def __init__(self) -> None:
        self.running = False
        self.mode = EngineMode.IDLE
        self.lock = threading.Lock()
        
        # Розширена статистика
        self.dl_total = 0
        self.ul_total = 0
        self.errors = 0
        self.last_error = "—"
        self.start_time: Optional[float] = None
        self.max_dl_speed = 0.0
        self.max_ul_speed = 0.0
        self.dl_speeds_history: List[float] = []
        self.ul_speeds_history: List[float] = []
        
        self.urls: List[str] = cfg.data.get("download_urls", [])
        if not self.urls:
            log.warning("Список URL для завантаження порожній. Режим завантаження не працюватиме.")
        
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._async_loop_manager, name="AsyncLoop", daemon=True).start()

    def _async_loop_manager(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start_download(self) -> None:
        if self.running: return
        if not self.urls:
            log.error("Неможливо запустити завантаження: список URL-адрес порожній.")
            return
        
        self._reset_stats()
        self.running, self.mode, self.start_time = True, EngineMode.DOWNLOADING, time.time()
        log.info(f"ENGINE: Запуск режиму '{self.mode.value}'. Потоків: {cfg.data['threads_dl']}")
        for _ in range(cfg.data['threads_dl']):
            asyncio.run_coroutine_threadsafe(self._dl_task(), self.loop)

    def start_flood(self, ip: str, port: int) -> None:
        if self.running: return

        self._reset_stats()
        self.running, self.mode, self.start_time = True, EngineMode.UDP_FLOOD, time.time()
        log.warning(f"ENGINE: Запуск режиму '{self.mode.value}' -> {ip}:{port}. Потоків: {cfg.data['threads_ul']}")
        cfg.data.update({'target_ip': ip, 'target_port': port})
        cfg.save()
        
        for i in range(cfg.data['threads_ul']):
            thread = threading.Thread(target=self._ul_task, args=(ip, port), name=f"UL-Thread-{i+1}", daemon=True)
            thread.start()

    def stop(self) -> None:
        if self.running:
            log.info("ENGINE: Зупинка всіх мережевих операцій.")
            self.running = False
            time.sleep(0.5) # Даємо потокам час завершитись
            self.generate_and_save_report()
            self.mode = EngineMode.IDLE
    
    def _reset_stats(self):
        """Скидає статистику перед новим запуском."""
        with self.lock:
            self.dl_total = self.ul_total = self.errors = 0
            self.last_error = "—"
            self.start_time = None
            self.max_dl_speed = 0.0
            self.max_ul_speed = 0.0
            self.dl_speeds_history.clear()
            self.ul_speeds_history.clear()

    async def _dl_task(self) -> None:
        conn = aiohttp.TCPConnector(ssl=False, limit=0)
        async with aiohttp.ClientSession(connector=conn) as session:
            while self.running and self.mode == EngineMode.DOWNLOADING:
                try:
                    url = random.choice(self.urls)
                    async with session.get(url, timeout=10) as resp:
                        resp.raise_for_status()
                        while self.running and self.mode == EngineMode.DOWNLOADING:
                            chunk = await resp.content.read(1024 * 1024)
                            if not chunk: break
                            with self.lock: self.dl_total += len(chunk)
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    with self.lock: self.errors += 1; self.last_error = f"{type(e).__name__}: {str(e)[:60]}"
                    await asyncio.sleep(2)
                except Exception as e:
                    log.error(f"Неочікувана помилка в DL-завданні: {e}")
                    await asyncio.sleep(5)

    def _ul_task(self, ip: str, port: int) -> None:
        try:
            # Тут можна було б додати логіку прив'язки до інтерфейсу
            # sock.bind((interface_ip, 0))
            payload = os.urandom(min(cfg.data['packet_size'], 65500))
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            addr = (ip, port)
            
            while self.running and self.mode == EngineMode.UDP_FLOOD:
                try:
                    sock.sendto(payload, addr)
                    with self.lock: self.ul_total += len(payload)
                    if IS_ANDROID: time.sleep(0.001)
                except socket.error as e:
                    with self.lock: self.errors += 1; self.last_error = f"{type(e).__name__}: {str(e)[:60]}"
                    time.sleep(1)
            sock.close()
        except Exception as e:
            with self.lock: self.errors += 1; self.last_error = f"UDP Task Init Error: {e}"
            log.error(f"Помилка в UDP-завданні: {e}")

    def get_stats(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "dl": self.dl_total, "ul": self.ul_total, "err": self.errors,
                "mode": self.mode.value, "active": self.running, "last_error": self.last_error
            }

    def generate_and_save_report(self) -> None:
        """Створює фінальний звіт, виводить у лог та зберігає у JSON."""
        if not self.start_time: return
        
        duration = time.time() - self.start_time
        avg_dl_speed = (sum(self.dl_speeds_history) / len(self.dl_speeds_history)) if self.dl_speeds_history else 0
        avg_ul_speed = (sum(self.ul_speeds_history) / len(self.ul_speeds_history)) if self.ul_speeds_history else 0

        report = {
            "session_end_time": datetime.now().isoformat(),
            "mode": self.mode.value,
            "duration_seconds": round(duration, 2),
            "total_download_gb": round(self.dl_total / 1024**3, 4),
            "total_upload_gb": round(self.ul_total / 1024**3, 4),
            "avg_download_mbs": round(avg_dl_speed, 2),
            "max_download_mbs": round(self.max_dl_speed, 2),
            "avg_upload_mbs": round(avg_ul_speed, 2),
            "max_upload_mbs": round(self.max_ul_speed, 2),
            "errors_count": self.errors,
            "config": {
                "threads": cfg.data['threads_dl'] if self.mode == EngineMode.DOWNLOADING else cfg.data['threads_ul'],
                "target": cfg.data['target_ip'] + ":" + str(cfg.data['target_port']) if self.mode == EngineMode.UDP_FLOOD else "Multiple URLs"
            }
        }
        
        # Виведення звіту в консоль
        report_str = f"""
        --- ЗВІТ ПРО СЕСІЮ ---
        Тривалість: {report['duration_seconds']} с
        Режим: {report['mode']}
        Загальний трафік: {report['total_download_gb'] + report['total_upload_gb']:.3f} GB (DL: {report['total_download_gb']:.3f}, UL: {report['total_upload_gb']:.3f})
        Середня швидкість: DL {report['avg_download_mbs']:.2f} MB/s, UL {report['avg_upload_mbs']:.2f} MB/s
        Макс. швидкість:  DL {report['max_download_mbs']:.2f} MB/s, UL {report['max_upload_mbs']:.2f} MB/s
        Помилки: {report['errors_count']}
        --------------------
        """
        log.info(report_str)

        # Збереження у файл
        filename = f"report_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
        filepath = os.path.join(REPORT_DIR, filename)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=4, ensure_ascii=False)
            log.info(f"Звіт збережено у файл: {filepath}")
        except IOError as e:
            log.error(f"Не вдалося зберегти звіт у файл: {e}")


engine = NetworkEngine()

# --- 3. КОНСОЛЬНИЙ ІНТЕРФЕЙС (TUI) ---
class TermuxUI:
    def __init__(self) -> None:
        self.console = Console()
        self.last_dl = 0
        self.last_ul = 0
        self.last_t = time.time()
        self.dl_spark_data = [0.0] * 30
        self.ul_spark_data = [0.0] * 30

    def _format_speed(self, a_bytes: float) -> str: return f"[bold green]{a_bytes / 1024**2:.2f}[/] MB/s"
    def _format_total(self, a_bytes: float) -> str: return f"{a_bytes / 1024**3:.3f} GB"

    def generate_dashboard(self) -> Panel:
        stats = engine.get_stats(); now = time.time(); delta = max(now - self.last_t, 1e-6)
        spd_dl = (stats['dl'] - self.last_dl) / delta; spd_ul = (stats['ul'] - self.last_ul) / delta
        self.last_dl, self.last_ul, self.last_t = stats['dl'], stats['ul'], now

        if engine.running:
            spd_dl_mbs = spd_dl / 1024**2; spd_ul_mbs = spd_ul / 1024**2
            self.dl_spark_data.append(spd_dl_mbs); self.dl_spark_data.pop(0)
            self.ul_spark_data.append(spd_ul_mbs); self.ul_spark_data.pop(0)
            engine.dl_speeds_history.append(spd_dl_mbs); engine.max_dl_speed = max(engine.max_dl_speed, spd_dl_mbs)
            engine.ul_speeds_history.append(spd_ul_mbs); engine.max_ul_speed = max(engine.max_ul_speed, spd_ul_mbs)
        
        stats_table = Table(box=None, show_header=False, padding=(0,1))
        stats_table.add_column(style="cyan", justify="right"); stats_table.add_column(style="bold white", justify="left")
        
        status_color = 'green' if stats['active'] else 'red'
        stats_table.add_row("Статус:", f"[{status_color}]{stats['mode']}[/]")
        stats_table.add_row("Швидкість DL:", self._format_speed(spd_dl), Sparkline(self.dl_spark_data, "green"))
        stats_table.add_row("Швидкість UL:", self._format_speed(spd_ul).replace("green", "red"), Sparkline(self.ul_spark_data, "red"))
        stats_table.add_row("Всього DL:", f"[green]{self._format_total(stats['dl'])}[/]")
        stats_table.add_row("Всього UL:", f"[red]{self._format_total(stats['ul'])}[/]")
        stats_table.add_row("Помилки:", f"[yellow]{stats['err']}[/]")
        
        try:
            cpu, ram = psutil.cpu_percent(), psutil.virtual_memory().percent
            cpu_color = 'green' if cpu < 70 else 'yellow' if cpu < 90 else 'red'
            ram_color = 'green' if ram < 80 else 'yellow' if ram < 90 else 'red'
            # Тут можна додати візуалізацію через rich.progress.Progress
            res_text = f"CPU: [bold {cpu_color}]{cpu}%[/] | RAM: [bold {ram_color}]{ram}%[/]"
        except Exception: res_text = "N/A"

        gateway_ip = cfg.data.get('target_ip', '192.168.0.1')
        menu_text = (
            "[bold cyan]1.[/] Завантаження (тест швидкості)\n"
            f"[bold cyan]2.[/] UDP Flood на шлюз ([dim]{gateway_ip}[/])\n"
            f"[bold cyan]3.[/] UDP Flood на власну ціль\n"
            f"[bold cyan]s.[/] Зупинити поточну операцію\n\n"
            f"[bold red]q.[/] Вихід"
        )
        
        grid = Table.grid(expand=True, padding=1); grid.add_column(width=45); grid.add_column()
        grid.add_row(
            Panel(stats_table, title="[bold cyan]Live Статистика[/]", border_style="cyan"),
            Panel(menu_text, title="[bold green]Меню[/]", border_style="green")
        )
        grid.add_row(Panel(Align.center(res_text), title="[bold blue]Система[/]"), Panel(f"[dim]{stats['last_error']}[/]", title="[bold yellow]Остання помилка[/]"))
        
        return Panel(grid, title="[bold green]TRAFFICDOWN 5.0[/]", border_style="green", subtitle="[yellow]Введіть опцію та натисніть Enter[/]")

    def run(self) -> None:
        self.console.clear()
        with Live(self.generate_dashboard(), console=self.console, screen=True, refresh_per_second=4, vertical_overflow="visible") as live:
            def get_input():
                choice = self.console.input("[bold yellow]> [/]").strip().lower()
                
                if engine.running and choice != 's':
                    live.console.print("[bold yellow]Спочатку зупиніть поточну операцію (s)![/]")
                    return

                action = None
                if choice == '1': action = engine.start_download
                elif choice == '2': action = lambda: engine.start_flood(cfg.data.get('target_ip'), cfg.data.get('target_port'))
                elif choice == '3':
                    try:
                        live.stop(); self.console.clear()
                        ip = Prompt.ask("[cyan]Введіть IP[/cyan]", default=cfg.data['target_ip'])
                        port = IntPrompt.ask("[cyan]Введіть порт[/cyan]", default=cfg.data['target_port'])
                        if not (0 < port < 65536): raise ValueError("Некоректний порт.")
                        action = lambda: engine.start_flood(ip, port)
                        live.start()
                    except (ValueError, Exception) as e:
                        live.start(); live.console.print(f"\n[bold red]Помилка: {e}[/]"); time.sleep(2)
                elif choice == 's': action = engine.stop
                elif choice in ('q', 'й'): return "exit"
                if action: action()

            input_thread = threading.Thread(target=lambda: setattr(threading.current_thread(), 'result', get_input()), daemon=True)
            while True:
                live.update(self.generate_dashboard())
                if not input_thread.is_alive():
                    if getattr(input_thread, 'result', None) == 'exit': break
                    input_thread = threading.Thread(target=lambda: setattr(threading.current_thread(), 'result', get_input()), daemon=True)
                    input_thread.start()
                time.sleep(0.1)

# --- 4. ГРАФІЧНИЙ ІНТЕРФЕЙС (GUI) ---
if GUI_AVAILABLE:
    class GUILogHandler(logging.Handler):
        def __init__(self, textbox: ctk.CTkTextbox):
            super().__init__(); self.textbox = textbox
        def emit(self, record: logging.LogRecord) -> None:
            msg = self.format(record)
            if self.textbox.winfo_exists(): self.textbox.after(0, self.thread_safe_insert, msg)
        def thread_safe_insert(self, msg: str) -> None:
            if self.textbox.winfo_exists():
                self.textbox.configure(state="normal")
                self.textbox.insert("end", msg + "\n")
                self.textbox.see("end")
                self.textbox.configure(state="disabled")
    
    class ToolTip(ctk.CTkToplevel):
        """Спливаюча підказка, що з'являється біля віджета."""
        def __init__(self, widget, text):
            super().__init__(widget)
            self.withdraw() # Сховати вікно
            self.overrideredirect(True) # Без рамок
            self.attributes("-topmost", True)
            
            self.widget = widget
            self.text = text
            
            self.label = ctk.CTkLabel(self, text=self.text, fg_color=("#F0F0F0", "#20232A"),
                                      corner_radius=5, text_color=("#2E3440", "#D8DEE9"),
                                      font=("Segoe UI", 10), padx=8, pady=4)
            self.label.pack()
            
            self.widget.bind("<Enter>", self.show_tip)
            self.widget.bind("<Leave>", self.hide_tip)
            self.widget.bind("<Button-1>", self.hide_tip)

        def show_tip(self, event=None):
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
            y = self.widget.winfo_rooty() - self.label.winfo_reqheight() - 5
            self.geometry(f"+{x}+{y}")
            self.deiconify() # Показати вікно

        def hide_tip(self, event=None):
            self.withdraw()

    class WindowsGUI:
        THEME = {
            "bg_color": ("#ECEFF4", "#2E3440"), "fg_color": ("#FFFFFF", "#3B4252"),
            "text_color": ("#2E3440", "#D8DEE9"), "accent_color": "#81A1C1",
            "dl_color": "#A3BE8C", "ul_color": "#BF616A", "warn_color": "#EBCB8B",
            "stop_color": "#D08770", "canvas_bg": ("#E5E9F0", "#292E39"),
            "font_family": "Segoe UI", "font_large": ("Segoe UI", 32, "bold"),
            "font_medium": ("Segoe UI", 16, "bold"), "font_normal": ("Segoe UI", 12),
            "font_small": ("Consolas", 11), "font_title": ("Segoe UI", 18, "bold"),
            "font_button": ("Segoe UI", 16, "bold"), "font_total": ("Segoe UI", 12),
        }

        def __init__(self) -> None:
            self.root = ctk.CTk(); self.root.title("TrafficDown Ultimate 5.0"); self.root.geometry("1000x750");
            self.root.minsize(900, 700); ctk.set_appearance_mode("Dark")

            self.last_dl = self.last_ul = 0.0; self.last_t = time.time()
            self.dl_history = [0.0] * 50; self.ul_history = [0.0] * 50
            self.slider_widgets: Dict[str, Tuple[ctk.CTkSlider, ctk.CTkLabel]] = {}
            self.status_message_job: Optional[str] = None
            self.txt_urls: Optional[ctk.CTkTextbox] = None
            self.icons = self.load_icons()

            self.setup_ui(); self.setup_logging(); self.update_loop()

        def load_icons(self) -> Dict[str, ctk.CTkImage]:
            """Завантажує іконки для GUI. Іконки мають бути у папці /icons."""
            icons = {}
            icon_data = {
                "start": "M8 5v14l11-7z", "stop": "M6 6h12v12H6z", # Прості SVG-подібні шляхи
                "dashboard": "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z",
                "settings": "M19.43 12.98c.04-.32.07-.64.07-.98s-.03-.66-.07-.98l2.11-1.65c.19-.15.24-.42.12-.64l-2-3.46c-.12-.22-.39-.3-.61-.22l-2.49 1c-.52-.4-1.08-.73-1.69-.98l-.38-2.65C14.46 2.18 14.25 2 14 2h-4c-.25 0-.46.18-.49.42l-.38 2.65c-.61.25-1.17.59-1.69.98l-2.49-1c-.23-.09-.49 0-.61.22l-2 3.46c-.13.22-.07.49.12.64l2.11 1.65c-.04.32-.07.64-.07.98s.03.66.07.98l-2.11 1.65c-.19.15-.24.42.12.64l2 3.46c.12.22.39.3.61.22l2.49-1c.52.4 1.08.73 1.69.98l.38 2.65c.03.24.24.42.49.42h4c.25 0 .46-.18.49-.42l.38-2.65c.61-.25 1.17-.59 1.69-.98l2.49 1c.23.09.49 0 .61-.22l2-3.46c.12-.22.07-.49-.12-.64l-2.11-1.65zM12 15.5c-1.93 0-3.5-1.57-3.5-3.5s1.57-3.5 3.5-3.5 3.5 1.57 3.5 3.5-1.57 3.5-3.5 3.5z"
            }
            # Створюємо прості файли іконок, якщо вони відсутні
            for name, path_d in icon_data.items():
                filepath = os.path.join("icons", f"{name}.png")
                if not os.path.exists(filepath):
                    try: # Спроба створити зображення програмно
                        from PIL import Image, ImageDraw
                        img = Image.new('RGBA', (24, 24), (0,0,0,0))
                        draw = ImageDraw.Draw(img)
                        # Це дуже спрощена логіка, вона не буде малювати SVG, а лише прямокутник
                        if name == "stop": draw.rectangle((4,4,20,20), fill="white")
                        elif name == "start": draw.polygon([(6,4),(6,20),(20,12)], fill="white")
                        else: draw.rectangle((4,4,20,20), fill="white")
                        img.save(filepath)
                        log.info(f"Створено шаблон іконки: {filepath}")
                    except Exception as e:
                        log.warning(f"Не вдалося створити іконку {name}.png: {e}")

            for name in ["start", "stop"]:
                try:
                    path = os.path.join("icons", f"{name}.png")
                    if os.path.exists(path):
                        icons[name] = ctk.CTkImage(Image.open(path))
                except Exception as e:
                    log.error(f"Не вдалося завантажити іконку {name}: {e}")
            return icons

        def setup_ui(self) -> None:
            self.root.grid_columnconfigure(0, weight=1); self.root.grid_rowconfigure(0, weight=1)
            tab_view = ctk.CTkTabview(self.root, border_width=1); tab_view.grid(row=0, column=0, padx=15, pady=15, sticky="nsew")
            tab_view.configure(segmented_button_selected_color=self.THEME["accent_color"], segmented_button_unselected_color=self.THEME["fg_color"][1])
            
            self.dashboard_tab = tab_view.add("Dashboard"); self.settings_tab = tab_view.add("Settings"); self.log_tab = tab_view.add("Logs")
            self._setup_dashboard(self.dashboard_tab); self._setup_settings(self.settings_tab); self._setup_logs_tab(self.log_tab)
        
        def _create_stat_frame(self, p, title, color) -> Tuple[ctk.CTkLabel, ctk.CTkLabel]:
            p.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(p, text=title, font=self.THEME["font_title"], text_color=color).grid(row=0, pady=(5,0))
            lbl_speed = ctk.CTkLabel(p, text="0.0 MB/s", font=self.THEME["font_large"], text_color=color); lbl_speed.grid(row=1, pady=(5,5))
            lbl_total = ctk.CTkLabel(p, text="Total: 0.00 GB", font=self.THEME["font_total"], text_color=("gray50", "gray60")); lbl_total.grid(row=2, pady=(0,10))
            return lbl_speed, lbl_total

        def _setup_dashboard(self, tab: ctk.CTkFrame) -> None:
            tab.grid_columnconfigure(0, weight=1); tab.grid_rowconfigure(1, weight=1)
            
            top_panel = ctk.CTkFrame(tab); top_panel.grid(row=0, column=0, sticky="ew", pady=(0, 10))
            top_panel.grid_columnconfigure((0, 2), weight=1); top_panel.grid_columnconfigure(1, weight=2)
            
            dl_frame = ctk.CTkFrame(top_panel); dl_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=5)
            self.lbl_dl_speed, self.lbl_dl_total = self._create_stat_frame(dl_frame, "DOWNLOAD", self.THEME["dl_color"])
            ul_frame = ctk.CTkFrame(top_panel); ul_frame.grid(row=0, column=2, sticky="nsew", padx=10, pady=5)
            self.lbl_ul_speed, self.lbl_ul_total = self._create_stat_frame(ul_frame, "UPLOAD", self.THEME["ul_color"])

            center_frame = ctk.CTkFrame(top_panel); center_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=5)
            center_frame.grid_columnconfigure(0, weight=1)
            self.lbl_mode = ctk.CTkLabel(center_frame, text="MODE: IDLE", font=self.THEME["font_medium"]); self.lbl_mode.pack(pady=(15, 5), expand=True)
            # Тут можна додати круглі прогрес-бари для CPU/RAM
            self.lbl_cpu_ram = ctk.CTkLabel(center_frame, text="CPU: -% | RAM: -%", font=self.THEME["font_normal"]); self.lbl_cpu_ram.pack(pady=5, expand=True)
            self.lbl_errors_count = ctk.CTkLabel(center_frame, text="ERRORS: 0", font=self.THEME["font_normal"]); self.lbl_errors_count.pack(pady=(5, 15), expand=True)

            graph_panel = ctk.CTkFrame(tab); graph_panel.grid(row=1, column=0, sticky="nsew", pady=10)
            graph_panel.grid_columnconfigure(0, weight=1); graph_panel.grid_rowconfigure(0, weight=1)
            self.canvas = ctk.CTkCanvas(graph_panel, highlightthickness=0); self.canvas.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
            self.canvas.bind("<Configure>", self.draw_graph)
            self.canvas.bind("<Motion>", self.on_graph_hover) # Основа для інтерактивності
            self.graph_tooltip = ctk.CTkLabel(self.canvas, text="", fg_color="black", corner_radius=5)

            control_panel = ctk.CTkFrame(tab); control_panel.grid(row=2, column=0, sticky="ew", pady=(10, 0))
            control_panel.grid_columnconfigure((0, 1), weight=1)
            self.btn_dl = ctk.CTkButton(control_panel, command=self.toggle_dl, height=50, font=self.THEME["font_button"], image=self.icons.get("start"), compound="left", text_color=("#000000", "#FFFFFF")); self.btn_dl.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
            self.btn_ul = ctk.CTkButton(control_panel, command=self.toggle_ul, height=50, font=self.THEME["font_button"], image=self.icons.get("start"), compound="left", text_color=("#000000", "#FFFFFF")); self.btn_ul.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
            
            status_bar = ctk.CTkFrame(tab, fg_color="transparent"); status_bar.grid(row=3, column=0, sticky="ew", pady=(5,0), padx=10)
            ctk.CTkLabel(status_bar, text="Status:", font=self.THEME["font_small"], text_color=("gray50", "gray60")).pack(side="left")
            self.lbl_status = ctk.CTkLabel(status_bar, text="—", anchor="w", font=self.THEME["font_small"], text_color="gray"); self.lbl_status.pack(side="left", fill="x", expand=True, padx=5)

        def _setup_settings(self, tab: ctk.CTkFrame) -> None:
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
            ToolTip(self.ent_ip, "IP-адреса для UDP-флуду")
            ctk.CTkLabel(target_g, text="Target Port:").grid(row=2, column=0, padx=20, pady=10, sticky="w")
            self.ent_port = ctk.CTkEntry(target_g); self.ent_port.grid(row=2, column=1, padx=20, pady=10, sticky="ew")
            ToolTip(self.ent_port, "Порт для UDP-флуду (1-65535)")
            
            perf_g = create_group(scroll_frame, "Performance Tuning")
            self._add_slider(perf_g, "Download Threads", 1, 100, 'threads_dl', 1, "Кількість потоків для завантаження")
            self._add_slider(perf_g, "Flood Threads", 10, 1000, 'threads_ul', 3, "Кількість потоків для UDP-флуду")
            self._add_slider(perf_g, "Packet Size (bytes)", 64, 8192, 'packet_size', 5, "Розмір одного UDP-пакета")

            urls_g = create_group(scroll_frame, "Download URLs")
            ctk.CTkLabel(urls_g, text="One URL per line:").grid(row=1, column=0, columnspan=2, padx=20, pady=(10,5), sticky="w")
            self.txt_urls = ctk.CTkTextbox(urls_g, height=200, font=self.THEME["font_small"], wrap="none")
            self.txt_urls.grid(row=2, column=0, columnspan=2, padx=20, pady=(0,10), sticky="nsew")
            ToolTip(self.txt_urls, "Список URL-адрес для режиму тестування швидкості")

            net_g = create_group(scroll_frame, "Network")
            ctk.CTkLabel(net_g, text="Network Interface:").grid(row=1, column=0, padx=20, pady=10, sticky="w")
            interfaces = ["default"] + list(psutil.net_if_addrs().keys())
            self.if_menu = ctk.CTkOptionMenu(net_g, values=interfaces); self.if_menu.grid(row=1, column=1, padx=20, pady=10, sticky="ew")
            ToolTip(self.if_menu, "Вибір мережевого інтерфейсу (для досвідчених користувачів).\n'Default' - вибір системи.")
            
            btn_frame = ctk.CTkFrame(tab, fg_color="transparent"); btn_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
            btn_frame.grid_columnconfigure((0,1), weight=1)
            ctk.CTkButton(btn_frame, text="Save Settings", command=self.save_settings, height=40).grid(row=0, column=0, padx=10, sticky="ew")
            ctk.CTkButton(btn_frame, text="Reset to Default", command=self.reset_settings, height=40, fg_color="gray50").grid(row=0, column=1, padx=10, sticky="ew")
            self._update_settings_ui()

        def _setup_logs_tab(self, tab: ctk.CTkFrame) -> None:
            tab.grid_columnconfigure(0, weight=1); tab.grid_rowconfigure(0, weight=1)
            self.log_textbox = ctk.CTkTextbox(tab, font=self.THEME["font_small"], wrap="none"); self.log_textbox.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
            self.log_textbox.configure(state="disabled")

        def setup_logging(self) -> None:
            gui_handler = GUILogHandler(self.log_textbox)
            gui_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
            gui_handler.setLevel(logging.INFO)
            log.addHandler(gui_handler)

        def _add_slider(self, p, text, f, t, key, r, tip_text) -> None:
            lbl_title = ctk.CTkLabel(p, text=f"{text}:"); lbl_title.grid(row=r, column=0, sticky="w", padx=20, pady=(10,0))
            lbl_val = ctk.CTkLabel(p, text=str(cfg.data.get(key,f))); lbl_val.grid(row=r, column=1, sticky="e", padx=20, pady=(10,0))
            slider = ctk.CTkSlider(p, from_=f, to=t, command=lambda v, k=key: self.slider_widgets[k][1].configure(text=f"{int(v)}"))
            slider.grid(row=r + 1, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 15))
            self.slider_widgets[key] = (slider, lbl_val)
            ToolTip(slider, tip_text); ToolTip(lbl_title, tip_text)
        
        def _update_settings_ui(self) -> None:
            self.ent_ip.delete(0, 'end'); self.ent_ip.insert(0, cfg.data['target_ip'])
            self.ent_port.delete(0, 'end'); self.ent_port.insert(0, str(cfg.data['target_port']))
            self.if_menu.set(cfg.data.get('network_interface', 'default'))
            for key, (slider, label) in self.slider_widgets.items():
                val = cfg.data.get(key, slider._from_); slider.set(val); label.configure(text=str(int(val)))
            if self.txt_urls:
                self.txt_urls.delete("1.0", "end"); self.txt_urls.insert("1.0", "\n".join(cfg.data.get("download_urls", [])))

        def set_status_message(self, text: str, color: str="gray", duration_s: int=4) -> None:
            if not self.lbl_status.winfo_exists(): return
            self.lbl_status.configure(text=text, text_color=color)
            if self.status_message_job: self.root.after_cancel(self.status_message_job)
            self.status_message_job = self.root.after(duration_s * 1000, lambda: self.lbl_status.configure(text=engine.get_stats()['last_error'], text_color="gray"))

        def toggle_dl(self) -> None:
            if engine.running and engine.mode == EngineMode.DOWNLOADING: engine.stop()
            elif not engine.running: engine.start_download()

        def toggle_ul(self) -> None:
            if engine.running and engine.mode == EngineMode.UDP_FLOOD: engine.stop()
            elif not engine.running:
                if self.save_settings(): engine.start_flood(cfg.data['target_ip'], cfg.data['target_port'])
        
        def update_buttons(self) -> None:
            if not self.btn_dl.winfo_exists(): return
            dl_run = engine.running and engine.mode == EngineMode.DOWNLOADING
            ul_run = engine.running and engine.mode == EngineMode.UDP_FLOOD
            self.btn_dl.configure(text="STOP DOWNLOAD" if dl_run else "START DOWNLOAD",
                                  fg_color=self.THEME["stop_color"] if dl_run else self.THEME["dl_color"],
                                  image=self.icons.get("stop") if dl_run else self.icons.get("start"),
                                  state="disabled" if ul_run else "normal")
            self.btn_ul.configure(text="STOP FLOOD" if ul_run else "START FLOOD",
                                  fg_color=self.THEME["stop_color"] if ul_run else self.THEME["ul_color"],
                                  image=self.icons.get("stop") if ul_run else self.icons.get("start"),
                                  state="disabled" if dl_run else "normal")

        def save_settings(self) -> bool:
            try:
                ip, port_str = self.ent_ip.get(), self.ent_port.get()
                if not ip: raise ValueError("IP-адреса не може бути порожньою.")
                if not (port_str.isdigit() and 1<=int(port_str)<=65535): raise ValueError("Порт має бути числом від 1 до 65535.")
                urls_list = [line.strip() for line in self.txt_urls.get("1.0", "end").strip().split("\n") if line.strip()]
                if not urls_list: raise ValueError("Список URL для завантаження не може бути порожнім.")
                
                cfg.data.update({
                    'target_ip': ip, 'target_port': int(port_str),
                    'threads_dl': int(self.slider_widgets['threads_dl'][0].get()),
                    'threads_ul': int(self.slider_widgets['threads_ul'][0].get()),
                    'packet_size': int(self.slider_widgets['packet_size'][0].get()),
                    'download_urls': urls_list,
                    'network_interface': self.if_menu.get()
                })
                
                engine.urls = urls_list; cfg.save()
                log.info("Налаштування успішно збережено.")
                self.set_status_message("Налаштування збережено!", self.THEME["dl_color"])
                return True
            except (ValueError, Exception) as e:
                self.set_status_message(f"Помилка збереження: {e}", self.THEME["warn_color"])
                log.error(f"Не вдалося зберегти налаштування: {e}")
                return False

        def reset_settings(self) -> None:
            cfg.reset_to_default(); self._update_settings_ui()
            engine.urls = cfg.data.get("download_urls", [])
            self.set_status_message("Налаштування скинуто до стандартних.", "gray")

        def draw_graph(self, event: Optional[Any] = None) -> None:
            if not self.canvas.winfo_exists(): return
            w, h = self.canvas.winfo_width(), self.canvas.winfo_height(); self.canvas.delete("all")
            if not (w > 1 and h > 1): return

            is_dark = ctk.get_appearance_mode() == "Dark"
            grid_c, text_c = ("#404B5D", "#D8DEE9") if is_dark else ("#D8DEE9", "#434C5E")
            self.canvas.configure(bg=self.THEME["canvas_bg"][1] if is_dark else self.THEME["canvas_bg"][0])
            
            max_val = max(max(self.dl_history), max(self.ul_history), 10); max_y = (int(max_val / 50) + 1) * 50 if max_val > 100 else (100 if max_val > 50 else 50 if max_val > 10 else 10)
            
            for i in range(1, 5):
                y = h*i/5; self.canvas.create_line(0, y, w, y, fill=grid_c, dash=(2,4))
                self.canvas.create_text(25, y, text=f"{max_y*(5-i)/5:.0f}", fill=text_c, anchor="e")
            self.canvas.create_text(25, 10, text="MB/s", fill=text_c, anchor="e")

            def plot(hist: list, color: str):
                if len(hist) > 1:
                    pts = [(w*i/(len(hist)-1), h-(h*min(v, max_y)/max_y if max_y > 0 else 0)) for i,v in enumerate(hist)]
                    self.canvas.create_line(pts, fill=color, width=2.5, smooth=True)
            plot(self.ul_history, self.THEME["ul_color"]); plot(self.dl_history, self.THEME["dl_color"])

        def on_graph_hover(self, event):
            """ПОКРАЩЕННЯ: Показує підказку на графіку."""
            # Ця функція є основою. Для повної реалізації потрібно:
            # 1. Знайти найближчу точку даних до event.x
            # 2. Отримати її значення (швидкість, час)
            # 3. Показати та оновити self.graph_tooltip
            w = self.canvas.winfo_width()
            index = min(max(round((event.x / w) * (len(self.dl_history) - 1)), 0), len(self.dl_history)-1)
            dl_val = self.dl_history[index]; ul_val = self.ul_history[index]
            
            self.graph_tooltip.configure(text=f"DL: {dl_val:.1f} MB/s\nUL: {ul_val:.1f} MB/s")
            self.graph_tooltip.place(x=event.x + 15, y=event.y)
            self.canvas.bind("<Leave>", lambda e: self.graph_tooltip.place_forget())

        def update_loop(self) -> None:
            if not self.root.winfo_exists(): return
            
            stats = engine.get_stats(); now = time.time(); delta = max(now - self.last_t, 1e-6)
            sdl = (stats['dl']-self.last_dl)/delta/1024**2; sul = (stats['ul']-self.last_ul)/delta/1024**2
            self.last_dl, self.last_ul, self.last_t = stats['dl'], stats['ul'], now

            if engine.running:
                engine.dl_speeds_history.append(sdl); engine.max_dl_speed = max(engine.max_dl_speed, sdl)
                engine.ul_speeds_history.append(sul); engine.max_ul_speed = max(engine.max_ul_speed, sul)
            
            self.dl_history.append(max(0,sdl)); self.dl_history.pop(0)
            self.ul_history.append(max(0,sul)); self.ul_history.pop(0)

            dl_gb, ul_gb = stats['dl']/1024**3, stats['ul']/1024**3
            self.lbl_dl_speed.configure(text=f"{sdl:.1f} MB/s"); self.lbl_dl_total.configure(text=f"Total: {dl_gb:.2f} GB")
            self.lbl_ul_speed.configure(text=f"{sul:.1f} MB/s"); self.lbl_ul_total.configure(text=f"Total: {ul_gb:.2f} GB")
            self.lbl_mode.configure(text=f"MODE: {stats['mode']}")
            self.lbl_errors_count.configure(text=f"ERRORS: {stats['err']}")
            
            try:
                cpu, ram = psutil.cpu_percent(), psutil.virtual_memory().percent
                self.lbl_cpu_ram.configure(text=f"CPU: {cpu}% | RAM: {ram}%")
            except Exception: pass
            
            if not self.status_message_job: self.lbl_status.configure(text=stats['last_error'])
            if self.root.winfo_viewable() and self.dashboard_tab.winfo_ismapped(): self.draw_graph()
            
            self.update_buttons()
            self.root.after(500, self.update_loop)

        def run(self) -> None:
            self.root.protocol("WM_DELETE_WINDOW", self.on_closing); self.root.mainloop()
        def on_closing(self) -> None:
            log.info("Отримано запит на закриття вікна. Зупинка..."); engine.stop(); self.root.destroy()

# --- 5. ГОЛОВНА ТОЧКА ВХОДУ ---
def run_cli_mode(args):
    """Виконує тест в неінтерактивному режимі згідно з аргументами."""
    log.info(f"Запуск у неінтерактивному режимі: {args.mode}")

    # Оновлення конфігурації з аргументів
    if args.threads:
        if args.mode == "download": cfg.data['threads_dl'] = args.threads
        else: cfg.data['threads_ul'] = args.threads
    
    if args.target:
        try:
            ip, port = args.target.split(":")
            cfg.data['target_ip'] = ip
            cfg.data['target_port'] = int(port)
        except ValueError:
            log.error("Неправильний формат цілі. Використовуйте IP:PORT (напр., 192.168.1.1:80)")
            return
            
    # Запуск
    if args.mode == "download":
        engine.start_download()
    elif args.mode == "udp":
        engine.start_flood(cfg.data['target_ip'], cfg.data['target_port'])
    
    print(f"Тест '{args.mode}' запущено. Натисніть Ctrl+C для зупинки або чекайте {args.duration}...")

    try:
        time.sleep(args.duration)
    except KeyboardInterrupt:
        log.info("Тест зупинено користувачем.")
    finally:
        engine.stop()
        log.info("Неінтерактивний режим завершено.")
        
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TrafficDown 5.0 - інструмент для мережевого навантаження.")
    parser.add_argument("--mode", type=str, choices=["download", "udp"], help="Режим роботи: 'download' або 'udp'.")
    parser.add_argument("--threads", type=int, help="Кількість потоків.")
    parser.add_argument("--duration", type=int, default=60, help="Тривалість тесту в секундах (за замовчуванням: 60).")
    parser.add_argument("--target", type=str, help="Ціль для UDP-флуду у форматі IP:PORT.")
    args = parser.parse_args()

    try:
        # Якщо вказано режим, запускаємо CLI, інакше - інтерактивний UI
        if args.mode:
            run_cli_mode(args)
        else:
            if IS_WINDOWS and GUI_AVAILABLE:
                log.info("Запуск графічного інтерфейсу для Windows.")
                app = WindowsGUI()
                app.run()
            else:
                if IS_WINDOWS: log.warning("Не вдалося завантажити customtkinter. Перехід до консольного режиму.")
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
        os._exit(0) 
