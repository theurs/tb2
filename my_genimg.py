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
    bing_images = bingai.gen_imgs(prompt)
    if not isinstance(bing_images, list):
        bing_images = []
    openai_images = openai(prompt)
    if not isinstance(openai_images, list):
        openai_images = []
    return bing_images + openai_images


if __name__ == '__main__':
    print(gen_images('мотоцикл из золота под дождем'))
