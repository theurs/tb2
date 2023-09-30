#!/usr/bin/env python3


import html
import json

import my_log
import utils
from Perplexity import Perplexity


def ask(query: str, search_focus: str = 'internet') -> str:
    query += ' (отвечай на русском языке)'

    assert search_focus in ["internet", "scholar", "news", "youtube", "reddit", "wikipedia"], "Invalid search focus"

    # пробуем 3 раза получить ответ
    for _ in range(3):
        try:
            perplexity = Perplexity()
            # answer = perplexity.search(query, search_focus=search_focus)
            answer = ''
            answer = perplexity.search(query)
            result = ''
            for i in answer:
                d = json.loads(i['text'])
                result += d['answer']
                if i['step_type'] == 'FINAL':
                    result += '\n\n'
                    for x in d['web_results']:
                        result += f'<a href="{x["url"]}">{x["name"]}</a>\n'
            answer = result
        except Exception as error:
            answer = ''
            print(error)
            my_log.log2(f'my_perplexity.py:ask: {error}')
 
    return answer


if __name__ == '__main__':

    print(ask('1+1'))
    while 1:
        query = input('> ')
        print(ask(query))
