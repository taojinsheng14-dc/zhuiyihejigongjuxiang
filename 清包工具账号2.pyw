from pathlib import Path
import sys,runpy
sys.argv += ['--instance','2']
runpy.run_path(str(Path(__file__).resolve().parent/'tools'/'fast-sale'/'mixed_sale_gui.py'),run_name='__main__')
