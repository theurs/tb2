#!/usr/bin/env python3


import threading
import re
import requests

from bardapi import Bard
from textblob import TextBlob

import cfg
import my_log
import utils


# хранилище сессий {chat_id(int):session(bardapi.Bard),...}
DIALOGS = {}
# хранилище замков что бы юзеры не могли делать новые запросы пока не получен ответ на старый
# {chat_id(str):threading.Lock(),...}
CHAT_LOCKS = {}

# максимальный размер запроса который принимает бард, получен подбором
MAX_REQUEST = 3100


# указатель на текущий ключ в списке ключей (токенов)
current_token = 0
# если задан всего 1 ключ то продублировать его, что бы было 2, пускай и одинаковые но 2
if len(cfg.bard_tokens) == 1:
    cfg.bard_tokens.append(cfg.bard_tokens[0])
# на случай если все ключи протухли надо использовать счетчик что бы не попасть в петлю
loop_detector = {}


def get_new_session():
    """
    Retrieves a new session for making HTTP requests.

    Args:


    Returns:
        Bard: An instance of the Bard class representing the new session.
    """
    proxies = None

    session = requests.Session()

    session.cookies.set("__Secure-1PSID", cfg.bard_tokens[current_token])

    session.headers = {
        "Host": "bard.google.com",
        "X-Same-Domain": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Origin": "https://bard.google.com",
        "Referer": "https://bard.google.com/",
        }

    bard = Bard(token=cfg.bard_tokens[current_token], proxies=proxies, session=session, timeout=30)

    rules = """Отвечай на русском языке, коротко."""

    #my_log.log2(str(rules))
    r = bard.get_answer(rules)
    #my_log.log2(str(r))

    return bard


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
        DIALOGS[dialog] = session

    try:
        response = session.get_answer(query)
    except Exception as error:
        print(error)
        my_log.log2(str(error))

        try:
            del DIALOGS[dialog]
            session = get_new_session()
            DIALOGS[dialog] = session
        except KeyError:
            print(f'no such key in DIALOGS: {dialog}')
            my_log.log2(f'my_bard.py:chat_request:no such key in DIALOGS: {dialog}')

        try:
            response = session.get_answer(query)
        except Exception as error2:
            print(error2)
            my_log.log2(str(error2))
            return ''

    result = response['content']

    try:
        links = list(set([x for x in response['links'] if 'http://' not in x]))
    except Exception as links_error:
        # вероятно получили ответ с ошибкой слишком частого доступа, надо сменить ключ
        global current_token
        if dialog in loop_detector:
            loop_detector[dialog] += 1
        else:
            loop_detector[dialog] = 1
        if loop_detector[dialog] >= len(cfg.bard_tokens):
            loop_detector[dialog] = 0
            return ''
        current_token += 1
        if current_token >= len(cfg.bard_tokens):
            current_token = 0
        print(links_error)
        my_log.log2(f'my_bard.py:chat_request:bard token rotated:current_token: {current_token}\n\n{links_error}')
        chat_request(query, dialog, reset = True)
        return chat_request(query, dialog, reset)

    if len(links) > 6:
        links = links[:6]
    try:
        if links:
            for url in links:
                if url:
                    # result += f"\n\n[{url}]({url})"
                    result += f"\n\n{url}"
    except Exception as error:
        print(error)
        my_log.log2(str(error))

    # images = response['images']
    # if len(images) > 6:
    #   images = images[:6]
    # try:
    #    if images:
    #        for image in images:
    #            if str(image):
    #                result += f"\n\n{str(image)}"
    # except Exception as error2:
    #    print(error2)
    #    my_log.log2(str(error2))

    if len(result) > 16000:
        return result[:16000]
    else:
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
    with lock:
        result = chat_request(query, dialog, reset)
    return result


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


def split_text(text: str, max_size: int = MAX_REQUEST) -> list:
    """
    Split the given text into chunks of sentences, where each chunk does not exceed the maximum size.

    Args:
        text (str): The text to be split.
        max_size (int, optional): The maximum size of each chunk. Defaults to MAX_REQUEST.

    Returns:
        list: A list of chunks, where each chunk contains a group of sentences.
    """
    if len(text) < 500:
        return text

    text = text.replace(u"\xa0\xa0", " ")
    text = text.replace(u"\xa0", " ")

    blob = TextBlob(text)
    sentences = blob.sentences
    chunk = ''
    chunks = []
    sentences2 = []

    for sentence in sentences:
        if len(sentence) > max_size-300:
            sentences2 += [x for x in utils.split_text(sentence, int(max_size/2))]
        else:
            sentences2.append(sentence)

    for sentence in sentences2:
        sentence = sentence.replace("\n", " ")
        sentence = re.sub(r'\s{2,}', ' ', str(sentence))
        if len(chunk) + len(sentence) < max_size:
            chunk += str(sentence) + ' '
        else:
            chunks.append(chunk)
            chunk = sentence
    if chunk:
        chunks.append(chunk)
    return chunks


def bard_clear_text_chunk_voice(chunk: str) -> str:
    """
    Clears a text chunk from voice by making it more readable and correcting typical
    voice recognition errors.

    :param chunk: The text chunk to be cleared.
    :type chunk: str
    :return: The cleared text chunk.
    :rtype: str
    """
    query = '''Исправь форматирование текста аудиосообщения, сделай его легко читаемым, разбей на абзацы,
исправь характерные ошибки распознавания голоса, убери лишние переносы строк, в ответе должен быть
только исправленный текст, максимально короткий ответ.


''' + chunk

    try:
        response = chat(query, 0)
    except Exception as error:
        print(error)
        my_log.log2(f'my_bard.py:bard_clear_text_chunk_voice:{error}')
        return chunk

    return response.strip()


def clear_voice_message_text(text: str) -> str:
    """
    Clear the voice message text with using Bard AI.

    Parameters:
        text (str): The voice message text to be cleared.
    
    Returns:
        str: The cleared voice message text as a single string.
    """
    result = ''
    for chunk in split_text(text, 2500):
        result += bard_clear_text_chunk_voice(chunk) + '\n\n'
    result = result.strip()
    return result


if __name__ == "__main__":
    pass
