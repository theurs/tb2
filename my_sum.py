#!/usr/bin/env python3
#pip install lxml[html_clean]

import io
import os
import re
import sys
from urllib.parse import urlparse
from youtube_transcript_api import YouTubeTranscriptApi

import chardet
# import magic
import PyPDF2
import requests
import trafilatura

import my_log
import my_gemini
import my_groq
import utils


def get_text_from_youtube(url: str) -> str:
    """Вытаскивает текст из субтитров на ютубе

    Args:
        url (str): ссылка на ютуб видео

    Returns:
        str: первые субтитры из списка какие есть в видео
    """
    top_langs = ('ru', 'en', 'uk', 'es', 'pt', 'fr', 'ar', 'id', 'it', 'de', 'ja', 'ko', 'pl', 'th', 'tr', 'nl', 'hi', 'vi', 'sv', 'ro')

    try:
        video_id = re.search(r"(?:v=|\/)([a-zA-Z0-9_-]{11})(?:\?|&|\/|$)", url).group(1)
    except:
        return ''

    try:
        t = YouTubeTranscriptApi.get_transcript(video_id, languages=top_langs)
    except Exception as error:
        if 'If you are sure that the described cause is not responsible for this error and that a transcript should be retrievable, please create an issue at' not in str(error):
            my_log.log2(f'get_text_from_youtube: {error}')
        t = ''

    text = '\n'.join([x['text'] for x in t])
    
    return text.strip() or ''


def summ_text_worker(text: str, subj: str = 'text', lang: str = 'ru', query: str = '') -> str:
    """параллельный воркер для summ_text
       subj == 'text' or 'pdf'  - обычный текст о котором ничего не известно
       subj == 'chat_log'       - журнал чата
       subj == 'youtube_video'  - субтитры к видео на ютубе
    """

    # если запустили из pool.map и передали параметры как список
    if isinstance(text, tuple):
        text, subj, _ = text[0], text[1], text[2]

    if type(text) != str or len(text) < 1: return ''

    result = ''

    if subj == 'youtube_video':
        qq = f'''Summarize the content of this YouTube video.

Answer in [{lang}] language.

The structure of the answer should be similar to the following:
Show a block with the brief summary of the video in 2 sentences, which satisfies most people.
Show a block with a detail summary of the content of the video in your own words, 300-2000 words.

Extracted subtitles:
'''
    else:
        qq = f'''Summarize the content of this text.

Answer in [{lang}] language.

The structure of the answer should be similar to the following:
Show a block with the brief summary of the text in 2 sentences, which satisfies most people.
Show a block with a detail summary of the content of the text in your own words, 300-2000 words.

Text:'''

    if not result:
        try:
            if query:
                qq = query
            r = my_gemini.sum_big_text(text[:my_gemini.MAX_SUM_REQUEST], qq).strip()
            if r != '':
                result = f'{r}\n\n--\nGemini Pro [{len(text[:my_gemini.MAX_SUM_REQUEST])}]'
        except Exception as error:
            print(f'my_sum:summ_text_worker:gpt: {error}')
            my_log.log2(f'my_sum:summ_text_worker:gpt: {error}')


    if not result:
        try:
            if query:
                qq = query
            r = my_groq.sum_big_text(text[:32000], qq, model = 'mixtral-8x7b-32768').strip()
            if r != '':
                result = f'{r}\n\n--\nMixtral-8x7b-32768 [Groq] [{len(text[:32000])}]'
        except Exception as error:
            print(f'my_sum:summ_text_worker:gpt: {error}')
            my_log.log2(f'my_sum:summ_text_worker:gpt: {error}')

    if not result:
        try:
            if query:
                qq = query
            r = my_groq.sum_big_text(text[:my_groq.MAX_QUERY_LENGTH], qq).strip()
            if r != '':
                result = f'{r}\n\n--\nLlama3 70b [Groq] [{len(text[:my_groq.MAX_QUERY_LENGTH])}]'
        except Exception as error:
            print(f'my_sum:summ_text_worker:gpt: {error}')
            my_log.log2(f'my_sum:summ_text_worker:gpt: {error}')

    return result


def summ_text(text: str, subj: str = 'text', lang: str = 'ru', query: str = '') -> str:
    """сумморизирует текст с помощью бинга или гптчата или клод-100к, возвращает краткое содержание, только первые 30(60)(99)т символов
    subj - смотрите summ_text_worker()
    """
    return summ_text_worker(text, subj, lang, query)


def summ_url(url:str, download_only: bool = False, lang: str = 'ru'):
    """скачивает веб страницу, просит гптчат или бинг сделать краткое изложение текста, возвращает текст
    если в ссылке ютуб то скачивает субтитры к видео вместо текста
    может просто скачать текст без саммаризации, для другой обработки"""
    youtube = False
    pdf = False
    if '/youtu.be/' in url or 'youtube.com/' in url:
        text = get_text_from_youtube(url)
        youtube = True
    else:
        # Получаем содержимое страницы
                
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}

        try:
            response = requests.get(url, stream=True, headers=headers, timeout=20)
            content = b''
            # Ограничиваем размер
            for chunk in response.iter_content(chunk_size=1024):
                content += chunk
                if len(content) > 1 * 1024 * 1024: # 1 MB
                    break
        except:
            if download_only:
                return ''
            else:
                return '', ''

        if utils.mime_from_buffer(content) == 'application/pdf':
            pdf = True
            file_bytes = io.BytesIO(content)
            pdf_reader = PyPDF2.PdfReader(file_bytes)
            text = ''
            for page in pdf_reader.pages:
                text += page.extract_text()
        else:
            # Определяем кодировку текста
            encoding = chardet.detect(content[:2000])['encoding']
            # Декодируем содержимое страницы
            try:
                content = content.decode(encoding)
            except:
                try:
                    content = content.decode('utf-8')
                except:
                    if download_only:
                        return ''
                    else:
                        return '', ''

            text = trafilatura.extract(content)
   
    if download_only:
        if youtube:
            r = f'URL: {url}\nСубтитры из видео на ютубе (полное содержание, отметки времени были удалены):\n\n{text}'
        else:
            r = f'URL: {url}\nРаспознанное содержание веб страницы:\n\n{text}'
        return r
    else:
        if youtube:
            r = summ_text(text, 'youtube_video', lang)
        elif pdf:
            r = summ_text(text, 'pdf', lang)
        else:
            r = summ_text(text, 'text', lang)
        return r, text


def is_valid_url(url: str) -> bool:
    """Функция is_valid_url() принимает строку url и возвращает True, если эта строка является веб-ссылкой,
    и False в противном случае."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


if __name__ == "__main__":

    # print(summ_url('https://telegra.ph/Tomm-05-19', download_only=True))

    print(summ_url('https://www.youtube.com/watch?v=nrFjjsAc_E8')[0])
    # print(summ_url('https://www.youtube.com/watch?v=0uOCF04QcHk')[0])
    # print(summ_url('https://www.youtube.com/watch?v=IVTzUg50f_4')[0])
    # print(summ_url('https://www.youtube.com/watch?v=0MehBAmxj-E')[0])
    # print(summ_url('https://www.youtube.com/watch?v=-fbQK1to7-s')[0])
    # print(summ_url('https://www.youtube.com/watch?v=5ijY7TjBwVk')[0])
    # print(summ_url('https://www.youtube.com/watch?v=uNCsO0JytPA')[0])
    # print(summ_url('https://www.youtube.com/watch?v=DZkEg82Nc_k')[0])
    
    # print(summ_url('https://www.linux.org.ru/news/opensource/17620258')[0])
    # print(summ_url('https://habr.com/ru/companies/productradar/articles/815709/')[0])
    # print(summ_url('https://habr.com/ru/news/815789/')[0])
    # print(summ_url('http://lib.ru/RUFANT/ABARINOWA/shwabra.txt')[0])
    # print(summ_url('http://lib.ru/RUFANT/ABARINOWA/nederzhanie_istiny.txt')[0])

