# -*- coding: utf-8 -*-
"""Dispatcher adapters. Register new adapters in ADAPTERS (name -> class)."""
from .base import DispatcherAdapter
from .rds import RdsAdapter

ADAPTERS = {"rds": RdsAdapter}

def get_adapter(name, base_url, log=None):
    cls = ADAPTERS.get(name or "rds")
    if cls is None: raise ValueError("unknown dispatcher adapter: %s" % name)
    return cls(base_url, log)
