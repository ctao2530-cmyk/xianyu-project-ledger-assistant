import subprocess
import sys


def test_python_child_inherits_sensitive_file_and_network_denial():
    result=subprocess.run([sys.executable,'-c',"""
from pathlib import Path
from backend.app.config import get_settings
import socket
settings=get_settings()
blocked=[]
for operation in (lambda:Path('.env').read_bytes(),lambda:socket.create_connection(('127.0.0.1',8877))):
    try: operation()
    except PermissionError: blocked.append(True)
assert len(blocked)==2
print('child guards active')
"""],capture_output=True,text=True,check=True)
    assert result.stdout.strip()=='child guards active'
