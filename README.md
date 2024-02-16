# Телеграм бот ...


![Доступные команды](commands.txt)


## Установка

Для установки проекта выполните следующие шаги:

1. Установите Python 3.8+.

2. Установите словари и прочее `sudo apt install aspell aspell-en aspell-ru aspell-uk enchant-2 ffmpeg python3-venv sox translate-shell`

3. Клонируйте репозиторий с помощью команды:

   ```
   git clone https://github.com/theurs/tb2.git

   python -m venv .tb2
   source ~/.tb2/bin/activate

   ```

4. Перейдите в директорию проекта:

   ```
   cd tb2
   ```

5. Установите зависимости, выполнив команду:

   ```
   pip install -r requirements.txt
   python -m textblob.download_corpora
   ```

6. Создайте файл cfg.py и добавьте в него строку
```
# список админов, кому можно использовать команды /restart и вкл-выкл автоответы в чатах
# надо зайти в любую тему и дать команду /id что
# бы узнать свой ID
admins = [id1,id2,]

# куда слать репорты. надо зайти в нужную тему и дать команду /id что
# бы узнать координаты этой темы (ID группы: [-xxxxxxxxxxxx] [yyy])
report_id =  [-xxxxxxxxxxxx, yyy]

# надо дать боту права на создание тем в группах, или просто сделать админом
log_gpoup = -xxxxxxxxxxxx


# telegram bot token
token   = "xxx"

# openai tokens and addresses
# список  серверов для chatGPT [['address', 'token', True/False(распознавание голоса), True/False(рисование)], [], ...]
openai_servers = [
    ['https://api.openai.com/v1', 'sk-xxx', True, False],
    ['https://api.openai.com/v1', 'sk-yyy', True, False],
]


# искать (__Secure-1PSID, __Secure-1PSIDTS, __Secure-1PSIDCC) в куках с сайта https://gemini.google.com/
# [(__Secure-1PSID, __Secure-1PSIDTS, __Secure-1PSIDCC), ...]
bard_tokens = [
    ('xxx',
     'yyy',
     'zzz'),
]


# ключи для клауда
claudeai_keys = [
    'sessionKey=sk-ant-sid01-xxx',
    'sessionKey=sk-ant-sid01-yyy',
    ]


# размер буфера для поиска в гугле, чем больше тем лучше ищет и отвечает
# и тем больше токенов жрет
# для модели с 4к памяти
# для модели с 16к памяти
max_request = 14000
max_google_answer = 2000


# насколько большие сообщения от юзера принимать
max_message_from_user = 190000


# 16k
max_hist_lines = 10
max_hist_bytes = 9000
max_hist_compressed=1500
max_hist_mem = 1500
CHATGPT_MAX_REQUEST = 7000


# https://openai.com/pricing
# 16K context   $0.003 / 1K tokens  $0.004 / 1K tokens
# примерно 7$ за 750.000 слов в запросе+ответе, при этом в запрос добавляется
# история переписки размером до max_hist_lines строк
model = 'gpt-3.5-turbo-16k'
# 8K context    $0.03 / 1K tokens   $0.06 / 1K tokens
# примерно 9$ за 75.000 слов в запросе+ответе, при этом в запрос добавляется
# история переписки размером до max_hist_lines строк
# model = 'gpt-4-8k'

# роль для chatGPT, инструкция что и как делать, например отвечать покороче
gpt_start_message1 = 'Ты искусственный интеллект отвечающий на запросы юзера, на русском языке.'


# кодовые слова для поиска в гугле
search_commands = ['погугли', 'загугли', 'гугл', 'google', 'поиск', 'найди']
bard_commands = ['бард', 'bard']

# сколько тысяч символов в сутки можно запрашивать одному юзеру,
# ограничитель для защиты от быстрого исчерпания токенов chatGPT
spam_limit = 800

# for bard
proxies = None

# perplexity
perplexity_proxies = None



# id телеграм группы куда скидываются все сгенерированные картинки
#pics_group = 0
#pics_group_url = ''
pics_group = -xxx
pics_group_url = 'https://t.me/xxx_pics_ch'

# https://ai.google.dev/
gemini_keys = ['xxx',
               'yyy']


# прокси для рисования бингом
# bing_proxy = ['socks5://172.28.1.4:1080', 'socks5://172.28.1.7:1080', 'socks5://172.28.1.5:1080',]
bing_proxy = []
```

7. Запустить ./tb.py



## Использование

Перед тем как приглашать бота на канал надо в настройке бота у @Botfather выбрать бота, затем зайти в `Bot Settings-Group Privacy-` и выключить. После того как бот зашел на канал надо включить опять. Это нужно для того что бы у бота был доступ к сообщениям на канале.

## Лицензия

Лицензия, под которой распространяется проект.
