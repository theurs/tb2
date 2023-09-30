#!/usr/bin/env python3


import subprocess


def ask(query: str) -> str:
    process = subprocess.Popen(['./my_perplexity_cmd.py', query], stdout = subprocess.PIPE)
    output, error = process.communicate()
    r = output.decode('utf-8').strip()
    if error != None:
        return None
    return r


if __name__ == '__main__':
    print(ask('1+1'))  
