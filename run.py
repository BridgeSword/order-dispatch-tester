# -*- coding: utf-8 -*-
"""Entry point: python run.py [--port 5088] [--rds http://<rds-host>:8088] [--data DIR]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from order_tester.server import main
if __name__ == "__main__": main()
