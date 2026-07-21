import subprocess
import sys
import os
import shutil

def find_python():
    if not getattr(sys, 'frozen', False):
        return sys.executable
    for name in ('python', 'python3'):
        path = shutil.which(name)
        if path:
            return path
    return 'python'

root = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, 'frozen', False) else __file__))
script_dir = os.path.join(root, "tool", "scripts")
gui_path = os.path.join(script_dir, "gui.py")
subprocess.Popen([find_python(), gui_path], cwd=script_dir)
