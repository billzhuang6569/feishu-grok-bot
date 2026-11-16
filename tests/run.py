"""Isolated runner: denies sockets, subprocesses and credential environment.

Only test temporary synthetic state is opened by the application.
"""
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
os.environ.clear()
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))

def deny(*args, **kwargs):
    raise AssertionError('offline_boundary_violation')

def audit(event, args):
    if event in ('socket.__new__', 'socket.connect', 'socket.bind', 'subprocess.Popen', 'os.system'):
        deny()
sys.addaudithook(audit)
socket.create_connection = deny
subprocess.Popen = deny
suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_*.py')
r = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if r.wasSuccessful() else 1)
