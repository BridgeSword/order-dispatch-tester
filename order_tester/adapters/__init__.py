# -*- coding: utf-8 -*-
"""Dispatcher adapters. Register new adapters in ADAPTERS (name -> class)."""
from .base import DispatcherAdapter
from .rds import RdsAdapter
from .m4 import M4Adapter

ADAPTERS = {"rds": RdsAdapter, "m4": M4Adapter}

def get_adapter(name, base_url, log=None, opts=None):
    cls = ADAPTERS.get(name or "rds")
    if cls is None: raise ValueError("unknown dispatcher adapter: %s" % name)
    return cls(base_url, log, opts) if opts is not None else cls(base_url, log)
