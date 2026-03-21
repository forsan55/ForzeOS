import os
import re
import sys
import json
import math
import time
import random
import hashlib
import logging

SCRIPT_PATH = r'C:\Users\User\Downloads\ForzeOS System.py'


def extract_class_src(path: str, classname: str) -> str:
    src = open(path, 'r', encoding='utf-8').read()
    start = src.find(f'class {classname}:')
    if start == -1:
        return ''
    # Heuristic end marker: look for the next top-level comment marker we know follows the class
    end_marker = '\n\n# --- Security helpers'
    end = src.find(end_marker, start)
    if end == -1:
        # fallback: try to find two consecutive blank lines after start
        m = re.search(r'\n\n\S', src[start:])
        end = start + m.start() if m else len(src)
    return src[start:end]


def main():
    if not os.path.exists(SCRIPT_PATH):
        print('ForzeOS System.py not found at', SCRIPT_PATH)
        return

    cls_src = extract_class_src(SCRIPT_PATH, 'EnhancedAssistantAI')
    if not cls_src:
        print('Could not extract EnhancedAssistantAI source from file')
        return

    # Prepare a safe globals environment with required names
    g: dict = {}
    logging.basicConfig(level=logging.INFO)
    g['logger'] = logging.getLogger('smoke_test')
    # minimal imports expected by the class
    g['os'] = os
    g['json'] = json
    g['hashlib'] = hashlib
    g['math'] = math
    g['time'] = time
    g['random'] = random
    g['re'] = re

    # Provide ASSISTANT_MEMORY_PATH default used by class signature
    g['ASSISTANT_MEMORY_PATH'] = os.path.join(os.path.dirname(SCRIPT_PATH), 'assistant_memory_large.json')

    try:
        exec(cls_src, g)
    except Exception as e:
        print('Failed to exec class source:', e)
        return

    AIClass = g.get('EnhancedAssistantAI')
    if AIClass is None:
        print('EnhancedAssistantAI not found after exec')
        return

    mem_path = g['ASSISTANT_MEMORY_PATH']
    a = AIClass(memory_path=mem_path, session_size=80)
    qs = [
        'merhaba',
        'nasılsın',
        'film öner',
        'kod öğrenmek istiyorum',
        'müzik aç'
    ]
    for q in qs:
        print('Q:', q)
        try:
            r = a.reply(q)
        except Exception as e:
            r = f'ERROR: {e}'
        print('A:', r)
        print('---')


if __name__ == '__main__':
    main()
