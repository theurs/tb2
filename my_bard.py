#!/usr/bin/env python3


import threading
import random
import re
import requests

from bardapi import Bard

import cfg
import my_log


# хранилище для ссылок и картинок в ответах [(text, [images], [links]),...]
REPLIES = []

# хранилище сессий {chat_id(int):session(bardapi.Bard),...}
DIALOGS = {}
# хранилище замков что бы юзеры не могли делать новые запросы пока не получен ответ на старый
# {chat_id(str):threading.Lock(),...}
CHAT_LOCKS = {}

# максимальный размер запроса который принимает бард, получен подбором
# MAX_REQUEST = 3100
MAX_REQUEST = 14000


# loop detector
LOOP = {}


def get_new_session():
    """
    Retrieves a new session for making HTTP requests.

    Args:


    Returns:
        Bard: An instance of the Bard class representing the new session.
    """
    try:
        proxies = cfg.proxies
    except:
        proxies = None

    session = requests.Session()

    random.shuffle(cfg.bard_tokens)
    session.cookies.set("__Secure-1PSID", cfg.bard_tokens[0])

    session.headers = {
        "Host": "bard.google.com",
        "X-Same-Domain": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Origin": "https://bard.google.com",
        "Referer": "https://bard.google.com/",
        }

    for token in cfg.bard_tokens:
        bard = Bard(token=token, proxies=proxies, session=session, timeout=30)

        rules = """Отвечай на русском языке, коротко."""

        r = bard.get_answer(rules)
        if r['content']:
            return bard

    return None


def reset_bard_chat(dialog: str):
    """
    Deletes a specific dialog from the DIALOGS dictionary.

    Args:
        dialog (str): The key of the dialog to be deleted.

    Returns:
        None
    """
    try:
        del DIALOGS[dialog]
    except KeyError:
        print(f'no such key in DIALOGS: {dialog}')
        my_log.log2(f'my_bard.py:reset_bard_chat:no such key in DIALOGS: {dialog}')
    return


def chat_request(query: str, dialog: str, reset = False) -> str:
    """
    Generates a response to a chat request.

    Args:
        query (str): The user's query.
        dialog (str): The dialog number.
        reset (bool, optional): Whether to reset the dialog. Defaults to False.

    Returns:
        str: The generated response.
    """
    if reset:
        reset_bard_chat(dialog)
        return

    if dialog in DIALOGS:
        session = DIALOGS[dialog]
    else:
        session = get_new_session()
        assert session != None, 'no bard session found'
        DIALOGS[dialog] = session

    try:
        response = session.get_answer(query)
    except Exception as error:
        print(error)
        my_log.log2(str(error))

        try:
            del DIALOGS[dialog]
            session = get_new_session()
            assert session != None, 'no bard session found'
            DIALOGS[dialog] = session
        except Exception as error:
            print(f'my_bard:chat_request: {error}')
            my_log.log2(f'my_bard:chat_request: {error}')
            return ''
        try:
            response = session.get_answer(query)
        except Exception as error2:
            print(error2)
            my_log.log2(str(error2))
            return ''

    result = response['content']
    
    # удалить картинки из текста, телеграм все равно не может их показывать посреди текста
    result = re.sub("\[Image of .*?\]", "", result)
    result = result.replace("\n\n", "\n")
    result = result.replace("\n\n", "\n")

    try:
        links = list(set([x for x in response['links'] if 'http://' not in x]))
    except Exception as links_error:
        # вероятно получили ответ с ошибкой слишком частого доступа, надо сменить ключ
        print(links_error)
        my_log.log2(f'my_bard.py:chat_request: {links_error}')

        if dialog in LOOP:
            LOOP[dialog] += 1
        else:
            LOOP[dialog] = 1
        if LOOP[dialog] > 2:
            del LOOP[dialog]
            return ''

        chat_request(query, dialog, reset = True)
        return chat_request(query, dialog, reset)



    images = []
    if response['images']:
        for key in response['images']:
            if key:
                images.append(key)

    links = []
    if response['links']:
        for key in response['links']:
            if key:
                links.append(key)

    global REPLIES
    REPLIES.append((result, images, links))
    REPLIES = REPLIES[-20:]



    if dialog in LOOP:
        del LOOP[dialog]

    if len(result) > 4000:
        return result[:4000]
    else:
        return result


def chat(query: str, dialog: str, reset: bool = False) -> str:
    """
    Executes a chat request with the given query and dialog ID.

    Args:
        query (str): The query to be sent to the chat API.
        dialog (str): The ID of the dialog to send the request to.
        reset (bool, optional): Whether to reset the conversation. Defaults to False.

    Returns:
        str: The response from the chat API.
    """
    if dialog in CHAT_LOCKS:
        lock = CHAT_LOCKS[dialog]
    else:
        lock = threading.Lock()
        CHAT_LOCKS[dialog] = lock
    result = ''
    with lock:
        try:
            result = chat_request(query, dialog, reset)
        except Exception as error:
            print(f'my_bard:chat: {error}')
            my_log.log2(f'my_bard:chat: {error}')
            try:
                result = chat_request(query, dialog, reset)
            except Exception as error2:
                print(f'my_bard:chat:2: {error2}')
                my_log.log2(f'my_bard:chat:2: {error2}')
    return result


def chat_request_image(query: str, dialog: str, image: bytes, reset = False):
    """
    Function to make a chat request with an image.
    
    Args:
        query (str): The query for the chat request.
        dialog (str): The index of the dialog.
        image (bytes): The image to be used in the chat request.
        reset (bool, optional): Whether to reset the chat dialog. Defaults to False.
    
    Returns:
        str: The response from the chat request.
    """
    if reset:
        reset_bard_chat(dialog)
        return

    if dialog in DIALOGS:
        session = DIALOGS[dialog]
    else:
        session = get_new_session()
        DIALOGS[dialog] = session

    try:
        response = session.ask_about_image(query, image)['content']
    except Exception as error:
        print(error)
        my_log.log2(str(error))

        try:
            del DIALOGS[dialog]
            session = get_new_session()
            DIALOGS[dialog] = session
        except KeyError:
            print(f'no such key in DIALOGS: {dialog}')
            my_log.log2(f'my_bard.py:chat:no such key in DIALOGS: {dialog}')

        try:
            response = session.ask_about_image(query, image)['content']
        except Exception as error2:
            print(error2)
            my_log.log2(str(error2))
            return ''

    return response


def chat_image(query: str, dialog: str, image: bytes, reset: bool = False) -> str:
    """
    Executes a chat request with an image.

    Args:
        query (str): The query string for the chat request.
        dialog (str): The ID of the dialog.
        image (bytes): The image to be included in the chat request.
        reset (bool, optional): Whether to reset the dialog state. Defaults to False.

    Returns:
        str: The response from the chat request.
    """
    if dialog in CHAT_LOCKS:
        lock = CHAT_LOCKS[dialog]
    else:
        lock = threading.Lock()
        CHAT_LOCKS[dialog] = lock
    with lock:
        result = chat_request_image(query, dialog, image, reset)
    return result


if __name__ == "__main__":
    print(chat('hi', '0'))
