import sqlite3
import os
import glob
import shutil

appdata = os.environ.get('LOCALAPPDATA', '')
paths = [
    os.path.join(appdata, 'Google', 'Chrome', 'User Data', 'Default', 'Network', 'Cookies'),
    os.path.join(appdata, 'Google', 'Chrome', 'User Data', 'Profile 1', 'Network', 'Cookies'),
    os.path.join(appdata, 'Google', 'Chrome', 'User Data', 'Default', 'Cookies')
]

for p in paths:
    if os.path.exists(p):
        print("Found cookies db at:", p)
        # Copiar a temporal para leer sin lock
        temp_p = p + '.tmp'
        try:
            shutil.copy2(p, temp_p)
            conn = sqlite3.connect(temp_p)
            c = conn.cursor()
            c.execute("SELECT host_key, name FROM cookies WHERE host_key LIKE '%dropi%'")
            rows = c.fetchall()
            print("Dropi cookies encontradas:", rows)
            conn.close()
            os.remove(temp_p)
        except Exception as e:
            print("Error reading db:", e)
