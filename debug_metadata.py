import sys
import os
import clr
clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import MessageBox

# Add script dir to path
script_dir = r"c:\Users\arthu\AppData\Local\CODESYS\ScriptDir\cds-text-sync"
if script_dir not in sys.path:
    sys.path.append(script_dir)

from codesys_utils import load_base_dir, resolve_projects

def debug_sync():
    base_dir, error = load_base_dir()
    if error:
        print("Base Dir Error: " + str(error))
        return
    
    print("Base Dir: " + str(base_dir))
    if os.path.exists(base_dir):
        print("Contents of " + base_dir + ":")
        for f in os.listdir(base_dir):
            if f.startswith("_"):
                print("  " + f)
                if f == "_metadata.csv":
                    print("  Metadata found!")
    else:
        print("Base Dir DOES NOT EXIST")

if __name__ == "__main__":
    debug_sync()
