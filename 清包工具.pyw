from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'tools'/'fast-sale'))
from launch_toolbox import launch
launch()
