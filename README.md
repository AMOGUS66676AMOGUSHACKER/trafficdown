# TrafficDown


Это скрипт, который позволяет съесть много трафика, понизить скорость любой сети! Необходим Python версии выше 3.13!

Как он работает
Как он ест трафик: скрипт получает очень много мусорной информации, которая много весит. Из-за этого можно съесть у точки доступа много трафика. Как он понижает скорость сети: скрипт делает очень много запросов на случайный IP (8.8.8.8:443), из-за чего сеть начинает лагать.

Как добавить свои сервера со своими файлами для этого шоу? docs.md в servers вам в помощь

# Баги?
Уверенно создавайте Issue, либо же заходите в наш телеграм канал и в комментариях опишите свою проблему. Вы нам очень поможете!

# Установка
Скрипт сам установит необходимые модули. Поддерживает:

Android (termux)
Linux дистрибутивы
Windows
WSL
Почему не поддерживает pydroid? Он ужасен.

# Запуск
Как использовать на Android: Скачайте Termux, введите команду cd ~ && rm -rf trafficdown && apt update && apt upgrade -y && apt install python3 -y && pip install colorama && pip install psutil && pip install requests && apt install git -y && git clone https://github.com/AMOGUS66676AMOGUSHACKER/trafficdown && cd trafficdown && python3 TrafficDown.py

Как пользоваться на Windows: Скачайте Python 3.13 и выше с Microsoft Store (там легче всего, либо через python.org) и запустите скрипт

Как пользоваться на Linux дистрибутивах: Впишите в терминале команду cd ~ && rm -rf trafficdown && apt update && apt upgrade -y && apt install python3 -y && pip install colorama && pip install psutil && pip install requests && apt install git -y && git clone https://github.com/AMOGUS66676AMOGUSHACKER/trafficdown && cd trafficdown && python3 TrafficDown.py

# Changelog
v2.0 beta
Оптимизирован скрипт.

Улушенный дизайн.

Полная переработка кода и безопасности.

V2.1 Добавлены нормальные настройки и логирование всего процесса
Оптимизация скрипта
Улучшен Дизайн
Изменена логика автозагрузки и зависимостей.


2.2 Исправлен Баг с netifaces


3.4 Изменен та улучшен дизайн.

Переработана структура кода.

Добавлена возможность на GUI смотреть логи прямо в програме а также менять размер пакета потоки и т д. 

Изменен конфиг.

Работает на термух(не точно я ебал это фиксить )

 посмотрите сами там еще по коду что изменилось я ебал ещё смотреть

# Фото (GUI)
<img width="994" height="713" alt="image" src="https://github.com/user-attachments/assets/741eb832-bf7b-4ed9-b4ad-af19487ca8ce" />

<img width="987" height="730" alt="image" src="https://github.com/user-attachments/assets/98eb180b-98c4-4cf4-9678-1bc5b364d24f" />

<img width="997" height="762" alt="image" src="https://github.com/user-attachments/assets/10d30226-944d-4cd7-9064-2893a6180707" />


# Тест
pkg update -y && pkg upgrade -y
pkg install python rust binutils build-essential git -y
pip install --upgrade pip
pip install aiohttp rich psutil requests netifaces
# Доска обявлений

Сдесь пока еще нихуя нету
