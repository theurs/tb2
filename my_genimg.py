#!/usr/bin/env python3


from multiprocessing.pool import ThreadPool

import bingai
import gpt_basic
import my_log


def openai(prompt: str):
    """рисует 4 картинок с помощью openai и возвращает сколько смог нарисовать"""
    try:
        return gpt_basic.image_gen(prompt, amount = 4)
    except Exception as error_openai_img:
        print(f'my_genimg:openai: {error_openai_img}')
        my_log.log2(f'my_genimg:openai: {error_openai_img}')
    return []


def gen_images(prompt: str):
    """рисует одновременно и с помощью бинга и с сервисом от chimera"""

    pool = ThreadPool(processes=2)

    async_result1 = pool.apply_async(bingai.gen_imgs, (prompt,))
    async_result2 = pool.apply_async(openai, (prompt,))

    bing_images = async_result1.get()
    openai_images = async_result2.get()

    if not isinstance(bing_images, list):
        bing_images = []
    if not isinstance(openai_images, list):
        openai_images = []

    return bing_images + openai_images


if __name__ == '__main__':
    print(gen_images('мотоцикл из золота под дождем'))
