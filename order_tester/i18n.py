# -*- coding: utf-8 -*-
"""String dictionaries: order_tester/i18n/<lang>.json. Default language: zh."""
import json, os
DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n")
LANGS = ("zh", "en")
_cache = {}

def table(lang):
    lang = lang if lang in LANGS else "zh"
    if lang not in _cache:
        with open(os.path.join(DIR, lang + ".json"), encoding="utf-8") as f: _cache[lang] = json.load(f)
    return _cache[lang]

def t(lang, key, **kw):
    s = table(lang).get(key) or table("zh").get(key) or key
    try: return s.format(**kw) if kw else s
    except (KeyError, IndexError, ValueError): return s
