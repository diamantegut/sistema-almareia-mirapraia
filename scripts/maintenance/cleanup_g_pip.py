import shutil
import os
import glob

base_dir = r"G:\Almareia Mirapraia Sistema Producao\.venv\Lib\site-packages"
if not os.path.exists(base_dir) and os.path.exists(r"F:\Sistema Almareia Mirapraia\.venv\Lib\site-packages"):
    base_dir = r"F:\Sistema Almareia Mirapraia\.venv\Lib\site-packages"
targets = glob.glob(os.path.join(base_dir, "pip*"))

for target in targets:
    if os.path.exists(target):
        print(f"Removing {target}...")
        try:
            if os.path.isdir(target):
                shutil.rmtree(target)
            else:
                os.remove(target)
            print("Success.")
        except Exception as e:
            print(f"Error: {e}")

