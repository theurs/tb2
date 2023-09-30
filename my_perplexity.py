#!/usr/bin/env python3


import html
import json

import my_log
import utils
from Perplexity import Perplexity


def ask(query: str, search_focus: str = 'internet') -> str:
    query += ' (отвечай на русском языке)'

    assert search_focus in ["internet", "scholar", "news", "youtube", "reddit", "wikipedia"], "Invalid search focus"

    try:
        perplexity = Perplexity()
        answer = perplexity.search(query, search_focus=search_focus)
        result = ''
        for i in answer:
            d = json.loads(i['text'])
            result += d['answer']
            try:
                if i['step_type'] == 'FINAL':
                    result += '\n\n'
                    for x in d['web_results']:
                        result += f'<a href="{x["url"]}">{x["name"]}</a>\n'
            except Exception as error:
                if 'step_type' not in error:
                    print(error)
                    my_log.log2(f'my_perplexity.py:ask: {error}')
    except Exception as error:
        print(error)
        my_log.log2(f'my_perplexity.py:ask: {error}')
 
    return result


if __name__ == '__main__':

    print(ask('курс рубля к доллару и прогноз'))
    while 1:
        query = input('> ')
        print(ask(query))
