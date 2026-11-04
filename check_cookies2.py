import os
import shutil
import sqlite3
import subprocess

appdata = os.environ.get('LOCALAPPDATA', '')
src = os.path.join(appdata, 'Google', 'Chrome', 'User Data', 'Profile 1', 'Network', 'Cookies')
dst = os.path.join(os.getcwd(), 'chrome_cookies.tmp')

# Usar cmd /c copy
subprocess.run(['cmd', '/c', 'copy', '/y', src, dst], capture_output=True)

if os.path.exists(dst):
    conn = sqlite3.connect(dst)
    c = conn.cursor()
    c.execute("SELECT host_key, name FROM cookies WHERE host_key LIKE '%dropi%'")
    rows = c.fetchall()
    print("Dropi cookies en Profile 1:", rows)
    conn.close()
    os.remove(dst)
else:
    print("No se pudo copiar Cookies")
