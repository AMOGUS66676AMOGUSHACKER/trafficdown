# -*- coding: utf-8 -*-
"""
TrafficDown Ultimate 5.0 (Visually Enhanced)
---------------------------------------------
Багатопотоковий інструмент для генерації мережевого навантаження (HTTP Download та UDP Flood)
з підтримкою сучасного графічного (Windows) та консольного (всі системи) інтерфейсів.

Version 5.1 (Visual Style Update):
- Інтегровано новий візуальний стиль згідно з наданими вимогами.
- GUI: Додано 8-px grid, нова палітра кольорів (Nord), уніфіковані шрифти.
- GUI: Графік тепер має 15% відступ зверху, градієнтну заливку, інтерактивний crosshair та паузу при наведенні.
- GUI: Реалізовано Toast-повідомлення, inline-валідацію для полів та "Empty State" для графіка.
- GUI: Додано Tooltip для неактивних кнопок та авто-визначення теми ОС.
- GUI: Стилі кнопок розділено на Primary, Danger, Secondary.
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
            "Pillow": "PIL",
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
        from PIL import Image
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
            "network_interface": "default",
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
            time.sleep(0.5)
            self.generate_and_save_report()
            self.mode = EngineMode.IDLE
    
    def _reset_stats(self):
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
        
        report_str = f"""
        --- ЗВІТ ПРО СЕСІЮ ---
        Тривалість: {report['duration_seconds']} с...
        """
        log.info(report_str)

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
# ... (TUI class remains unchanged, as requested modifications were for the GUI)
class Sparkline:
    """A simple sparkline generator for Rich."""
    def __init__(self, data, color="green"):
        self.data = data
        self.color = color
        self.bars = " ▂▃▄▅▆▇█"
    
    def __rich__(self) -> Text:
        if not self.data: return Text("")
        max_val = max(self.data) if self.data else 1
        text = Text(style=self.color)
        for val in self.data:
            index = int((val / max_val) * (len(self.bars) - 1)) if max_val > 0 else 0
            text.append(self.bars[index])
        return text

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
        stats_table.add_column(style="cyan", justify="right"); stats_table.add_column(style="bold white", justify="left"); stats_table.add_column()
        
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
        def __init__(self, widget, text_func):
            super().__init__(widget)
            self.withdraw()
            self.overrideredirect(True)
            self.attributes("-topmost", True)
            
            self.widget = widget
            self.text_func = text_func
            self.text = ""
            
            self.label = ctk.CTkLabel(self, text="", bg_color="#20232A",
                                      corner_radius=4, font=("Segoe UI", 11), padx=8, pady=4,)
            self.label.pack()
            
            self.widget.bind("<Enter>", self.show_tip)
            self.widget.bind("<Leave>", self.hide_tip)
            self.widget.bind("<Button-1>", self.hide_tip)

        def show_tip(self, event=None):
            self.text = self.text_func()
            if not self.text:
                return
            self.label.configure(text=self.text)
            x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2 - self.label.winfo_reqwidth() // 2
            y = self.widget.winfo_rooty() - self.label.winfo_reqheight() - 8
            self.geometry(f"+{x}+{y}")
            self.deiconify()

        def hide_tip(self, event=None):
            self.withdraw()
    
    class Toast(ctk.CTkToplevel):
        def __init__(self, master, message, status):
            super().__init__(master)
            self.overrideredirect(True)
            self.attributes("-topmost", True)
            
            is_dark = ctk.get_appearance_mode() == "Dark"
            colors = {
                "success": ("#A3BE8C", "#2E3440") if is_dark else ("#A3BE8C", "#FFFFFF"),
                "warning": ("#EBCB8B", "#2E3440") if is_dark else ("#EBCB8B", "#2E3440"),
                "error":   ("#BF616A", "#FFFFFF") if is_dark else ("#BF616A", "#FFFFFF"),
            }
            bg_color, text_color = colors.get(status, (None, None))

            self.label = ctk.CTkLabel(self, text=message, corner_radius=6, padx=16, pady=12,
                                      font=("Segoe UI", 13), fg_color=bg_color, text_color=text_color)
            self.label.pack()

            self.update_idletasks()
            x = master.winfo_rootx() + master.winfo_width() - self.winfo_width() - 16
            y = master.winfo_rooty() + master.winfo_height() - self.winfo_height() - 16
            self.geometry(f"+{x}+{y}")
            
            self.after(3000, self.fade_out)

        def fade_out(self):
            alpha = self.attributes("-alpha")
            if alpha > 0:
                alpha -= 0.1
                self.attributes("-alpha", alpha)
                self.after(50, self.fade_out)
            else:
                self.destroy()

    class WindowsGUI:
        NORD_THEME = {
            "light": {
                "base": "#ECEFF4", "surface": "#FFFFFF", "overlay": "#E5E9F0", "muted": "#D8DEE9",
                "text": "#2E3440", "text_subtle": "#4C566A"
            },
            "dark": {
                "base": "#2E3440", "surface": "#3B4252", "overlay": "#434C56", "muted": "#4C566A",
                "text": "#ECEFF4", "text_subtle": "#D8DEE9"
            },
            "common": {
                "accent": "#88C0D0", "dl": "#A3BE8C", "ul": "#81A1C1", 
                "danger": "#BF616A", "warning": "#EBCB8B", "secondary": "#5E81AC"
            }
        }
        
        FONTS = {
            "title": ("Segoe UI", 20, "bold"),
            "stat": ("Segoe UI", 32, "bold"),
            "body_bold": ("Segoe UI", 14, "bold"),
            "body": ("Segoe UI", 13),
            "mono": ("Consolas", 12)
        }

        def __init__(self) -> None:
            self.root = ctk.CTk()
            self.root.title("TrafficDown Ultimate 5.1")
            self.root.geometry("1000x750")
            self.root.minsize(900, 700)
            ctk.set_appearance_mode("System")
            
            self.last_dl = self.last_ul = 0.0
            self.last_t = time.time()
            self.dl_history = [0.0] * 50
            self.ul_history = [0.0] * 50
            self.slider_widgets: Dict[str, Tuple[ctk.CTkSlider, ctk.CTkLabel]] = {}
            self.txt_urls: Optional[ctk.CTkTextbox] = None
            self.icons = self.load_icons()
            self.is_graph_hovered = False
            self.crosshair_line = None
            self.validation_error_widgets = []
            
            self.setup_ui()
            self.setup_logging()
            self.update_loop()

        def get_color(self, name: str) -> str:
            mode = ctk.get_appearance_mode().lower()
            if name in self.NORD_THEME["common"]:
                return self.NORD_THEME["common"][name]
            return self.NORD_THEME[mode][name]

        def load_icons(self) -> Dict[str, ctk.CTkImage]:
            icons = {}
            for name in ["start", "stop"]:
                try:
                    path = os.path.join("icons", f"{name}.png")
                    if os.path.exists(path):
                        icons[name] = ctk.CTkImage(Image.open(path))
                except Exception as e:
                    log.error(f"Не вдалося завантажити іконку {name}: {e}")
            return icons

        def setup_ui(self) -> None:
            self.root.grid_columnconfigure(0, weight=1)
            self.root.grid_rowconfigure(0, weight=1)
            self.root.configure(fg_color=self.get_color("base"))

            tab_view = ctk.CTkTabview(self.root, border_width=0,
                                      fg_color=self.get_color("surface"),
                                      segmented_button_selected_color=self.get_color("accent"),
                                      segmented_button_unselected_color=self.get_color("surface"),
                                      segmented_button_selected_hover_color=self.get_color("accent"),
                                      text_color=self.get_color("text"))
            tab_view.grid(row=0, column=0, padx=16, pady=16, sticky="nsew")
            
            self.dashboard_tab = tab_view.add("Dashboard")
            self.settings_tab = tab_view.add("Settings")
            self.log_tab = tab_view.add("Logs")
            
            for tab in [self.dashboard_tab, self.settings_tab, self.log_tab]:
                tab.configure(fg_color=self.get_color("surface"))

            self._setup_dashboard(self.dashboard_tab)
            self._setup_settings(self.settings_tab)
            self._setup_logs_tab(self.log_tab)
        
        def _create_stat_frame(self, p, title, color) -> Tuple[ctk.CTkLabel, ctk.CTkLabel]:
            p.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(p, text=title, font=self.FONTS["title"], text_color=color).grid(row=0, pady=(8,0))
            lbl_speed = ctk.CTkLabel(p, text="0.0 MB/s", font=self.FONTS["stat"], text_color=color)
            lbl_speed.grid(row=1, pady=(0,0), padx=8)
            lbl_total = ctk.CTkLabel(p, text="Total: 0.00 GB", font=self.FONTS["body"], text_color=self.get_color("text_subtle"))
            lbl_total.grid(row=2, pady=(0,8))
            return lbl_speed, lbl_total

        def _setup_dashboard(self, tab: ctk.CTkFrame) -> None:
            tab.grid_columnconfigure(0, weight=1); tab.grid_rowconfigure(1, weight=1)
            
            top_panel = ctk.CTkFrame(tab, fg_color="transparent"); top_panel.grid(row=0, column=0, sticky="ew", pady=(0, 8))
            top_panel.grid_columnconfigure((0, 2), weight=1); top_panel.grid_columnconfigure(1, weight=2)
            
            dl_frame = ctk.CTkFrame(top_panel, corner_radius=8); dl_frame.grid(row=0, column=0, sticky="nsew", padx=(0,8), pady=8)
            self.lbl_dl_speed, self.lbl_dl_total = self._create_stat_frame(dl_frame, "DOWNLOAD", self.get_color("dl"))
            ul_frame = ctk.CTkFrame(top_panel, corner_radius=8); ul_frame.grid(row=0, column=2, sticky="nsew", padx=(8,0), pady=8)
            self.lbl_ul_speed, self.lbl_ul_total = self._create_stat_frame(ul_frame, "UPLOAD", self.get_color("ul"))

            center_frame = ctk.CTkFrame(top_panel, corner_radius=8); center_frame.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
            center_frame.grid_columnconfigure(0, weight=1); center_frame.grid_rowconfigure((0,1,2), weight=1)
            self.lbl_mode = ctk.CTkLabel(center_frame, text="MODE: IDLE", font=self.FONTS["body_bold"]); self.lbl_mode.grid(row=0, pady=8)
            self.lbl_cpu_ram = ctk.CTkLabel(center_frame, text="CPU: -% | RAM: -%", font=self.FONTS["body"]); self.lbl_cpu_ram.grid(row=1, pady=8)
            self.lbl_errors_count = ctk.CTkLabel(center_frame, text="ERRORS: 0", font=self.FONTS["body"]); self.lbl_errors_count.grid(row=2, pady=8)

            graph_panel = ctk.CTkFrame(tab, corner_radius=8); graph_panel.grid(row=1, column=0, sticky="nsew", pady=8)
            graph_panel.grid_columnconfigure(0, weight=1); graph_panel.grid_rowconfigure(0, weight=1)
            self.canvas = ctk.CTkCanvas(graph_panel, highlightthickness=0); self.canvas.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
            self.canvas.bind("<Configure>", self.draw_graph); self.canvas.bind("<Motion>", self.on_graph_hover)
            self.canvas.bind("<Enter>", lambda e: setattr(self, 'is_graph_hovered', True))
            self.canvas.bind("<Leave>", self.on_graph_leave)
            self.graph_tooltip = ctk.CTkLabel(self.canvas, text="", fg_color=self.get_color("overlay"), corner_radius=6, font=self.FONTS["mono"])

            control_panel = ctk.CTkFrame(tab, fg_color="transparent"); control_panel.grid(row=2, column=0, sticky="ew", pady=(8, 0))
            control_panel.grid_columnconfigure((0, 1), weight=1)
            self.btn_dl = ctk.CTkButton(control_panel, command=self.toggle_dl, height=48, font=self.FONTS["body_bold"], image=self.icons.get("start"), compound="left", corner_radius=8)
            self.btn_dl.grid(row=0, column=0, padx=(0, 8), pady=8, sticky="ew")
            self.btn_ul = ctk.CTkButton(control_panel, command=self.toggle_ul, height=48, font=self.FONTS["body_bold"], image=self.icons.get("start"), compound="left", corner_radius=8)
            self.btn_ul.grid(row=0, column=1, padx=(8, 0), pady=8, sticky="ew")

            ToolTip(self.btn_dl, lambda: "Інший тест вже запущено" if self.btn_dl.cget("state") == "disabled" else "")
            ToolTip(self.btn_ul, lambda: "Інший тест вже запущено" if self.btn_ul.cget("state") == "disabled" else "")

        def _setup_settings(self, tab: ctk.CTkFrame) -> None:
            tab.grid_columnconfigure(0, weight=1); tab.grid_rowconfigure(0, weight=1)
            scroll_frame = ctk.CTkScrollableFrame(tab, label_text="Application Settings", label_font=self.FONTS["body_bold"], fg_color="transparent")
            scroll_frame.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
            scroll_frame.grid_columnconfigure(0, weight=1)
            
            def create_group(p, title):
                g = ctk.CTkFrame(p, corner_radius=8); g.pack(fill="x", expand=True, padx=8, pady=8)
                g.grid_columnconfigure(1, weight=1)
                ctk.CTkLabel(g, text=title, font=self.FONTS["body_bold"]).grid(row=0, column=0, columnspan=2, pady=8, padx=16, sticky="w")
                return g

            target_g = create_group(scroll_frame, "Target Configuration")
            ctk.CTkLabel(target_g, text="Target IP:", font=self.FONTS["body"]).grid(row=1, column=0, padx=16, pady=8, sticky="w")
            self.ent_ip = ctk.CTkEntry(target_g, font=self.FONTS["body"]); self.ent_ip.grid(row=1, column=1, padx=16, pady=8, sticky="ew")
            ToolTip(self.ent_ip, lambda: "IP-адреса для UDP-флуду")
            ctk.CTkLabel(target_g, text="Target Port:", font=self.FONTS["body"]).grid(row=2, column=0, padx=16, pady=8, sticky="w")
            self.ent_port = ctk.CTkEntry(target_g, font=self.FONTS["body"]); self.ent_port.grid(row=2, column=1, padx=16, pady=8, sticky="ew")
            ToolTip(self.ent_port, lambda: "Порт для UDP-флуду (1-65535)")
            
            perf_g = create_group(scroll_frame, "Performance Tuning")
            self._add_slider(perf_g, "Download Threads", 1, 100, 'threads_dl', 1, "Кількість потоків для завантаження")
            self._add_slider(perf_g, "Flood Threads", 10, 1000, 'threads_ul', 3, "Кількість потоків для UDP-флуду")
            self._add_slider(perf_g, "Packet Size (bytes)", 64, 8192, 'packet_size', 5, "Розмір одного UDP-пакета")

            urls_g = create_group(scroll_frame, "Download URLs")
            ctk.CTkLabel(urls_g, text="One URL per line:", font=self.FONTS["body"]).grid(row=1, column=0, columnspan=2, padx=16, pady=(8,4), sticky="w")
            self.txt_urls = ctk.CTkTextbox(urls_g, height=200, font=self.FONTS["mono"], wrap="none", corner_radius=8)
            self.txt_urls.grid(row=2, column=0, columnspan=2, padx=16, pady=(0,8), sticky="nsew")
            ToolTip(self.txt_urls, lambda: "Список URL-адрес для режиму тестування швидкості")

            net_g = create_group(scroll_frame, "Network")
            ctk.CTkLabel(net_g, text="Network Interface:", font=self.FONTS["body"]).grid(row=1, column=0, padx=16, pady=8, sticky="w")
            interfaces = ["default"] + list(psutil.net_if_addrs().keys())
            self.if_menu = ctk.CTkOptionMenu(net_g, values=interfaces, font=self.FONTS["body"]); self.if_menu.grid(row=1, column=1, padx=16, pady=8, sticky="ew")
            ToolTip(self.if_menu, lambda: "Вибір мережевого інтерфейсу.\n'Default' - вибір системи.")
            
            btn_frame = ctk.CTkFrame(tab, fg_color="transparent"); btn_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=0)
            btn_frame.grid_columnconfigure(0, weight=1); btn_frame.grid_columnconfigure(1, weight=1)
            ctk.CTkButton(btn_frame, text="Save Settings", command=self.save_settings, height=40, font=self.FONTS["body_bold"], fg_color=self.get_color("secondary"), corner_radius=8).grid(row=0, column=0, padx=(0, 8), pady=8, sticky="ew")
            ctk.CTkButton(btn_frame, text="Reset to Default", command=self.reset_settings, height=40, font=self.FONTS["body_bold"], fg_color=self.get_color("muted"), text_color=self.get_color("text"), corner_radius=8).grid(row=0, column=1, padx=(8,0), pady=8, sticky="ew")
            self._update_settings_ui()

        def _setup_logs_tab(self, tab: ctk.CTkFrame) -> None:
            tab.grid_columnconfigure(0, weight=1); tab.grid_rowconfigure(0, weight=1)
            self.log_textbox = ctk.CTkTextbox(tab, font=self.FONTS["mono"], wrap="none", corner_radius=8, border_width=0)
            self.log_textbox.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
            self.log_textbox.configure(state="disabled")

        def setup_logging(self) -> None:
            gui_handler = GUILogHandler(self.log_textbox)
            gui_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
            gui_handler.setLevel(logging.INFO)
            log.addHandler(gui_handler)

        def _add_slider(self, p, text, f, t, key, r, tip_text) -> None:
            lbl_title = ctk.CTkLabel(p, text=f"{text}:", font=self.FONTS["body"]); lbl_title.grid(row=r, column=0, sticky="w", padx=16, pady=(8,0))
            lbl_val = ctk.CTkLabel(p, text=str(cfg.data.get(key,f)), font=self.FONTS["body"]); lbl_val.grid(row=r, column=1, sticky="e", padx=16, pady=(8,0))
            slider = ctk.CTkSlider(p, from_=f, to=t, command=lambda v, k=key: self.slider_widgets[k][1].configure(text=f"{int(v)}"))
            slider.grid(row=r + 1, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))
            self.slider_widgets[key] = (slider, lbl_val)
            ToolTip(slider, lambda: tip_text); ToolTip(lbl_title, lambda: tip_text)
        
        def _update_settings_ui(self) -> None:
            self.ent_ip.delete(0, 'end'); self.ent_ip.insert(0, cfg.data['target_ip'])
            self.ent_port.delete(0, 'end'); self.ent_port.insert(0, str(cfg.data['target_port']))
            self.if_menu.set(cfg.data.get('network_interface', 'default'))
            for key, (slider, label) in self.slider_widgets.items():
                val = cfg.data.get(key, slider._from_); slider.set(val); label.configure(text=str(int(val)))
            if self.txt_urls:
                self.txt_urls.delete("1.0", "end"); self.txt_urls.insert("1.0", "\n".join(cfg.data.get("download_urls", [])))

        def show_toast(self, message: str, status: str = "success"):
            Toast(self.root, message, status)

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
            
            self.btn_dl.configure(text="STOP" if dl_run else "START DOWNLOAD",
                                  fg_color=self.get_color("danger") if dl_run else self.get_color("dl"),
                                  image=self.icons.get("stop") if dl_run else self.icons.get("start"),
                                  state="disabled" if ul_run else "normal")
            self.btn_ul.configure(text="STOP" if ul_run else "START FLOOD",
                                  fg_color=self.get_color("danger") if ul_run else self.get_color("ul"),
                                  image=self.icons.get("stop") if ul_run else self.icons.get("start"),
                                  state="disabled" if dl_run else "normal")

        def save_settings(self) -> bool:
            for widget in self.validation_error_widgets:
                widget.configure(border_color=self.get_color("muted"))
            self.validation_error_widgets.clear()
            
            try:
                ip, port_str = self.ent_ip.get(), self.ent_port.get()
                if not ip:
                    self.validation_error_widgets.append(self.ent_ip)
                    raise ValueError("IP-адреса не може бути порожньою.")
                if not (port_str.isdigit() and 1<=int(port_str)<=65535):
                    self.validation_error_widgets.append(self.ent_port)
                    raise ValueError("Порт має бути числом від 1 до 65535.")
                urls_list = [line.strip() for line in self.txt_urls.get("1.0", "end").strip().split("\n") if line.strip()]
                if not urls_list:
                    self.validation_error_widgets.append(self.txt_urls)
                    raise ValueError("Список URL не може бути порожнім.")
                
                for widget in self.validation_error_widgets:
                    widget.configure(border_color=self.get_color("danger"))

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
                self.show_toast("Налаштування збережено", "success")
                return True
            except ValueError as e:
                for widget in self.validation_error_widgets:
                    widget.configure(border_width=1, border_color=self.get_color("danger"))
                self.show_toast(f"Помилка: {e}", "error")
                log.error(f"Не вдалося зберегти налаштування: {e}")
                return False

        def reset_settings(self) -> None:
            cfg.reset_to_default(); self._update_settings_ui()
            engine.urls = cfg.data.get("download_urls", [])
            self.show_toast("Налаштування скинуто до стандартних.", "warning")

        def draw_graph(self, event: Optional[Any] = None) -> None:
            if not self.canvas.winfo_exists(): return
            w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
            self.canvas.delete("all")
            if not (w > 1 and h > 1): return

            self.canvas.configure(bg=self.get_color("overlay"))
            
            if not engine.running:
                self.canvas.create_text(w/2, h/2, text="No session running",
                                        font=self.FONTS["body_bold"], fill=self.get_color("text_subtle"))
                return
            
            max_val = max(max(self.dl_history), max(self.ul_history), 1)
            # Auto-scale with 15% padding
            max_y = max_val * 1.15
            
            # Draw grid lines
            for i in range(1, 5):
                y = h * i / 5
                self.canvas.create_line(0, y, w, y, fill=self.get_color("muted"), dash=(2, 4))
                self.canvas.create_text(35, y, text=f"{max_y * (5 - i) / 5:.0f}", fill=self.get_color("text_subtle"), anchor="e", font=self.FONTS["mono"])
            self.canvas.create_text(35, 16, text="MB/s", fill=self.get_color("text_subtle"), anchor="e", font=self.FONTS["mono"])

            def plot(hist: list, color: str, fill_color: str):
                if len(hist) < 2: return
                pts = [(w*i/(len(hist)-1), h - (h*min(v, max_y)/max_y if max_y > 0 else 0)) for i,v in enumerate(hist)]
                
                # Filled area (gradient simulation)
                poly_pts = pts[:]
                poly_pts.insert(0, (pts[0][0], h))
                poly_pts.append((pts[-1][0], h))
                self.canvas.create_polygon(poly_pts, fill=fill_color, outline="", smooth=True)

                # Main line
                self.canvas.create_line(pts, fill=color, width=2, smooth=True)

            plot(self.ul_history, self.get_color("ul"), "#4C566A") # Hex with alpha approximation
            plot(self.dl_history, self.get_color("dl"), "#6F8F6B")

        def on_graph_hover(self, event):
            if not engine.running: return
            w, h = self.canvas.winfo_width(), self.canvas.winfo_height()

            # Delete old crosshair line
            if self.crosshair_line: self.canvas.delete(self.crosshair_line)
            
            # Draw new crosshair line
            self.crosshair_line = self.canvas.create_line(event.x, 0, event.x, h, fill=self.get_color("text_subtle"), dash=(4, 4))
            
            index = min(max(round((event.x / w) * (len(self.dl_history) - 1)), 0), len(self.dl_history)-1)
            dl_val = self.dl_history[index]; ul_val = self.ul_history[index]
            
            self.graph_tooltip.configure(text=f"DL: {dl_val:.1f}\nUL: {ul_val:.1f}")
            
            # Position tooltip
            x, y = event.x + 20, event.y
            if x + self.graph_tooltip.winfo_reqwidth() > w:
                x = event.x - self.graph_tooltip.winfo_reqwidth() - 20
            self.graph_tooltip.place(x=x, y=y)

        def on_graph_leave(self, event):
            setattr(self, 'is_graph_hovered', False)
            self.graph_tooltip.place_forget()
            if self.crosshair_line: self.canvas.delete(self.crosshair_line)
            self.crosshair_line = None

        def update_loop(self) -> None:
            if not self.root.winfo_exists(): return
            
            stats = engine.get_stats(); now = time.time(); delta = max(now - self.last_t, 1e-6)
            sdl = (stats['dl']-self.last_dl)/delta/1024**2; sul = (stats['ul']-self.last_ul)/delta/1024**2
            self.last_dl, self.last_ul, self.last_t = stats['dl'], stats['ul'], now

            if not self.is_graph_hovered:
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
            
            if self.root.winfo_viewable() and self.dashboard_tab.winfo_ismapped(): self.draw_graph()
            
            self.update_buttons()
            self.root.after(500, self.update_loop)

        def run(self) -> None:
            self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
            self.root.mainloop()
        def on_closing(self) -> None:
            log.info("Отримано запит на закриття вікна. Зупинка...")
            engine.stop()
            self.root.destroy()

# --- 5. ГОЛОВНА ТОЧКА ВХОДУ ---
def run_cli_mode(args):
    """Виконує тест в неінтерактивному режимі згідно з аргументами."""
    log.info(f"Запуск у неінтерактивному режимі: {args.mode}")

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
            
    if args.mode == "download": engine.start_download()
    elif args.mode == "udp": engine.start_flood(cfg.data['target_ip'], cfg.data['target_port'])
    
    print(f"Тест '{args.mode}' запущено. Натисніть Ctrl+C для зупинки або чекайте {args.duration}...")

    try:
        time.sleep(args.duration)
    except KeyboardInterrupt:
        log.info("Тест зупинено користувачем.")
    finally:
        engine.stop()
        log.info("Неінтерактивний режим завершено.")
        
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TrafficDown 5.1 - інструмент для мережевого навантаження.")
    parser.add_argument("--mode", type=str, choices=["download", "udp"], help="Режим роботи: 'download' або 'udp'.")
    parser.add_argument("--threads", type=int, help="Кількість потоків.")
    parser.add_argument("--duration", type=int, default=60, help="Тривалість тесту в секундах (за замовчуванням: 60).")
    parser.add_argument("--target", type=str, help="Ціль для UDP-флуду у форматі IP:PORT.")
    args = parser.parse_args()

    try:
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
