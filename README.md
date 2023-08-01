# Телеграм бот ...


![Доступные команды](commands.txt)


## Установка

Для установки проекта выполните следующие шаги:

1. Установите Python 3.8+.

2. Установите словари и прочее `sudo apt install ffmpeg python3-venv sox trans`

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
# бы узнать свой ID (ID пользователя: xxxxxxxxxxxx)
admins = [xxxxxxxxxxxx,]

# куда слать репорты. надо зайти в нужную тему и дать команду /id что 
# бы узнать координаты этой темы (ID группы: [xxxxxxxxxxxx] [yyyy])
report_id =  [xxxxxxxxxxxxxx, yyyy]

# надо дать боту права на создание тем в группах, или просто сделать админом
log_gpoup = xxx


# telegram bot token
token   = "xxx"

# openai tokens and addresses
# список  серверов для chatGPT [['address', 'token', True/False(распознавание голоса), True/False(рисование)], [], ...]
openai_servers = [
    ['https://api.openai.com/v1', 'xxx', True, True],
    ['https://...', 'xxx', True, True],
]


# искать __Secure-1PSID в куках с сайта https://bard.google.com/
bard_tokens = ['xxxx.',
               'yyyy']


# id телеграм группы куда скидываются все сгенерированные картинки
# id телеграм группы куда скидываются все сгенерированные картинки
#pics_group = 0
#pics_group_url = ''
pics_group = xxxxxx
pics_group_url = 'https://t.me/xxx'


# размер буфера для поиска в гугле, чем больше тем лучше ищет и отвечает
# и тем больше токенов жрет
# для модели с 4к памяти
# для модели с 16к памяти
max_request = 15000
max_google_answer = 2000


# насколько большие сообщения от юзера принимать
max_message_from_user = 4000


# 16k
max_hist_lines = 10
max_hist_bytes = 8000
max_hist_compressed=1500
max_hist_mem = 2500


# https://openai.com/pricing
# 16K context	$0.003 / 1K tokens	$0.004 / 1K tokens
# примерно 7$ за 750.000 слов в запросе+ответе, при этом в запрос добавляется
# история переписки размером до max_hist_lines строк
model = 'gpt-3.5-turbo-16k'
# 8K context	$0.03 / 1K tokens	$0.06 / 1K tokens
# примерно 9$ за 75.000 слов в запросе+ответе, при этом в запрос добавляется
# история переписки размером до max_hist_lines строк
# model = 'gpt-4-8k'

# роль для chatGPT, инструкция что и как делать, например отвечать покороче
gpt_start_message1 = 'Ты искусственный интеллект отвечающий на запросы юзера, на русском языке, коротко.'


# размер картинок для генерации с помощью openai (chatGPT)
# Must be one of '1024x1024', '512x512', or '256x256'.
# 1024×1024	$0.020 / image
# 512×512	$0.018 / image
# 256×256	$0.016 / image
image_gen_size = '1024x1024'


# кодовые слова для поиска в гугле
search_commands = ['загугли', 'гугл', 'google', 'поиск', 'найди']
bard_commands = ['бард', 'bard']

# сколько тысяч символов в сутки можно запрашивать одному юзеру, 
# ограничитель для защиты от быстрого исчерпания токенов chatGPT
spam_limit = 200


```

7. Запустить ./tb.py



## Использование

Перед тем как приглашать бота на канал надо в настройке бота у @Botfather выбрать бота, затем зайти в `Bot Settings-Group Privacy-` и выключить. После того как бот зашел на канал надо включить опять. Это нужно для того что бы у бота был доступ к сообщениям на канале.

## Лицензия

Лицензия, под которой распространяется проект.
