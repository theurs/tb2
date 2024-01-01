#!/usr/bin/env python3


import bing_img
import my_log


def bing(prompt: str, moderation_flag: bool = False):
    """рисует 4 картинки с помощью далли и возвращает сколько смог нарисовать"""
    if moderation_flag:
        return []
    try:
        images = bing_img.gen_images(prompt)
        if type(images) == list:
            return images
    except Exception as error_bing_img:
        my_log.log2(f'my_genimg:bing: {error_bing_img}')
    return []


def gen_images(prompt: str, moderation_flag: bool = False):
    return bing(prompt, moderation_flag)


if __name__ == '__main__':
    # print(ddg_search_images('сочная малина'))
    print(gen_images('рисунок мальчика с чёрными волосами в костюме жирафа и девочки с рыжими волосами в костюме лисы, наклейки, логотип, минимализм, в новый год, наряжают ёлку'))
