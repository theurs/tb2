#!/usr/bin/env python3


import os
import datetime
import threading
import time

import telebot

import cfg
import my_dic


# хранилище данных о логах юзеров, какой юзер в каком месте должен быть залогирован
# {user_id: (thread_id)} тут предполагается что все в одной группе разделенные по темам
USERS_LOGS = my_dic.PersistentDict('db/users_logs.pkl')


lock = threading.Lock()


if not os.path.exists('logs'):
    os.mkdir('logs')


def log2(text: str) -> None:
    """для дебага"""
    time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
    log_file_path = 'logs/debug.log'
    open(log_file_path, 'a', encoding="utf-8").write(f'{time_now}\n\n{text}\n\n{"="*89}\n')


def log_echo(message: telebot.types.Message, reply_from_bot: str = '', debug: bool = False) -> None:
    """записывает в журнал сообщение полученное обработчиком обычных сообщений либо ответ бота"""

    time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
    private_or_chat = 'private' if message.chat.type == 'private' else 'chat'
    chat_name = message.chat.username or message.chat.first_name or message.chat.title or ''
    user_name = message.from_user.first_name or message.from_user.username or ''
    chat_name = chat_name.replace('/', '⁄')
    user_name = user_name.replace('/', '⁄')
    
    logname = f'logs/[{chat_name}] [{private_or_chat}] [{message.chat.type}] [{message.chat.id}].log'.replace('[private] [private]', '[private]').replace('[chat] [supergroup]', '[chat]')

    topic_id = 0

    if message.reply_to_message and message.reply_to_message.is_topic_message:
        topic_id = message.reply_to_message.message_thread_id
    elif message.is_topic_message:
        topic_id = message.message_thread_id

    log_file_path = logname
    
    if debug:
        log_file_path = log_file_path + '.debug.log'

    if topic_id:
        log_file_path = log_file_path[:-4] + f' [{topic_id}].log'

    with lock:
        with open(log_file_path, 'a', encoding="utf-8") as log_file:
            if reply_from_bot:
                log_file.write(f"[{time_now}] [BOT]: {reply_from_bot}\n")
            else:
                log_file.write(f"[{time_now}] [{user_name}]: {message.text or message.caption or ''}\n")


def log_media(message: telebot.types.Message) -> None:
    """записывает в журнал сообщение полученное обработчиком медиа файлов"""

    time_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')
    private_or_chat = 'private' if message.chat.type == 'private' else 'chat'
    chat_name = message.chat.username or message.chat.first_name or message.chat.title or ''
    user_name = message.from_user.first_name or message.from_user.username or ''
    chat_name = chat_name.replace('/', '⁄')
    user_name = user_name.replace('/', '⁄')

    caption = message.caption or ''

    logname = f'logs/[{chat_name}] [{private_or_chat}] [{message.chat.type}] [{message.chat.id}].log'.replace('[private] [private]', '[private]').replace('[chat] [supergroup]', '[chat]')

    topic_id = 0

    if message.reply_to_message and message.reply_to_message.is_topic_message:
        topic_id = message.reply_to_message.message_thread_id
    elif message.is_topic_message:
        topic_id = message.message_thread_id

    log_file_path = logname

    if topic_id:
        log_file_path = log_file_path[:-4] + f' [{topic_id}].log'

    if message.audio:
        file_name = message.audio.file_name
        file_size = message.audio.file_size
        file_duration = message.audio.duration
        file_title = message.audio.title
        file_mime_type = message.audio.mime_type
        with lock:
            with open(log_file_path, 'a', encoding="utf-8") as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил аудио файл] [caption: {caption}] [title: {file_title}] \
[filename: {file_name}] [filesize: {file_size}] [duration: {file_duration}] [mime type: {file_mime_type}]\n")

    if message.voice:
        file_size = message.voice.file_size
        file_duration = message.voice.duration
        with lock:
            with open(log_file_path, 'a', encoding="utf-8") as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил голосовое сообщение] [filesize: \
{file_size}] [duration: {file_duration}]\n")

    if message.document:
        file_name = message.document.file_name
        file_size = message.document.file_size
        file_mime_type = message.document.mime_type
        with lock:
            with open(log_file_path, 'a', encoding="utf-8") as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил документ] [caption: {caption}] \
[filename: {file_name}] [filesize: {file_size}] [mime type: {file_mime_type}]\n")

    if message.photo or message.video:
        with lock:
            with open(log_file_path, 'a', encoding="utf-8") as log_file:
                log_file.write(f"[{time_now}] [{user_name}]: [Отправил фото] [caption]: {caption}\n")


def log_google(request: str, respond: str):
    """записывает в журнал сообщение полученное обработчиком google"""
    time_now = datetime.datetime.now().strftime('%d-%m-%Y %H.%M.%S')
    log_file_path = f'logs/askgoogle at {time_now}.log'
    with open(log_file_path, 'a', encoding="utf-8") as log_file:
        log_file.write(f'{respond}\n\n{"="*40}\n\n{request}')


def log_report(bot: telebot.TeleBot, message: telebot.types.Message, 
               chat_id_full: str, user_id: int, user_text: str, resp: str,
               parse_mode: str = '') -> None:
    """сохраняет в лог для отчета запросы и ответы юзеров
    ./logs/user_id.log
    """

    time_now = time.time()
    ftime_now = datetime.datetime.now().strftime('%d-%m-%Y %H:%M:%S')

    logname = f'logs/{message.from_user.id}.log'

    log_file_path = logname

    with lock:
        with open(log_file_path, 'a', encoding="utf-8") as log_file:
            log_file.write('=' * 40 + '\n')
            log_file.write(f"{time_now}\n")
            log_file.write(f"{ftime_now}\n")
            log_file.write(f'{chat_id_full}\n')
            log_file.write('-' * 40 + '\n')
            log_file.write(f"{user_text}\n")
            log_file.write('-' * 40 + '\n')
            log_file.write(f"{resp}\n")
            log_file.write('=' * 40 + '\n')

    user_id = message.from_user.id
    user_name = message.from_user.first_name or message.from_user.username or "[пусто]"
    user_id_with_name = f'[{user_id}] [{user_name}]'
    logs_group = cfg.log_gpoup
    if user_id in USERS_LOGS:
        user_thread = USERS_LOGS[user_id]
    else:
        user_thread = bot.create_forum_topic(logs_group, user_id_with_name).message_thread_id
        USERS_LOGS[user_id] = user_thread

    try:
        bot.send_message(logs_group, message_thread_id=user_thread, text = f'USER: {user_text}')
        time.sleep(1)
        bot.send_message(logs_group, message_thread_id=user_thread, text = f'BOT: {resp}', parse_mode=parse_mode)
    except Exception as error:
        print(f'my_log:log_report: {error}')
        log2(f'my_log:log_report: {error}')

        # возможно удалили тему и надо создать ее заново
        user_thread = bot.create_forum_topic(logs_group, user_id_with_name).message_thread_id
        USERS_LOGS[user_id] = user_thread

        bot.send_message(logs_group, message_thread_id=user_thread, text = f'USER: {user_text}')
        time.sleep(1)
        bot.send_message(logs_group, message_thread_id=user_thread, text = f'BOT: {resp}', parse_mode=parse_mode)


if __name__ == '__main__':
    pass
    log_google('1', '2')
