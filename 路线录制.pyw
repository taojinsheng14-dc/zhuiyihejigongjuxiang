from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).resolve().parent/'tools'/'fast-sale'/'route_recorder_gui.py'),run_name='__main__')
