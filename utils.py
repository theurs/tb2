#!/usr/bin/env python3


import hashlib
import html
import multiprocessing
import os
import random
import re
import requests
import string
import subprocess
import telebot
import tempfile
import traceback
import platform as platform_module

import prettytable
from pylatexenc.latex2text import LatexNodes2Text

import my_log


def count_tokens(messages):
    """
    Count the number of tokens in the given messages.

    Parameters:
        messages (list): A list of messages.

    Returns:
        int: The number of tokens in the messages. Returns 0 if messages is empty.
    """
    # токенты никто из пиратов не считает, так что просто считаем символы
    if messages:
       return len(str(messages))
    return 0


def remove_vowels(text: str) -> str:
    """
    Функция для удаления из текста русских и английских гласных букв "а", "о", "e" и "a".
    :param text: текст, в котором нужно удалить гласные буквы
    :type text: str
    :return: текст без указанных гласных букв
    :rtype: str
    """
    vowels = [  'а', 'о',   # русские
                'a', 'e']   # английские. не стоит наверное удалять слишком много
    for vowel in vowels:
        text = text.replace(vowel, '') # заменяем гласные буквы на пустую строку
    return text


class MessageList:
    """список последних сообщений в чате с заданным максимальным размером в байтах
    это нужно для суммаризации событий в чате с помощью бинга
    """
    def __init__(self, max_size=60000):
        self.max_size = max_size
        self.messages = []
        self.size = 0

    def append(self, message: str):
        assert len(message) < (4*1024)+1
        message_bytes = message.encode('utf-8')
        message_size = len(message_bytes)
        if self.size + message_size > self.max_size:
            while self.size + message_size > self.max_size:
                oldest_message = self.messages.pop(0)
                self.size -= len(oldest_message.encode('utf-8'))
        self.messages.append(message)
        self.size += message_size


def split_text(text: str, chunk_limit: int = 1500):
    """ Splits one string into multiple strings, with a maximum amount of chars_per_string
        characters per string. This is very useful for splitting one giant message into multiples.
        If chars_per_string > 4096: chars_per_string = 4096. Splits by '\n', '. ' or ' ' in exactly
        this priority.

        :param text: The text to split
        :type text: str

        :param chars_per_string: The number of maximum characters per part the text is split to.
        :type chars_per_string: int

        :return: The splitted text as a list of strings.
        :rtype: list of str
    """
    return telebot.util.smart_split(text, chunk_limit)


def platform() -> str:
    """
    Return the platform information.
    """
    return platform_module.platform()


def convert_to_mp3(input_file: str) -> str:
    """
    Converts an audio file to the MP3 format.

    Args:
        input_file (str): The path to the input audio file.

    Returns:
        str: The path to the converted MP3 file.
    """
    # Создаем временный файл с расширением .mp3
    temp_file = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
    temp_file.close()
    output_file = temp_file.name
    os.remove(output_file)
    # Конвертируем аудиофайл в wav с помощью ffmpeg
    command = ["ffmpeg", "-i", input_file, '-b:a', '96k', '-map', 'a', output_file]
    subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Проверяем, успешно ли прошла конвертация
    if os.path.exists(output_file):
        return output_file
    else:
        return None


def bot_markdown_to_html(text: str) -> str:
    # переделывает маркдаун от чатботов в хтмл для телеграма
    # сначала делается полное экранирование
    # затем меняются маркдаун теги и оформление на аналогичное в хтмл
    # при этом не затрагивается то что внутри тегов код, там только экранирование
    # латекс код в тегах $ и $$ меняется на юникод текст

    # экранируем весь текст для html
    text = html.escape(text)
    
    # найти все куски кода между ``` и заменить на хеши
    # спрятать код на время преобразований
    matches = re.findall('```(.*?)```', text, flags=re.DOTALL)
    list_of_code_blocks = []
    for match in matches:
        random_string = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(16))
        list_of_code_blocks.append([match, random_string])
        text = text.replace(f'```{match}```', random_string)

    # тут могут быть одиночные поворяющиеся `, меняем их на '
    text = text.replace('```', "'''")

    matches = re.findall('`(.*?)`', text, flags=re.DOTALL)
    list_of_code_blocks2 = []
    for match in matches:
        random_string = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(16))
        list_of_code_blocks2.append([match, random_string])
        text = text.replace(f'`{match}`', random_string)

    # переделываем списки на более красивые
    new_text = ''
    for i in text.split('\n'):
        ii = i.strip()
        if ii.startswith('* '):
            i = i.replace('* ', '• ', 1)
        if ii.startswith('- '):
            i = i.replace('- ', '• ', 1)
        new_text += i + '\n'
    text = new_text.strip()

    # 1 или 2 * в <b></b>
    text = re.sub('\*\*(.+?)\*\*', '<b>\\1</b>', text)

    # tex в unicode
    matches = re.findall("\$\$?(.*?)\$\$?", text, flags=re.DOTALL)
    for match in matches:
        new_match = LatexNodes2Text().latex_to_text(match.replace('\\\\', '\\'))
        text = text.replace(f'$${match}$$', new_match)
        text = text.replace(f'${match}$', new_match)

    # меняем маркдаун ссылки на хтмл
    text = re.sub(r'\[([^\]]*)\]\(([^\)]*)\)', r'<a href="\2">\1</a>', text)
    # меняем все ссылки на ссылки в хтмл теге кроме тех кто уже так оформлен
    text = re.sub(r'(?<!<a href=")(https?://\S+)(?!">[^<]*</a>)', r'<a href="\1">\1</a>', text)

    # меняем таблицы до возвращения кода
    text = replace_tables(text)

    # меняем обратно хеши на блоки кода
    for match, random_string in list_of_code_blocks2:
        # new_match = html.escape(match)
        new_match = match
        text = text.replace(random_string, f'<code>{new_match}</code>')

    # меняем обратно хеши на блоки кода
    for match, random_string in list_of_code_blocks:
        new_match = match
        text = text.replace(random_string, f'<code>{new_match}</code>')

    text = replace_code_lang(text)

    # text = replace_tables(text)

    return text


def replace_code_lang(t: str) -> str:
    """
    Replaces the code language in the given string with appropriate HTML tags.

    Parameters:
        t (str): The input string containing code snippets.

    Returns:
        str: The modified string with code snippets wrapped in HTML tags.
    """
    result = ''
    state = 0
    for i in t.split('\n'):
        if i.startswith('<code>') and len(i) > 7:
            result += f'<pre><code class = "language-{i[6:]}">'
            state = 1
        else:
            if state == 1:
                if i == '</code>':
                    result += '</code></pre>'
                    state = 0
                else:
                    result += i + '\n'
            else:
                result += i + '\n'
    return result


def replace_tables(text: str) -> str:
    text += '\n'
    state = 0
    table = ''
    results = []
    for line in text.split('\n'):
        if line.count('|') > 2 and len(line) > 4:
            if state == 0:
                state = 1
            table += line + '\n'
        else:
            if state == 1:
                results.append(table[:-1])
                table = ''
                state = 0

    for table in results:
        x = prettytable.PrettyTable(align = "l",
                                    set_style = prettytable.MSWORD_FRIENDLY,
                                    hrules = prettytable.HEADER,
                                    junction_char = '|')

        lines = table.split('\n')
        header = [x.strip().replace('<b>', '').replace('</b>', '') for x in lines[0].split('|') if x]
        header = [split_long_string(x, header = True) for x in header]
        try:
            x.field_names = header
        except Exception as error:
            my_log.log2(f'tb:replace_tables: {error}')
            continue
        for line in lines[2:]:
            row = [x.strip().replace('<b>', '').replace('</b>', '') for x in line.split('|') if x]
            row = [split_long_string(x) for x in row]
            try:
                x.add_row(row)
            except Exception as error2:
                my_log.log2(f'tb:replace_tables: {error2}')
                continue
        new_table = x.get_string()
        text = text.replace(table, f'<pre><code>{new_table}</code></pre>')

    return text


def split_html(text: str, max_length: int = 1500) -> list:
    """
    Split the given HTML text into chunks of maximum length, while preserving the integrity
    of HTML tags. The function takes two arguments:
    
    Parameters:
        - text (str): The HTML text to be split.
        - max_length (int): The maximum length of each chunk. Default is 1500.
        
    Returns:
        - list: A list of chunks, where each chunk is a part of the original text.
        
    Raises:
        - AssertionError: If the length of the text is less than or equal to 299.
    """
    if len(text) <= max_length:
        return [text,]
    def find_all(a_str, sub):
        start = 0
        while True:
            start = a_str.find(sub, start)
            if start == -1:
                return
            if sub.startswith('\n'):
                yield start+1
            else:
                yield start+len(sub)
            start += len(sub) # use start += 1 to find overlapping matches

    # find all end tags positions with \n after them
    positions = []
    # ищем либо открывающий тег в начале, либо закрывающий в конце
    tags = ['</b>\n','</a>\n','</pre>\n', '</code>\n',
            '\n<b>', '\n<a>', '\n<pre>', '\n<code>']

    for i in tags:
        for j in find_all(text, i):
            positions.append(j)

    chunks = []

    # нет ни одной найденной позиции, тупо режем по границе
    if not positions:
        chunks.append(text[:max_length])
        chunks += split_html(text[max_length:], max_length)
        return chunks

    for i in list(reversed(positions)):
        if i < max_length:
            chunks.append(text[:i])
            chunks += split_html(text[i:], max_length)
            return chunks

    # позиции есть но нет такой по которой можно резать,
    # значит придется резать просто по границе
    chunks.append(text[:max_length])
    chunks += split_html(text[max_length:], max_length)
    return chunks


def split_long_string(long_string: str, header = False, MAX_LENGTH = 24) -> str:
    if len(long_string) <= MAX_LENGTH:
        return long_string
    if header:
        return long_string[:MAX_LENGTH-2] + '..'
    split_strings = []
    while len(long_string) > MAX_LENGTH:
        split_strings.append(long_string[:MAX_LENGTH])
        long_string = long_string[MAX_LENGTH:]

    if long_string:
        split_strings.append(long_string)

    result = "\n".join(split_strings) 
    return result



def download_image(url):
    """
    Downloads an image from the given URL.

    Parameters:
        url (str): The URL of the image to download.

    Returns:
        bytes or None: The content of the image if the download is successful, otherwise None.
    """
    response = requests.get(url, timeout=10)
    if response.status_code == 200:
        return response.content
    else:
        return None


def download_images(urls):
    """
    Downloads images from a list of URLs in parallel using multiprocessing.Pool.

    Args:
        urls (list): A list of strings representing the URLs of the images to be downloaded.

    Returns:
        list: A list of downloaded images. The list may contain None values for failed downloads.
    """
    with multiprocessing.Pool(10) as pool:
        images = pool.map(download_image, urls)
    images = [x for x in images if x]
    return images


def nice_hash(s: str, l: int = 12) -> str:
    """
    Generate a nice hash of the given string.

    Parameters:
        s (str): The string to hash.

    Returns:
        str: The nice hash of the string.
    """
    hash_object = hashlib.sha224(s.encode())
    return f'{hash_object.hexdigest()[:l]}'


def mime_from_buffer(data: bytes) -> str:
    """
    Get the MIME type of the given buffer.

    Parameters:
        data (bytes): The buffer to get the MIME type of.

    Returns:
        str: The MIME type of the buffer.
    """
    pdf_signature = b'%PDF-1.'
    epub_signature = b'%!PS-Adobe-3.0'
    docx_signature = b'\x00\x00\x00\x0c'
    doc_signature = b'PK\x03\x04'
    html_signature = b'<!DOCTYPE html>'
    odt_signature = b'<!DOCTYPE html>'
    rtf_signature = b'<!DOCTYPE html>'
    xlsx_signature = b'\x50\x4b\x03\x04'

    if data.startswith(pdf_signature):
        return 'application/pdf'
    elif data.startswith(epub_signature):
        return 'application/epub+zip'
    elif data.startswith(docx_signature):
        return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif data.startswith(doc_signature):
        return 'application/msword'
    elif data.startswith(html_signature):
        return 'text/html'
    elif data.startswith(odt_signature):
        return 'application/vnd.oasis.opendocument.text'
    elif data.startswith(rtf_signature):
        return 'text/rtf'
    elif data.startswith(xlsx_signature):
        return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        return 'plain'


def download_image_as_bytes(url: str) -> bytes:
    """Загружает изображение по URL-адресу и возвращает его в виде байтов.

    Args:
        url: URL-адрес изображения.

    Returns:
        Изображение в виде байтов.
    """

    try:
        response = requests.get(url, timeout=10)
    except Exception as error:
        error_traceback = traceback.format_exc()
        my_log.log2(f'download_image_as_bytes: {error}\n\n{error_traceback}')
        return None
    return response.content


if __name__ == '__main__':
    urls = ['https://apps3proxy.mosmetro.tech/2_6.jpg',
            'https://catalog.detmir.st/media/rVt2_p5HYGlEkW6LONr4fgvECqMsVvi6uSFyo57b03Y=?preset=site_product_gallery_r1500',
            'https://upload.wikimedia.org/wikipedia/commons/thumb/8/82/VQ-BEI_%286919052100%29.jpg/1200px-VQ-BEI_%286919052100%29.jpg',
            'https://avtomir.ru/upload/uf/e15/25fuuni2p5rdamt5akx52tnodey28ef0.png',
            'https://modeli-korabli.ru/images/ships/tmp/korabli/HMS_Victory_T_034/img_06541.jpg',
            ]
    
    print([len(x) for x in download_images(urls)])
    print(1)