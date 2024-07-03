#!/usr/bin/env python3

import random
import threading
import traceback

import openai
from sqlitedict import SqliteDict

import cfg
import my_log


# ROLE = """Ты искусственный интеллект отвечающий на запросы юзера."""
ROLE = ''
MODEL = 'google/gemma-2-9b-it:free'

# сколько запросов хранить
MAX_MEM_LINES = 20
MAX_CHARS = 12000

# блокировка чатов что бы не испортить историю 
# {id:lock}
LOCKS = {}

# не принимать запросы больше чем, это ограничение для телеграм бота, в этом модуле оно не используется
MAX_REQUEST = 12000

# хранилище диалогов {id:list(mem)}
CHATS = SqliteDict('db/gemma2-9b_dialogs.db', autocommit=True)


def ai(prompt: str = '', temp: float = 0.1, max_tok: int = 4000, timeou: int = 120, messages = None,
       chat_id = None, model_to_use: str = '') -> str:
    """Сырой текстовый запрос к GPT чату, возвращает сырой ответ
    """
    try:
        if not messages:
            assert prompt != '', 'prompt не может быть пустым'
            messages = [{"role": "system", "content": ROLE},
                        {"role": "user", "content": prompt}]
        messages += [{"role": "user", "content": prompt}]
        current_model = MODEL

        response = ''

        # копируем и перемешиваем список серверов
        shuffled_servers = cfg.openai_servers[:]
        random.shuffle(shuffled_servers)

        for server in shuffled_servers:
            openai.api_base = server[0]
            openai.api_key = server[1]

            try:
                # тут можно добавить степень творчества(бреда) от 0 до 1 дефолт - temperature=0.5
                completion = openai.ChatCompletion.create(
                    model = current_model,
                    messages=messages,
                    max_tokens=max_tok,
                    temperature=temp,
                    timeout=timeou
                )
                response = completion.choices[0].message.content
                if response.strip() in ('Rate limit exceeded', 'You exceeded your current quota, please check your plan and billing details.'):
                    response = ''
                if response:
                    break
            except Exception as unknown_error1:
                error_tr = traceback.format_exc()
                my_log.log2(f'gpt_basic_2.ai: {unknown_error1}\n\nServer: {openai.api_base}\n\n{server[1]}\n\n{error_tr}')
        return response
    except Exception as unknown_error2:
        error_tr = traceback.format_exc()
        my_log.log2(f'gpt_basic_2.ai: {unknown_error2}\n\n{error_tr}')
        return ''


def clear_mem(mem):
    while 1:
        sizeofmem = count_tokens(mem)
        if sizeofmem <= MAX_CHARS:
            break
        try:
            mem = mem[2:]
        except IndexError:
            mem = []
            break

    return mem[-MAX_MEM_LINES*2:]


def count_tokens(mem) -> int:
    return sum([len(m['content']) for m in mem])


def update_mem(query: str, resp: str, chat_id: str):
    if chat_id not in CHATS:
        CHATS[chat_id] = []
    mem = CHATS[chat_id]
    mem += [{'role': 'user', 'content': query}]
    mem += [{'role': 'assistant', 'content': resp}]
    mem = clear_mem(mem)

    mem__ = []
    try:
        i = 0
        while i < len(mem):
            if i == 0 or mem[i] != mem[i-1]:
                mem__.append(mem[i])
            i += 1
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_haiku(f'my_gpt_basic_3:update_mem: {error}\n\n{error_traceback}\n\n{query}\n\n{resp}\n\n{mem}')

    CHATS[chat_id] = mem__


def chat(query: str, chat_id: str = '', temperature: float = 0.1) -> str:
    global LOCKS, CHATS
    if chat_id in LOCKS:
        lock = LOCKS[chat_id]
    else:
        lock = threading.Lock()
        LOCKS[chat_id] = lock
    with lock:
        if chat_id not in CHATS:
            CHATS[chat_id] = []
        mem = CHATS[chat_id]
        text = ai(query, messages=mem, temp = temperature)
        if text:
            update_mem(query, text, chat_id)
        return text


def chat_cli():
    while 1:
        q = input('>')
        if q == 'mem':
            print(get_mem_as_string('test'))
            continue
        r = chat(f'(отвечай всегда на языке [ru]) ' + q, 'test')
        print(r)


def undo(chat_id: str):
    """
    Undo the last two lines of chat history for a given chat ID.

    Args:
        chat_id (str): The ID of the chat.

    Raises:
        Exception: If there is an error while undoing the chat history.

    Returns:
        None
    """
    try:
        global LOCKS, CHATS

        if chat_id in LOCKS:
            lock = LOCKS[chat_id]
        else:
            lock = threading.Lock()
            LOCKS[chat_id] = lock
        with lock:
            if chat_id in CHATS:
                mem = CHATS[chat_id]
                # remove 2 last lines from mem
                mem = mem[:-2]
                CHATS[chat_id] = mem
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log_haiku(f'Failed to undo chat {chat_id}: {error}\n\n{error_traceback}')


def reset(chat_id: str):
    """
    Resets the chat history for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to reset.

    Returns:
        None
    """
    global CHATS
    CHATS[chat_id] = []


def get_mem_as_string(chat_id: str) -> str:
    """
    Returns the chat history as a string for the given ID.

    Parameters:
        chat_id (str): The ID of the chat to get the history for.

    Returns:
        str: The chat history as a string.
    """
    global CHATS
    if chat_id not in CHATS:
        CHATS[chat_id] = []
    mem = CHATS[chat_id]
    result = ''
    for x in mem:
        role = x['role']
        if role == 'user': role = '𝐔𝐒𝐄𝐑'
        if role == 'assistant': role = '𝐁𝐎𝐓'
        if role == 'system': role = '𝐒𝐘𝐒𝐓𝐄𝐌'
        text = x['content']
        if text.startswith('[Info to help you answer'):
            end = text.find(']') + 1
            text = text[end:].strip()
        result += f'{role}: {text}\n'
        if role == '𝐁𝐎𝐓':
            result += '\n'
    return result 



if __name__ == '__main__':
    # for _ in range(3):
    #     x = random.randint(100, 900)
    #     y = random.randint(100, 900)
    #     print(ai(f'реши пример {x}*{y}, в ответе покажи только запрос и результат так x*y=zzz, одна строчка в ответе и в нем только x*y=zzz'))
    reset('test')
    chat_cli()
