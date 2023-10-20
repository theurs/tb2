#!/usr/bin/env python3


import bingai
import cfg
import gpt_basic
import my_log


def openai(prompt: str):
    """рисует 4 картинок с помощью openai и возвращает сколько смог нарисовать"""
    try:
        return gpt_basic.image_gen(prompt, amount = 6)
    except Exception as error_openai_img:
        print(f'my_genimg:openai: {error_openai_img}')
        my_log.log2(f'my_genimg:openai: {error_openai_img}')
    return []


def gen_images(prompt: str):
    """рисует с помощью бинга и с сервисом от chimera"""
    return bingai.gen_imgs(prompt) + openai(prompt)


if __name__ == '__main__':
    print(gen_images('мотоцикл из золота под дождем'))
