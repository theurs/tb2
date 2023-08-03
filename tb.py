#!/usr/bin/env python3

import io
import glob
import os
import re
import tempfile
import threading
import time

import openai
import telebot
from fuzzywuzzy import fuzz
import pandas as pd

import cfg
import gpt_basic
import my_bard
import my_genimg
import my_dic
import my_google
import my_log
import my_sum
import my_stt
import my_trans
import my_tts
import utils


# устанавливаем рабочую папку = папке в которой скрипт лежит
os.chdir(os.path.abspath(os.path.dirname(__file__)))


# bot = telebot.TeleBot(cfg.token, skip_pending=True)
bot = telebot.TeleBot(cfg.token)
BOT_NAME = bot.get_me().username
BOT_ID = bot.get_me().id


# телеграм группа для отправки сгенерированных картинок
# pics_group = cfg.pics_group
# pics_group_url = cfg.pics_group_url

# до 40 одновременных потоков для чата с гпт и бингом
semaphore_talks = threading.Semaphore(40)

# папка для постоянных словарей, памяти бота
if not os.path.exists('db'):
    os.mkdir('db')

# история диалогов для GPT chat
DIALOGS_DB = my_dic.PersistentDict('db/dialogs.pkl')

# для запоминания ответов на команду /sum
SUM_CACHE = my_dic.PersistentDict('db/sum_cache.pkl')

# в каких чатах активирован режим работы
# {chat_id:False|True}
SUPER_CHAT = my_dic.PersistentDict('db/super_chat.pkl')

# в каких чатах включен Бард вместо чатГПТ
BARD_MODE = my_dic.PersistentDict('db/bard_mode.pkl')

# хранилище замков что бы юзеры не могли делать новые запросы пока не получен ответ на старый
# {chat_id(str):threading.Lock(),...}
GPT_CHAT_LOCKS = {}

# список стоп-слов
try:
    STOP_WORDS = [x.strip() for x in open('stop_words.txt', 'r', encoding="utf-8").read().split(',')]
except FileNotFoundError:
    STOP_WORDS = []
STOP_WORDS = [x.lower() for x in STOP_WORDS]
STOP_WORDS = sorted(STOP_WORDS)
with open('stop_words.txt', 'w', encoding='utf-8') as f:
    f.write(','.join(STOP_WORDS))
stop_words_lock = threading.Lock()

# защита от спама, временный бан юзера
# {user_id: Spamer}
SPAMERS = {}

# защита от одновременного доступа к файлу экспорта
panda_export_lock = threading.Lock()


supported_langs_tts = [
        'af', 'am', 'ar', 'as', 'az', 'be', 'bg', 'bn', 'bs', 'ca', 'cs', 'cy', 'da',
        'de', 'el', 'en', 'eo', 'es', 'et', 'eu', 'fa', 'fi', 'fil', 'fr', 'ga', 'gl',
        'gu', 'he', 'hi', 'hr', 'ht', 'hu', 'hy', 'id', 'is', 'it', 'ja', 'jv', 'ka',
        'kk', 'km', 'kn', 'ko', 'ku', 'ky', 'la', 'lb', 'lo', 'lt', 'lv', 'mg', 'mi',
        'mk', 'ml', 'mn', 'mr', 'ms', 'mt', 'my', 'nb', 'ne', 'nl', 'nn', 'no', 'ny',
        'or', 'pa', 'pl', 'ps', 'pt', 'ro', 'ru', 'rw', 'sd', 'si', 'sk', 'sl', 'sm',
        'sn', 'so', 'sq', 'sr', 'st', 'su', 'sv', 'sw', 'ta', 'te', 'tg', 'th', 'tk',
        'tl', 'tr', 'tt', 'ug', 'uk', 'ur', 'uz', 'vi', 'xh', 'yi', 'yo', 'zh', 'zu']


class ShowAction(threading.Thread):
    """Поток который можно остановить. Беспрерывно отправляет в чат уведомление об активности.
    Телеграм автоматически гасит уведомление через 5 секунд, по-этому его надо повторять.

    Использовать в коде надо как то так
    with ShowAction(message, 'typing'):
        делаем что-нибудь и пока делаем уведомление не гаснет
    """
    def __init__(self, message, action):
        """_summary_

        Args:
            chat_id (_type_): id чата в котором будет отображаться уведомление
            action (_type_):  "typing", "upload_photo", "record_video", "upload_video", "record_audio", 
                              "upload_audio", "upload_document", "find_location", "record_video_note", "upload_video_note"
        """
        super().__init__()
        self.actions = [  "typing", "upload_photo", "record_video", "upload_video", "record_audio",
                         "upload_audio", "upload_document", "find_location", "record_video_note", "upload_video_note"]
        assert action in self.actions, f'Допустимые actions = {self.actions}'
        self.chat_id = message.chat.id
        self.thread_id = message.message_thread_id
        self.action = action
        self.is_running = True
        self.timerseconds = 1

    def run(self):
        while self.is_running:
            try:
                bot.send_chat_action(self.chat_id, self.action, message_thread_id = self.thread_id)
            except Exception as error:
                my_log.log2(f'tb:show_action: {error}')
            n = 50
            while n > 0:
                time.sleep(0.1)
                n = n - self.timerseconds

    def stop(self):
        self.timerseconds = 50
        self.is_running = False
        try:
            bot.send_chat_action(self.chat_id, 'cancel', message_thread_id = self.thread_id)
        except Exception as error:
            my_log.log2(f'tb:show_action: {error}')

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


class Spamer:
    """ограничитель не дающий одному юзеру делать больше запросов к chatGPT чем ХХкб в сутки"""
    def __init__(self, user_id):
        self.user_id = user_id
        self.volume = 0
        self.timestamp = time.time()

    def add_text(self, text):
        # Проверка объема текста
        text_size = len(text.encode('utf-8'))
        if self.volume + text_size > cfg.spam_limit * 1024:
            raise AssertionError("Превышен лимит объема текстов в минуту")
        # Добавление текста
        self.volume += text_size
        current_time = time.time()
        if current_time - self.timestamp > 60*60*24:
            self.volume = text_size
            self.timestamp = current_time


def dialog_add_user_request(chat_id: str, text: str, engine: str = 'gpt') -> str:
    """добавляет в историю переписки с юзером его новый запрос и ответ от чатбота
    делает запрос и возвращает ответ

    Args:
        chat_id (str): номер чата или юзера, нужен для хранения истории переписки
        text (str): новый запрос от юзера
        engine (str, optional): 'gpt' или 'bing'. Defaults to 'gpt'.

    Returns:
        str: возвращает ответ который бот может показать, возможно '' или None
    """

    # по умолчанию формальный стиль
    current_prompt =   [{"role": "system", "content": cfg.gpt_start_message1}]

    # создаем новую историю диалогов с юзером из старой если есть
    # в истории диалогов не храним системный промпт
    if chat_id in DIALOGS_DB:
        new_messages = DIALOGS_DB[chat_id]
    else:
        new_messages = []

    # теперь ее надо почистить что бы влезла в запрос к GPT
    # просто удаляем все кроме max_hist_lines последних
    if len(new_messages) > cfg.max_hist_lines:
        new_messages = new_messages[cfg.max_hist_lines:]
    # удаляем первую запись в истории до тех пор пока общее количество токенов не станет меньше cfg.max_hist_bytes
    # удаляем по 2 сразу так как первая - промпт для бота
    while (utils.count_tokens(new_messages) > cfg.max_hist_bytes):
        new_messages = new_messages[2:]

    # добавляем в историю новый запрос и отправляем
    new_messages = new_messages + [{"role":    "user",
                                    "content": text}]

    if engine == 'gpt':
        # пытаемся получить ответ
        try:
            resp = gpt_basic.ai(prompt = text, messages = current_prompt + new_messages, chat_id=chat_id)
            if resp:
                new_messages = new_messages + [{"role":    "assistant",
                                                    "content": resp}]
            else:
                # не сохраняем диалог, нет ответа
                # если в последнем сообщении нет текста (глюк) то убираем его
                if new_messages[-1]['content'].strip() == '':
                    new_messages = new_messages[:-1]
                DIALOGS_DB[chat_id] = new_messages or []
                return 'ChatGPT не ответил.'
        # бот не ответил или обиделся
        except AttributeError:
            # не сохраняем диалог, нет ответа
            return 'ChatGPT не ответил.'
        # произошла ошибка переполнения ответа
        except openai.error.InvalidRequestError as error2:
            if """This model's maximum context length is""" in str(error2):
                # чистим историю, повторяем запрос
                p = '\n'.join(f'{i["role"]} - {i["content"]}\n' for i in new_messages) or 'Пусто'
                # сжимаем весь предыдущий разговор до cfg.max_hist_compressed символов
                r = gpt_basic.ai_compress(p, cfg.max_hist_compressed, 'dialog')
                new_messages = [{'role':'system','content':r}] + new_messages[-1:]
                # и на всякий случай еще
                while (utils.count_tokens(new_messages) > cfg.max_hist_compressed):
                    new_messages = new_messages[2:]

                try:
                    resp = gpt_basic.ai(prompt = text, messages = current_prompt + new_messages, chat_id=chat_id)
                except Exception as error3:
                    print(f'tb:dialog_add_user_request: {error3}')
                    my_log.log2(f'tb:dialog_add_user_request: {error3}')
                    return 'ChatGPT не ответил.'

                # добавляем в историю новый запрос и отправляем в GPT, если он не пустой, иначе удаляем запрос юзера из истории
                if resp:
                    new_messages = new_messages + [{"role":    "assistant",
                                                    "content": resp}]
                else:
                    return 'ChatGPT не ответил.'
            else:
                print(f'tb:dialog_add_user_request: {error2}')
                my_log.log2(f'tb:dialog_add_user_request: {error2}')
                return 'ChatGPT не ответил.'
    else:
        # для бинга
        return 'ChatGPT не ответил.'

    # сохраняем диалог, на данном этапе в истории разговора должны быть 2 последних записи несжатыми
    new_messages = new_messages[:-2]
    # если запрос юзера был длинным то в истории надо сохранить его коротко
    if len(text) > cfg.max_hist_mem:
        new_text = gpt_basic.ai_compress(text, cfg.max_hist_mem, 'user')
        # заменяем запрос пользователя на сокращенную версию
        new_messages += [{"role":    "user",
                             "content": new_text}]
    else:
        new_messages += [{"role":    "user",
                            "content": text}]
    # если ответ бота был длинным то в истории надо сохранить его коротко
    if len(resp) > cfg.max_hist_mem:
        new_resp = gpt_basic.ai_compress(resp, cfg.max_hist_mem, 'assistant')
        new_messages += [{"role":    "assistant",
                             "content": new_resp}]
    else:
        new_messages += [{"role":    "assistant",
                             "content": resp}]
    DIALOGS_DB[chat_id] = new_messages or []

    return resp


def get_topic_id(message: telebot.types.Message) -> str:
    """
    Get the topic ID from a Telegram message.

    Parameters:
        message (telebot.types.Message): The Telegram message object.

    Returns:
        str: '[chat.id] [topic.id]'
    """

    chat_id = message.chat.id
    # topic_id = 'not topic'
    topic_id = 0

    if message.reply_to_message and message.reply_to_message.is_topic_message:
        topic_id = message.reply_to_message.message_thread_id
    elif message.is_topic_message:
        topic_id = message.message_thread_id

    # bot.reply_to(message, f'DEBUG: [{chat_id}] [{topic_id}]')

    return f'[{chat_id}] [{topic_id}]'


def is_for_me(cmd: str):
    """Checks who the command is addressed to, this bot or another one.
    
    /cmd@botname args
    
    Returns (True/False, 'the same command but without the bot name').
    If there is no bot name at all, assumes that the command is addressed to this bot.
    """
    command_parts = cmd.split()
    first_arg = command_parts[0]

    if '@' in first_arg:
        message_cmd = first_arg.split('@', maxsplit=1)[0]
        message_bot = first_arg.split('@', maxsplit=1)[1] if len(first_arg.split('@', maxsplit=1)) > 1 else ''
        message_args = cmd.split(maxsplit=1)[1] if len(command_parts) > 1 else ''
        return (message_bot == BOT_NAME, f'{message_cmd} {message_args}'.strip())
    else:
        return (True, cmd)


def is_admin_member(message: telebot.types.Message):
    """
    Checks if the user is an admin member of the chat or config admin.

    Parameters:
    - message: A telebot.types.Message object representing the message received.

    Returns:
    - True if the user is an admin member of the chat or config admin.
    - False otherwise.
    """
    # Checks if the user is an admin member of the chat or config admin
    if not message:
        return False
    user_id = message.from_user.id
    return True if user_id in cfg.admins else False


def activated_location(message: telebot.types.Message) -> bool:
    """проверяет надо ли работать в этом чате, активировано ли администратором"""
    chat_id_full = get_topic_id(message)
    if chat_id_full in SUPER_CHAT and SUPER_CHAT[chat_id_full]:
        return True
    else:
        return False


def get_keyboard(kbd: str, message: telebot.types.Message, flag: str = '') -> telebot.types.InlineKeyboardMarkup:
    """создает и возвращает клавиатуру по текстовому описанию
    'chat' - клавиатура для чата
    'mem' - клавиатура для команды mem, с кнопками Забудь и Скрой
    'hide' - клавиатура с одной кнопкой Скрой
    ...
    """
    # chat_id_full = get_topic_id(message)

    if kbd == 'chat':
        markup  = telebot.types.InlineKeyboardMarkup(row_width=2)
        button1 = telebot.types.InlineKeyboardButton("Озвучить", callback_data='tts')
        button2 = telebot.types.InlineKeyboardButton("Перевод на русский", callback_data='translate')
        button3 = telebot.types.InlineKeyboardButton("Забудь всё", callback_data='forget_all')
        markup.add(button1, button3, button2)
        return markup
    elif kbd == 'chat_bard':
        markup  = telebot.types.InlineKeyboardMarkup(row_width=2)
        button1 = telebot.types.InlineKeyboardButton("Озвучить", callback_data='tts')
        button2 = telebot.types.InlineKeyboardButton("Перевод на русский", callback_data='translate')
        button3 = telebot.types.InlineKeyboardButton("Забудь всё", callback_data='forget_all_bard')
        markup.add(button1, button3, button2)
        return markup
    elif kbd == 'translate':
        markup  = telebot.types.InlineKeyboardMarkup()
        button2 = telebot.types.InlineKeyboardButton("Озвучить", callback_data='tts')
        button3 = telebot.types.InlineKeyboardButton("Перевод на русский", callback_data='translate')
        markup.add(button2, button3)
        return markup
    else:
        raise f"Неизвестная клавиатура '{kbd}'"


@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call: telebot.types.CallbackQuery):
    """Обработчик клавиатуры"""
    thread = threading.Thread(target=callback_inline_thread, args=(call,))
    thread.start()
def callback_inline_thread(call: telebot.types.CallbackQuery):
    """Обработчик клавиатуры"""

    with semaphore_talks:
        message = call.message
        chat_id_full = get_topic_id(message)
        user_id = message.from_user.id

        if chat_id_full in GPT_CHAT_LOCKS:
            lock = GPT_CHAT_LOCKS[chat_id_full]
        else:
            lock = threading.Lock()
            GPT_CHAT_LOCKS[chat_id_full] = lock
        with lock:

            if call.data == 'continue_gpt':
                # обработка нажатия кнопки "Продолжай GPT"
                message.dont_check_topic = True
                echo_all(message, 'Продолжай')
            elif call.data == 'forget_all':
                # обработка нажатия кнопки "Забудь всё"
                DIALOGS_DB[chat_id_full] = []
                bot.reply_to(message, 'chatGPT стёр память')
                my_log.log_report(bot, message.reply_to_message, chat_id_full, user_id, 'Забудь всё', 'chatGPT стёр память')
            elif call.data == 'forget_all_bard':
                # обработка нажатия кнопки "Забудь всё"
                my_bard.reset_bard_chat(chat_id_full)
                bot.reply_to(message, 'Google bard стёр память')
                my_log.log_report(bot, message.reply_to_message, chat_id_full, user_id, 'Забудь всё', 'Google bard стёр память')
            elif call.data == 'tts':
                lang = my_trans.detect_lang(message.text) or 'ru'
                message.text = f'/tts {lang} {message.text}'
                tts(message)
            elif call.data == 'translate':
                # реакция на клавиатуру для кнопки перевести текст
                text = message.text
                translated = my_trans.translate(text, 'ru')
                reply_to_long_message(message, translated, disable_web_page_preview=True)
                my_log.log_report(bot, message.reply_to_message, chat_id_full, user_id, 'переведи на русский', translated)


@bot.message_handler(content_types = ['voice', 'audio'])
def handle_voice(message: telebot.types.Message): 
    """Автоматическое распознавание текст из голосовых сообщений"""
    thread = threading.Thread(target=handle_voice_thread, args=(message,))
    thread.start()
def handle_voice_thread(message: telebot.types.Message):
    """Автоматическое распознавание текст из голосовых сообщений и аудио файлов"""

    # работаем только там где администратор включил
    if not activated_location(message):
        return

    chat_id_full = get_topic_id(message)
    if chat_id_full in GPT_CHAT_LOCKS:
        lock = GPT_CHAT_LOCKS[chat_id_full]
    else:
        lock = threading.Lock()
        GPT_CHAT_LOCKS[chat_id_full] = lock
    with lock:

        my_log.log_media(message)

        with semaphore_talks:
            # Создание временного файла
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                file_path = temp_file.name
            # Скачиваем аудиофайл во временный файл
            try:
                file_info = bot.get_file(message.voice.file_id)
            except AttributeError:
                file_info = bot.get_file(message.audio.file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            with open(file_path, 'wb') as new_file:
                new_file.write(downloaded_file)

            # Распознаем текст из аудио
            with ShowAction(message, 'typing'):
                text = my_stt.stt(file_path)

                os.remove(file_path)

                text = text.strip()
                # Отправляем распознанный текст
                if text:
                    reply_to_long_message(message, text)
                    my_log.log_echo(message, f'[ASR] {text}')
                else:
                    # bot.reply_to(message, 'Очень интересно, но ничего не понятно.', reply_markup=get_keyboard('hide', message))
                    my_log.log_echo(message, '[ASR] no results')

                # и при любом раскладе отправляем текст в обработчик текстовых сообщений,
                # возможно бот отреагирует на него если там есть кодовые слова
                if text:
                    message.text = f'[Голосовое сообщение]: {text}'
                    message.dont_check_topic = True
                    echo_all(message)


@bot.message_handler(commands=['mem'])
def send_debug_history(message: telebot.types.Message):
    """
    Отправляет текущую историю сообщений пользователю.
    """

    # работаем только там где администратор включил
    if not activated_location(message):
        return

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)
    
    chat_id_full = get_topic_id(message)

    # создаем новую историю диалогов с юзером из старой если есть
    messages = []
    if chat_id_full in DIALOGS_DB:
        messages = DIALOGS_DB[chat_id_full]
    prompt = '\n'.join(f'{i["role"]} - {i["content"]}\n' for i in messages) or 'Пусто'
    my_log.log_echo(message, prompt)
    reply_to_long_message(message, prompt, parse_mode = '', disable_web_page_preview = True)


@bot.message_handler(commands=['bard'])
def bard(message: telebot.types.Message):
    thread = threading.Thread(target=bard_thread, args=(message,))
    thread.start()
def bard_thread(message: telebot.types.Message):
    """делает запрос к гугл бард вместо chatGPT"""

    # работаем только там где администратор включил
    if not activated_location(message):
        return

    chat_id_full = get_topic_id(message)

    user_id = message.from_user.id
    try:
        user_text = message.text.split(maxsplit=1)[1]
    except IndexError:
        msg = """/bard <запрос к Google Bard>"""
        return

    if len(user_text) > my_bard.MAX_REQUEST:
        bot.reply_to(message, f'Слишком длинное сообщение для барда: {len(user_text)} из {my_bard.MAX_REQUEST}')
        my_log.log_echo(message, f'Слишком длинное сообщение для барда: {len(user_text)} из {my_bard.MAX_REQUEST}')
        return
    with ShowAction(message, 'typing'):
        try:
            answer = my_bard.chat(user_text, chat_id_full)
            my_log.log_echo(message, answer, debug = True)
            answer = utils.bot_markdown_to_html(answer)
            my_log.log_echo(message, answer)
            if answer:

                # сохранить в отчет вопрос и ответ для юзера, и там же сохранение в группу
                my_log.log_report(bot, message, chat_id_full, user_id, user_text, answer, parse_mode='HTML')

                try:
                    reply_to_long_message(message, answer, parse_mode='HTML', disable_web_page_preview = True, 
                                            reply_markup=get_keyboard('chat_bard', message))
                except Exception as bard_error:
                    print(f'tb:do_task: {bard_error}')
                    my_log.log2(f'tb:do_task: {bard_error}')
                    reply_to_long_message(message, answer, parse_mode='', disable_web_page_preview = True, 
                                            reply_markup=get_keyboard('chat_bard', message))
        except Exception as error3:
            print(f'tb:do_task: {error3}')
            my_log.log2(f'tb:do_task: {error3}')


@bot.message_handler(commands=['bardmode'])
def bardmode(message: telebot.types.Message):
    """выключить работу в этой теме/чате"""
    if is_admin_member(message):
        chat_id_full = get_topic_id(message)
        if chat_id_full in BARD_MODE:
            if BARD_MODE[chat_id_full]:
                BARD_MODE[chat_id_full] = False
                bot.reply_to(message, 'Теперь бот отвечает как chatGPT в этой теме/чате')
            else:
                BARD_MODE[chat_id_full] = True
                bot.reply_to(message, 'Теперь бот отвечает как Google Bard в этой теме/чате')
        else:
            BARD_MODE[chat_id_full] = True
            bot.reply_to(message, 'Теперь бот отвечает как Google Bard в этой теме/чате')
    else:
        bot.reply_to(message, 'Эта команда только для администраторов')


@bot.message_handler(commands=['activate']) 
def activate(message: telebot.types.Message):
    """включить работу в этой теме/чате"""
    if is_admin_member(message):
        SUPER_CHAT[get_topic_id(message)] = True
        bot.reply_to(message, 'Работа в этой теме/чате включена')
    else:
        bot.reply_to(message, 'Эта команда только для администраторов')


@bot.message_handler(commands=['deactivate']) 
def deactivate(message: telebot.types.Message):
    """выключить работу в этой теме/чате"""
    if is_admin_member(message):
        SUPER_CHAT[get_topic_id(message)] = False
        bot.reply_to(message, 'Работа в этой теме/чате выключена')
    else:
        bot.reply_to(message, 'Эта команда только для администраторов')


@bot.message_handler(commands=['add']) 
def stop_word_add(message: telebot.types.Message):
    """добавить стоп слово"""
    global STOP_WORDS
    if is_admin_member(message):
        with stop_words_lock:
            word = message.text.split(maxsplit=1)[1].strip()
            STOP_WORDS.append(word)
            STOP_WORDS = list(set(STOP_WORDS))
            STOP_WORDS = [x.lower() for x in STOP_WORDS]
            STOP_WORDS = sorted(STOP_WORDS)
            with open('stop_words.txt', 'w', encoding='utf-8') as f:
                f.write(','.join(STOP_WORDS))
            bot.reply_to(message, f'Добавлено стоп слово {word}')
    else:
        bot.reply_to(message, 'Эта команда только для администраторов')


@bot.message_handler(commands=['del']) 
def stop_word_del(message: telebot.types.Message):
    """удаляет стоп слово"""
    if is_admin_member(message):
        global STOP_WORDS
        word = message.text.split(maxsplit=1)[1].strip()
        with stop_words_lock:
            STOP_WORDS = [x for x in STOP_WORDS if x != word]
            STOP_WORDS = list(set(STOP_WORDS))
            STOP_WORDS = [x.lower() for x in STOP_WORDS]
            STOP_WORDS = sorted(STOP_WORDS)
            with open('stop_words.txt', 'w', encoding='utf-8') as f:
                f.write(','.join(STOP_WORDS))
        bot.reply_to(message, f'Удалено стоп слово {word}')
    else:
        bot.reply_to(message, 'Эта команда только для администраторов')


@bot.message_handler(commands=['restart']) 
def restart(message: telebot.types.Message):
    """остановка бота. после остановки его должен будет перезапустить скрипт systemd"""
    if is_admin_member(message):
        bot.stop_polling()
    else:
        bot.reply_to(message, 'Эта команда только для администраторов')


@bot.message_handler(commands=['id']) 
def id_cmd_handler(message: telebot.types.Message):
    """показывает id юзера и группы в которой сообщение отправлено"""
    user_id = message.from_user.id
    chat_id_full = get_topic_id(message)
    bot.reply_to(message, f'ID пользователя: {user_id}\n\nID группы: {chat_id_full}')


@bot.message_handler(commands=['export']) 
def export_data(message: telebot.types.Message):
    """Экспорт данных в виде файлов"""
    thread = threading.Thread(target=export_data_thread, args=(message,))
    thread.start()
def export_data_thread(message: telebot.types.Message):
    """Экспорт данных в виде файлов"""

    if not is_admin_member(message):
        bot.reply_to(message, 'Эта команда только для администраторов')
        return

    with ShowAction(message, 'upload_document'):
        # получить список всех файлов в папке логов
        files = []
        for x in glob.glob('logs/*.log'):
            try:
                user_id = int(x.split('/', maxsplit=1)[1].split('.',maxsplit=1)[0])
                files.append(x)
            except ValueError:
                pass
            except Exception as error:
                print(f'tb:export_data_thread: {error}')
                my_log.log2(f'tb:export_data_thread: {error}')

        # список строк для экспорта в таблицу
        data = []

        for x in files:
            with open(x, 'r', encoding='utf-8') as f:
                text = f.read()
                pattern = re.compile(r'={40}(.*?)={40}', re.DOTALL)
                matches = pattern.findall(text)
                sep2 = '-' * 40
                for match in matches:
                    text2 = match.strip()
                    lines2 = text2.splitlines()
                    _user = x.split('.', maxsplit=1)[0].split('/', maxsplit=1)[1]
                    _date_in_seconds = pd.to_datetime(float(lines2[0]), unit='s')                    
                    _date_and_time = lines2[1]
                    _chat_id_full = lines2[2]
                    lines2[2] = lines2[2].replace('[', '').replace(']', '')
                    _chat_id, _thread_id = lines2[2].split(' ')
                    _user_request = ''
                    _bot_response = ''
                    stage = 0
                    for l in lines2[4:]:
                        if l == sep2:
                            stage += 1
                            continue
                        if stage == 0:
                            _user_request += l + '\n'
                        else:
                            _bot_response += l + '\n'
                    _user_request = _user_request.strip()
                    _bot_response = _bot_response.strip()
                    _record = (_chat_id_full, _user, _date_and_time, _user_request, _bot_response, _date_in_seconds, _chat_id, _thread_id)
                    data.append(_record)

        # Создаем DataFrame из списка строк.
        df = pd.DataFrame(data)
        # Экспортируем DataFrame в файл Excel.
        with panda_export_lock:
            try:
                os.remove("export_file_7682341.xlsx")
            except FileNotFoundError:
                pass
            headers = ['chat_id_full', 'user_id', 'date_time_str', 'user_request', 'bot_response', 'date', 'chat_id', 'thread_id']
            df.to_excel("export_file_7682341.xlsx", header=headers)
            bot.send_document(message.chat.id, document = open('export_file_7682341.xlsx', 'rb'))
            try:
                os.remove("export_file_7682341.xlsx")
            except Exception as error:
                print(f'tb:export_data_thread: {error}')
                my_log.log2(f'tb:export_data_thread: {error}')


@bot.message_handler(commands=['tts']) 
def tts(message: telebot.types.Message):
    thread = threading.Thread(target=tts_thread, args=(message,))
    thread.start()
def tts_thread(message: telebot.types.Message):
    """ /tts [ru|en|uk|...] [+-XX%] <текст>
        /tts <URL>
    """

    # работаем только там где администратор включил
    if not activated_location(message):
        return

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_id_full = get_topic_id(message)
    if chat_id_full in GPT_CHAT_LOCKS:
        lock = GPT_CHAT_LOCKS[chat_id_full]
    else:
        lock = threading.Lock()
        GPT_CHAT_LOCKS[chat_id_full] = lock
    with lock:

        my_log.log_echo(message)

        # обрабатываем урл, просто достаем текст и показываем с клавиатурой для озвучки
        args = message.text.split()
        if len(args) == 2 and my_sum.is_valid_url(args[1]):
            url = args[1]
            if '/youtu.be/' in url or 'youtube.com/' in url:
                text = my_sum.get_text_from_youtube(url)
            else:
                text = my_google.download_text([url, ], 100000, no_links = True)
            if text:
                reply_to_long_message(message, text, parse_mode='',
                                    disable_web_page_preview=True)
            return

        # разбираем параметры
        # регулярное выражение для разбора строки
        pattern = r'/tts\s+((?P<lang>' + '|'.join(supported_langs_tts) + r')\s+)?\s*(?P<rate>([+-]\d{1,2}%\s+))?\s*(?P<text>.+)'
        # поиск совпадений с регулярным выражением
        match = re.match(pattern, message.text, re.DOTALL)
        # извлечение параметров из найденных совпадений
        if match:
            lang = match.group("lang") or "ru"  # если lang не указан, то по умолчанию 'ru'
            rate = match.group("rate") or "+0%"  # если rate не указан, то по умолчанию '+0%'
            text = match.group("text") or ''
        else:
            text = lang = rate = ''
        lang = lang.strip()
        rate = rate.strip()

        if not text or lang not in supported_langs_tts:
            help = f"""Использование: /tts [ru|en|uk|...] [+-XX%] <текст>|<URL>

    +-XX% - ускорение с обязательным указанием направления + или -

    /tts привет
    /tts en hello, let me speak from all my heart
    /tts +50% привет со скоростью 1.5х
    /tts uk -50% тянем время, говорим по-русски с украинским акцентом :)

    Поддерживаемые языки: {', '.join(supported_langs_tts)}

    """
            bot.reply_to(message, help, parse_mode='Markdown')
            my_log.log_echo(message, help)
            return

        with semaphore_talks:
            with ShowAction(message, 'record_audio'):
                gender = 'female'
                audio = my_tts.tts(text, lang, rate, gender=gender)
                if audio:
                    try:
                        bot.send_voice(message.chat.id, audio, reply_to_message_id = message.message_id)
                    except Exception as error:
                        print(f'tb:tts: {error}')
                        my_log.log2(f'tb:tts: {error}')
                        try:
                            bot.send_voice(message.chat.id, audio)
                        except Exception as error2:
                            print(f'tb:tts: {error2}')
                            my_log.log2(f'tb:tts: {error2}')
                            my_log.log_echo(message, '[Не удалось отправить голосовое сообщение]')
                            return
                    my_log.log_echo(message, '[Отправил голосовое сообщение]')
                else:
                    msg = 'Не удалось озвучить. Возможно вы перепутали язык, например немецкий голос не читает по-русски.'
                    bot.reply_to(message, msg)
                    my_log.log_echo(message, msg)


@bot.message_handler(commands=['google',])
def google(message: telebot.types.Message):
    thread = threading.Thread(target=google_thread, args=(message,))
    thread.start()
def google_thread(message: telebot.types.Message):
    """ищет в гугле перед ответом"""

    # работаем только там где администратор включил
    if not activated_location(message):
        return

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return
    
    chat_id_full = get_topic_id(message)
    if chat_id_full in GPT_CHAT_LOCKS:
        lock = GPT_CHAT_LOCKS[chat_id_full]
    else:
        lock = threading.Lock()
        GPT_CHAT_LOCKS[chat_id_full] = lock
    with lock:

        my_log.log_echo(message)

        chat_id_full = get_topic_id(message)

        try:
            q = message.text.split(maxsplit=1)[1]
        except Exception as error2:
            print(error2)
            help = """/google текст запроса

    Будет делать запрос в гугл, и потом пытаться найти нужный ответ в результатах

    /google курс биткоина, прогноз на ближайшее время

    /google текст песни малиновая лада

    /google кто звонил +69997778888, из какой страны
    """
            return

        if test_for_spam('Ж' * cfg.max_request, message.from_user.id):
            bot.reply_to(message, 'Слишком много сообщений, попробуйте позже')
            return

        with ShowAction(message, 'typing'):
            with semaphore_talks:
                r = my_google.search(q)
            try:
                r = utils.bot_markdown_to_html(r)
                bot.reply_to(message, r, parse_mode = 'HTML', disable_web_page_preview = True, reply_markup=get_keyboard('translate', message))
            except Exception as error2:
                print(f'tb:google: {error2}')
                my_log.log2(f'tb:google: {error2}')
                bot.reply_to(message, r, parse_mode = '', disable_web_page_preview = True, reply_markup=get_keyboard('translate', message))
            my_log.log_echo(message, r)

            # сохранить в отчет вопрос и ответ для юзера, и там же сохранение в группу
            my_log.log_report(bot, message, chat_id_full, message.from_user.id, '/google ' + q, r)

            if chat_id_full not in DIALOGS_DB:
                DIALOGS_DB[chat_id_full] = []
            DIALOGS_DB[chat_id_full] += [{"role":    'system',
                                    "content": f'user попросил сделать запрос в Google: {q}'},
                                        {"role":    'system',
                                    "content": f'assistant поискал в Google и ответил: {r}'}
                                    ]


@bot.message_handler(commands=['image','img'])
# def image(message: telebot.types.Message):
#     thread = threading.Thread(target=image_thread, args=(message,))
#     thread.start()
# def image_thread(message: telebot.types.Message):
#     """генерирует картинку по описанию"""

#     # работаем только там где администратор включил
#     if not activated_location(message):
#         return

#     # не обрабатывать команды к другому боту /cmd@botname args
#     if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
#     else: return

#     chat_id_full = get_topic_id(message)
#     if chat_id_full in GPT_CHAT_LOCKS:
#         lock = GPT_CHAT_LOCKS[chat_id_full]
#     else:
#         lock = threading.Lock()
#         GPT_CHAT_LOCKS[chat_id_full] = lock
#     with lock:

#         my_log.log_echo(message)

#         with semaphore_talks:
#             help = """/image <текстовое описание картинки, что надо нарисовать>

#     Пример:
#     `/image мишки на севере, ловят рыбу, рисунок карандашом`
#     """
#             prompt = message.text.split(maxsplit = 1)
#             if len(prompt) > 1:
#                 prompt = prompt[1]
#                 # считаем что рисование тратит 16к символов, хотя на самом деле больше
#                 if test_for_spam('Ж' * 16000, message.from_user.id):
#                     bot.reply_to(message, 'Слишком много сообщений, попробуйте позже')
#                     return
#                 with ShowAction(message, 'upload_photo'):
#                     images = my_genimg.gen_images(prompt)
#                     if len(images) > 0:
#                         medias = [telebot.types.InputMediaPhoto(i) for i in images]
#                         bot.send_media_group(message.chat.id, medias, reply_to_message_id=message.message_id)
#                         if pics_group:
#                             try:
#                                 bot.send_message(cfg.pics_group, prompt, disable_web_page_preview = True)
#                                 bot.send_media_group(pics_group, medias)
#                             except Exception as error2:
#                                 print(f'tb:image: {error2}')
#                                 my_log.log2(f'tb:image: {error2}')

#                         my_log.log_echo(message, '[image gen] ')

#                         # сохранить в отчет вопрос и ответ для юзера, и там же сохранение в группу
#                         my_log.log_report(bot, message, chat_id_full, message.from_user.id, f'/image {prompt}', '\n'.join(images))

#                         n = [{'role':'system', 'content':f'user попросил нарисовать\n{prompt}'}, {'role':'system', 'content':'assistant нарисовал с помощью DALL-E'}]
#                         if chat_id_full in DIALOGS_DB:
#                             DIALOGS_DB[chat_id_full] += n
#                         else:
#                             DIALOGS_DB[chat_id_full] = n
                        
#                     else:
#                         bot.reply_to(message, 'Не смог ничего нарисовать. Может настроения нет, а может надо другое описание дать.')
#                         my_log.log_echo(message, '[image gen error] ')
#                         my_log.log_report(bot, message, chat_id_full, message.from_user.id, f'/image {prompt}', 'Не смог ничего нарисовать. Может настроения нет, а может надо другое описание дать.')
#                         n = [{'role':'system', 'content':f'user попросил нарисовать\n{prompt}'}, {'role':'system', 'content':'assistant не захотел или не смог нарисовать это с помощью DALL-E'}]
#                         if chat_id_full in DIALOGS_DB:
#                             DIALOGS_DB[chat_id_full] += n
#                         else:
#                             DIALOGS_DB[chat_id_full] = n
#             else:
#                 bot.reply_to(message, help, parse_mode = 'Markdown')
#                 my_log.log_echo(message, help)


@bot.message_handler(commands=['sum'])
def summ_text(message: telebot.types.Message):
    thread = threading.Thread(target=summ_text_thread, args=(message,))
    thread.start()
def summ_text_thread(message: telebot.types.Message):

    # работаем только там где администратор включил
    if not activated_location(message):
        return

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    chat_id_full = get_topic_id(message)
    if chat_id_full in GPT_CHAT_LOCKS:
        lock = GPT_CHAT_LOCKS[chat_id_full]
    else:
        lock = threading.Lock()
        GPT_CHAT_LOCKS[chat_id_full] = lock

    if test_for_spam('Ж' * cfg.max_request, message.from_user.id):
        bot.reply_to(message, 'Слишком много сообщений, попробуйте позже')
        return

    with lock:

        my_log.log_echo(message)

        text = message.text
        
        if len(text.split(' ', 1)) == 2:
            url = text.split(' ', 1)[1].strip()
            if my_sum.is_valid_url(url):
                # убираем из ютуб урла временную метку
                if '/youtu.be/' in url or 'youtube.com/' in url:
                    url = url.split("&t=")[0]

                with semaphore_talks:

                    #смотрим нет ли в кеше ответа на этот урл
                    r = ''
                    if url in SUM_CACHE:
                        r = SUM_CACHE[url]
                    if r:
                        reply_to_long_message(message, r, disable_web_page_preview = True, reply_markup=get_keyboard('translate', message))
                        my_log.log_echo(message, r)

                        # сохранить в отчет вопрос и ответ для юзера, и там же сохранение в группу
                        my_log.log_report(bot, message, chat_id_full, message.from_user.id, '/sum ' + url, r)

                        if chat_id_full not in DIALOGS_DB:
                            DIALOGS_DB[chat_id_full] = []
                        DIALOGS_DB[chat_id_full] += [{"role":    'system',
                                    "content": f'user попросил кратко пересказать содержание текста по ссылке/из файла'},
                                    {"role":    'system',
                                    "content": f'assistant прочитал и ответил: {r}'}
                                    ]
                        return

                    with ShowAction(message, 'typing'):
                        res = ''
                        try:
                            res = my_sum.summ_url(url)
                        except Exception as error2:
                            print(f'tb:sum: {error2}')
                            my_log.log2(f'tb:sum: {error2}')
                            m = 'Не нашел тут текста. Возможно что в видео на ютубе нет субтитров или страница не показывает текст роботам'
                            bot.reply_to(message, m, parse_mode='Markdown')
                            my_log.log_report(bot, message, chat_id_full, message.from_user.id, '/sum ' + url, m)
                            my_log.log_echo(message, m)
                            return
                        if res:
                            reply_to_long_message(message, res, parse_mode='',
                                                disable_web_page_preview = True,
                                                reply_markup=get_keyboard('translate', message))
                            my_log.log_echo(message, res)

                            # сохранить в отчет вопрос и ответ для юзера, и там же сохранение в группу
                            my_log.log_report(bot, message, chat_id_full, message.from_user.id, '/sum ' + url, res)

                            SUM_CACHE[url] = res
                            if chat_id_full not in DIALOGS_DB:
                                DIALOGS_DB[chat_id_full] = []
                            DIALOGS_DB[chat_id_full] += [{"role":    'system',
                                    "content": f'user попросил кратко пересказать содержание текста по ссылке/из файла'},
                                    {"role":    'system',
                                    "content": f'assistant прочитал и ответил: {res}'}
                                    ]
                            return
                        else:
                            error = 'Не смог прочитать текст с этой страницы.'
                            bot.reply_to(message, error)
                            my_log.log_echo(message, error)
                            my_log.log_report(bot, message, chat_id_full, message.from_user.id, '/sum ' + url, error)
                            return
        help = """Пример: /sum https://youtu.be/3i123i6Bf-U"""
        bot.reply_to(message, help, parse_mode = 'Markdown')
        my_log.log_echo(message, help)


@bot.message_handler(commands=['sum2'])
def summ2_text(message: telebot.types.Message):
    # убирает запрос из кеша если он там есть и делает запрос снова

    # работаем только там где администратор включил
    if not activated_location(message):
        return

    text = message.text

    if len(text.split(' ', 1)) == 2:
        url = text.split(' ', 1)[1].strip()
        if my_sum.is_valid_url(url):
            # убираем из ютуб урла временную метку
            if '/youtu.be/' in url or 'youtube.com/' in url:
                url = url.split("&t=")[0]

            #смотрим нет ли в кеше ответа на этот урл
            if url in SUM_CACHE:
                SUM_CACHE.pop(url)
    summ_text(message)


@bot.message_handler(commands=['start'])
def send_welcome_start(message: telebot.types.Message):
    # Отправляем приветственное сообщение

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    help = """Я - ваш персональный чат-бот, готовый помочь вам в любое время суток. Моя задача - помочь вам получить необходимую информацию и решить возникающие проблемы."""
    bot.reply_to(message, help, parse_mode='Markdown')
    my_log.log_echo(message, help)


@bot.message_handler(commands=['help'])
def send_welcome_help(message: telebot.types.Message):
    # Отправляем приветственное сообщение

    # не обрабатывать команды к другому боту /cmd@botname args
    if is_for_me(message.text)[0]: message.text = is_for_me(message.text)[1]
    else: return

    my_log.log_echo(message)

    help = """Чат бот отвечает на любой запрос в чате кроме тех которые являются ответом на сообщение другого человека

Если бот перестал отвечать то возможно надо почистить ему память командой ***забудь***

Кодовое слово ***гугл*** позволит получить более актуальную информацию, бот будет гуглить перед ответом ***гугл курс биткоин***
Кодовое слово ***бард*** позволит получить более актуальную информацию, отвечать будет Google Bard вместо chatGPT ***бард бренд вкучно и точка*** (этот бренд появился уже после того как chatGPT закончил обучение и он о нем не знает)

Если отправить ссылку то попытается прочитать текст из неё и выдать краткое содержание.

Команды и запросы можно делать голосовыми сообщениями.

""" + '\n'.join(open('commands.txt', encoding='utf8').readlines())

    bot.reply_to(message, help, parse_mode='Markdown')
    my_log.log_echo(message, help)


def reply_to_long_message(message: telebot.types.Message, resp: str, parse_mode: str = None,
                          disable_web_page_preview: bool = None, reply_markup: telebot.types.InlineKeyboardMarkup = None):
    """отправляем сообщение, если оно слишком длинное то разбивает на части либо отправляем как текстовый файл"""
    if len(resp) < 20000:
        chunks = utils.split_text(resp, 3500)
        for chunk in chunks:
            try:
                bot.reply_to(message, chunk, parse_mode=parse_mode,
                             disable_web_page_preview=disable_web_page_preview,
                             reply_markup=reply_markup)
            except Exception as error:
                print(f'tb:reply_to_long_message: {error}')
                my_log.log2(f'tb:reply_to_long_message: {error}')
                bot.reply_to(message, chunk, parse_mode='',
                             disable_web_page_preview=disable_web_page_preview,
                             reply_markup=reply_markup)
            time.sleep(2)
    else:
        buf = io.BytesIO()
        buf.write(resp.encode())
        buf.seek(0)
        bot.send_document(message.chat.id, document=buf, caption='resp.txt', visible_file_name = 'resp.txt')


def send_message_to_admin(message: telebot.types.Message, bad_word_found: str):
    # Отправка ссылки на сообщение администратору
    chat_id = cfg.report_id[0]
    thread_id = cfg.report_id[1]

    # my_log.log2(str(message))

    if message.is_topic_message:
        message_link = f't.me/c/{str(message.chat.id)[3:]}/{message.reply_to_message.message_id}/{message.message_id}'
    else:
        message_link = f't.me/{message.chat.username}/{message.message_id}'

    bot.send_message(chat_id=chat_id, message_thread_id = thread_id, 
                     text=f"Посмотрите сообщение здесь, возможно маты ({bad_word_found}): {message_link}",
                     disable_web_page_preview = True)


def test_for_spam(text: str, user_id: int) -> bool:
    """функция проверки на спам, возвращает True если юзер слишком много токенов тратит"""
    try:
        if user_id not in SPAMERS:
            SPAMERS[user_id] = Spamer(user_id)
        SPAMERS[user_id].add_text(text)
    except AssertionError as spam_detected_error:
        print(f'tb:do_task: {spam_detected_error}')
        my_log.log2(f'tb:do_task: {spam_detected_error}')
        return True
    return False


def get_history_of_chat(chat_id_full: str) -> str:
    """возвращает историю диалога, надо что бы посчитать размер текста для проверки на спам"""
    messages = []
    if chat_id_full in DIALOGS_DB:
        messages = DIALOGS_DB[chat_id_full]

    # теперь ее надо почистить что бы влезла в запрос к GPT
    # просто удаляем все кроме max_hist_lines последних
    if len(messages) > cfg.max_hist_lines:
        messages = messages[cfg.max_hist_lines:]
    # удаляем первую запись в истории до тех пор пока общее количество токенов не станет меньше cfg.max_hist_bytes
    # удаляем по 2 сразу так как первая - промпт для бота
    while (utils.count_tokens(messages) > cfg.max_hist_bytes):
        messages = messages[2:]

    prompt = '\n'.join(f'{i["role"]} - {i["content"]}\n' for i in messages) or 'Пусто'
    return prompt


@bot.message_handler(func=lambda message: True)
def echo_all(message: telebot.types.Message, custom_prompt: str = '') -> None:
    """Обработчик текстовых сообщений"""
    thread = threading.Thread(target=do_task, args=(message, custom_prompt))
    thread.start()
def do_task(message, custom_prompt: str = ''):
    """функция обработчик сообщений работающая в отдельном потоке"""

    # работаем только там где администратор включил
    if not activated_location(message):
        return

    chat_id_full = get_topic_id(message)

    # не обрабатывать неизвестные команды
    if message.text.startswith('/'): return

    with semaphore_talks:

        my_log.log_echo(message)

        user_id = message.from_user.id
        user_text = message.text

        # является ли это сообщение топика, темы (особые чаты внутри чатов)
        is_topic = message.is_topic_message or (message.reply_to_message and message.reply_to_message.is_topic_message)
        # является ли это ответом на сообщение бота
        is_reply = message.reply_to_message and message.reply_to_message.from_user.id == BOT_ID

        # не отвечать если это ответ юзера другому юзеру
        try:
            _ = message.dont_check_topic
        except AttributeError:
            message.dont_check_topic = False
        if not message.dont_check_topic:
            if is_topic: # в топиках всё не так как в обычных чатах
                # если ответ не мне либо запрос ко всем(в топике он выглядит как ответ с content_type == 'forum_topic_created')
                if not (is_reply or message.reply_to_message.content_type == 'forum_topic_created'):
                    return
            else:
                # если это ответ в обычном чате но ответ не мне то выход
                if message.reply_to_message and not is_reply:
                    return

        # удаляем пробелы в конце каждой строки
        message.text = "\n".join([line.rstrip() for line in message.text.split("\n")])
        msg = message.text.lower()
        # убираем имя бота из запроса
        if msg.startswith(BOT_NAME):
            message.text = message.text.split(maxsplit = 1)[1]
            msg = message.text.lower()

        # если есть совпадение в списке стоп слов
        # удаляем все символы кроме букв
        letters = re.compile('[^а-яА-ЯёЁa-zA-Z0-9\'\`\$\_\-\{\}\[\]\<\>\@\*\|\s]')
        msg2 = letters.sub(' ', msg)
        # и разбиваем текст на слова
        words_in_msg2 = [x.strip() for x in msg2.split()]
        for x in words_in_msg2:
            if any(fuzz.ratio(x, keyword) > 80 for keyword in STOP_WORDS):
                # сообщить администратору о нарушителе
                send_message_to_admin(message, x)
        # for x in words_in_msg2:
            # if x in STOP_WORDS:
                # # сообщить администратору о нарушителе
                # send_message_to_admin(message, x)

        # если сообщение начинается на 'забудь' то стираем историю общения GPT
        if msg.startswith('забудь'):
            if chat_id_full in BARD_MODE and BARD_MODE[chat_id_full]:
                my_bard.reset_bard_chat(chat_id_full)
                my_log.log_echo(message, 'История Google Bard принудительно отчищена')
                my_log.log_report(bot, message, chat_id_full, user_id, 'забудь', 'История Google Bard принудительно отчищена')
            else:
                DIALOGS_DB[chat_id_full] = []
                my_log.log_echo(message, 'История chatGPT принудительно отчищена')
                my_log.log_report(bot, message, chat_id_full, user_id, 'забудь', 'История chatGPT принудительно отчищена')
            bot.reply_to(message, 'Ок', parse_mode='Markdown')
            return

        # если в сообщении только ссылка тогда суммаризируем текст из неё
        if my_sum.is_valid_url(message.text):
            message.text = '/sum ' + message.text
            summ_text(message)
            return

        # проверяем просят ли нарисовать что-нибудь
        # if msg.startswith(('нарисуй ', 'нарисуй,')):
        #     prompt = msg[8:]
        #     if prompt:
        #         message.text = f'/image {prompt}'
        #         image_thread(message)
        #         n = [{'role':'system', 'content':f'user попросил нарисовать\n{prompt}'}, {'role':'system', 'content':'assistant нарисовал с помощью DALL-E'}]
        #         if chat_id_full in DIALOGS_DB:
        #             DIALOGS_DB[chat_id_full] += n
        #         else:
        #             DIALOGS_DB[chat_id_full] = n
        #         return

        # можно перенаправить запрос к барду
        elif msg.startswith(tuple(cfg.bard_commands)):
            prompt = message.text.split(maxsplit=1)[1].strip()
            message.text = f'/bard {prompt}'
            bard(message)
            return

        # можно перенаправить запрос к гуглу
        elif msg.startswith(tuple(cfg.search_commands)):
            prompt = message.text.split(maxsplit=1)[1].strip()
            message.text = f'/google {prompt}'
            google(message)
            return

        # слишком длинное сообщение для бота
        if len(msg) > cfg.max_message_from_user:
            bot.reply_to(message, f'Слишком длинное сообщение чат-для бота: {len(msg)} из {cfg.max_message_from_user}')
            my_log.log_echo(message, f'Слишком длинное сообщение чат-для бота: {len(msg)} из {cfg.max_message_from_user}')
            return

        # если активирован бард
        if chat_id_full in BARD_MODE and BARD_MODE[chat_id_full]:
            if len(msg) > my_bard.MAX_REQUEST:
                bot.reply_to(message, f'Слишком длинное сообщение для барда: {len(msg)} из {my_bard.MAX_REQUEST}')
                my_log.log_echo(message, f'Слишком длинное сообщение для барда: {len(msg)} из {my_bard.MAX_REQUEST}')
                return

            with ShowAction(message, 'typing'):
                try:
                    answer = my_bard.chat(message.text, chat_id_full)
                    my_log.log_echo(message, answer, debug = True)
                    answer = utils.bot_markdown_to_html(answer)
                    my_log.log_echo(message, answer)
                    if answer:
                        try:
                            reply_to_long_message(message, answer, parse_mode='HTML', disable_web_page_preview = True, 
                                                    reply_markup=get_keyboard('chat', message))
                        except Exception as error:
                            print(f'tb:do_task: {error}')
                            my_log.log2(f'tb:do_task: {error}')
                            reply_to_long_message(message, answer, parse_mode='', disable_web_page_preview = True, 
                                                    reply_markup=get_keyboard('chat', message))
                        my_log.log_report(bot, message, chat_id_full, user_id, user_text, answer, parse_mode='HTML')
                    else:
                        my_log.log_echo(message, resp, debug = True)
                        my_log.log_report(bot, message, chat_id_full, user_id, user_text, 'Google Bard не ответил', parse_mode='HTML')
                        bot.reply_to(message, 'Google Bard не ответил')
                except Exception as error3:
                    print(f'tb:do_task: {error3}')
                    my_log.log2(f'tb:do_task: {error3}')
        else:
            # chatGPT, добавляем новый запрос пользователя в историю диалога пользователя
            with ShowAction(message, 'typing'):

                # проверка на спам сообщениями
                if test_for_spam(message.text + get_history_of_chat(chat_id_full), user_id):
                    bot.reply_to(message, f'Слишком много сообщений, попробуйте попозже')
                    return

                if chat_id_full in GPT_CHAT_LOCKS:
                    lock = GPT_CHAT_LOCKS[chat_id_full]
                else:
                    lock = threading.Lock()
                    GPT_CHAT_LOCKS[chat_id_full] = lock
                with lock:
                    resp = dialog_add_user_request(chat_id_full, message.text, 'gpt')
                    if resp:
                        
                        # добавляем ответ счетчик юзера что бы детектить спам
                        test_for_spam(resp, user_id)
                        
                        my_log.log_echo(message, resp, debug = True)
                        resp = utils.bot_markdown_to_html(resp)
                        my_log.log_echo(message, resp)

                        # сохранить в отчет вопрос и ответ для юзера, и там же сохранение в группу
                        my_log.log_report(bot, message, chat_id_full, user_id, user_text, resp, parse_mode='HTML')

                        try:
                            reply_to_long_message(message, resp, parse_mode='HTML', disable_web_page_preview = True, 
                                                reply_markup=get_keyboard('chat', message))
                        except Exception as error2:    
                            print(error2)
                            my_log.log2(resp)
                            reply_to_long_message(message, resp, parse_mode='', disable_web_page_preview = True, 
                                                reply_markup=get_keyboard('chat', message))
                    else:
                        my_log.log_echo(message, resp, debug = True)
                        my_log.log_report(bot, message, chat_id_full, user_id, user_text, 'ChatGPT не ответил', parse_mode='HTML')
                        bot.reply_to(message, 'ChatGPT не ответил')


def set_default_commands():
    """
    Reads a file containing a list of commands and their descriptions,
    and sets the default commands for the bot.
    """
    commands = []
    with open('commands.txt', encoding='utf-8') as file:
        for line in file:
            try:
                command, description = line[1:].strip().split(' - ', 1)
                if command and description:
                    commands.append(telebot.types.BotCommand(command, description))
            except Exception as error:
                print(error)
    bot.set_my_commands(commands)


def main():
    """
    Runs the main function, which sets default commands and starts polling the bot.
    """
    set_default_commands()
    bot.polling()


if __name__ == '__main__':
    main()
