#!/usr/bin/env python3


import io
import os
import re
import sys
from urllib.parse import urlparse

import chardet
import magic
import PyPDF2
import requests
import trafilatura
from youtube_transcript_api import YouTubeTranscriptApi

import cfg
import gpt_basic
import my_log
import my_claude


def get_text_from_youtube(url: str) -> str:
    """Вытаскивает текст из субтитров на ютубе

    Args:
        url (str): ссылка на ютуб видео

    Returns:
        str: первые субтитры из списка какие есть в видео
    """
    top_langs = ('ru', 'en', 'uk', 'es', 'pt', 'fr', 'ar', 'id', 'it', 'de', 'ja', 'ko', 'pl', 'th', 'tr', 'nl', 'hi', 'vi', 'sv', 'ro')
    video_id = re.search(r"(?:v=|\/)([a-zA-Z0-9_-]{11})(?:\?|&|\/|$)", url).group(1)
    t = YouTubeTranscriptApi.get_transcript(video_id, languages=top_langs)
    text = '\n'.join([x['text'] for x in t])
    return text or ''


def summ_text_worker(text: str, subj: str = 'text') -> str:
    """параллельный воркер для summ_text
       subj == 'text' or 'pdf'  - обычный текст о котором ничего не известно
       subj == 'chat_log'       - журнал чата
       subj == 'youtube_video'  - субтитры к видео на ютубе
    """

    # если запустили из pool.map и передали параметры как список
    if isinstance(text, tuple):
        text, subj, _ = text[0], text[1], text[2]

    if subj == 'text' or subj == 'pdf':
        prompt = f"""Summarize the following text, briefly answer in Russian with easy-to-read formatting:
-------------
{text}
-------------
BEGIN:
"""
    elif subj == 'chat_log':
        prompt = f"""Summarize the following telegram chat log, briefly answer in Russian with easy-to-read formatting:
-------------
{text}
-------------
BEGIN:
"""
    elif subj == 'youtube_video':
        prompt = f"""Summarize the following video subtitles extracted from youtube, briefly answer in Russian with easy-to-read formatting:
-------------
{text}
-------------
"""

    if not isinstance(text, str) or len(text) < 1:
        return ''

    result = ''

    # если текст большой то пытаемся его осилить с помощью клода
    if len(prompt) > cfg.max_request:
        try:
            response = my_claude.chat(prompt[:my_claude.MAX_QUERY], 'my_summ')
            if response:
                # to_remove = [
                #     'Вот краткое резюме видео на русском языке в простом формате:',
                #     'Вот краткое резюме основных моментов видео на русском языке в удобочитаемом формате:',
                #     'Вот краткое резюме основных моментов видео на русском языке в простом формате:',
                #     'Вот краткое резюме на русском языке с удобочитаемым форматированием:',
                # ]
                # for i in to_remove:
                #     response = response.replace(i, '', 1)
                first_line = response.split('\n', maxsplit=1)[0].lower()
                if 'краткое резюме' in first_line:
                    response = response.split('\n', maxsplit=1)[1].strip()
                result = f'{response}\n\n[Claude Anthropic {len(prompt[:my_claude.MAX_QUERY])} символов]'
        except Exception as error:
            print(error)
            my_log.log2(f'my_sum:summ_text_worker:claude: {error}')

    if not result:
        try:
            response = gpt_basic.ai(prompt[:cfg.max_request])
            if response:
                result = f'{response}\n\n[chatGPT {len(prompt[:cfg.max_request])} символов]'
        except Exception as error:
            print(error)
            my_log.log2(f'my_sum:summ_text_worker:chatgpt: {error}')

    return result


def summ_text(text: str, subj: str = 'text') -> str:
    """сумморизирует текст с помощью бинга или гптчата или клод-100к, возвращает краткое содержание, только первые 30(60)(99)т символов
    subj - смотрите summ_text_worker()
    """
    return summ_text_worker(text, subj)


def summ_url(url:str) -> str:
    """скачивает веб страницу, просит гптчат или бинг сделать краткое изложение текста, возвращает текст
    если в ссылке ютуб то скачивает субтитры к видео вместо текста"""
    youtube = False
    pdf = False
    if '/youtu.be/' in url or 'youtube.com/' in url:
        text = get_text_from_youtube(url)
        youtube = True
    else:
        # Получаем содержимое страницы
                
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}

        response = requests.get(url, stream=True, headers=headers, timeout=10)
        content = b''
        # Ограничиваем размер
        for chunk in response.iter_content(chunk_size=1024):
            content += chunk
            if len(content) > 1 * 1024 * 1024: # 1 MB
                break

        if 'PDF document' in magic.from_buffer(content):
            pdf = True
            file_bytes = io.BytesIO(content)
            pdf_reader = PyPDF2.PdfReader(file_bytes)
            text = ''
            for page in pdf_reader.pages:
                text += page.extract_text()
        else:
            # Определяем кодировку текста
            encoding = chardet.detect(content)['encoding']
            # Декодируем содержимое страницы
            try:
                content = content.decode(encoding)
            except UnicodeDecodeError as error:
                print(error)
                content = response.content.decode('utf-8')

            newconfig = trafilatura.settings.use_config()
            newconfig.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")
            text = trafilatura.extract(content, config=newconfig)
   
    #return text
    if youtube:
        result = summ_text(text, 'youtube_video')
    elif pdf:
        result = summ_text(text, 'pdf')
    else:
        result = summ_text(text, 'text')
    return result


def is_valid_url(url: str) -> bool:
    """Функция is_valid_url() принимает строку url и возвращает True, если эта строка является веб-ссылкой,
    и False в противном случае."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


if __name__ == "__main__":
    """Usage ./summarize.py '|URL|filename"""
    
   
    r = summ_url('https://www.youtube.com/watch?v=Nl18-rL3ZaQ')
    print(r)
    sys.exit(0)
    
    target = sys.argv[1]

    if is_valid_url(target):
        print(summ_url(target))
    elif os.path.exists(target):
        print(summ_text(open(target).read()))
    else:
        print("""Usage ./summarize.py '|URL|filename""")
    