"""Local UI stderr/stdout capture, without environment or credential dumps."""
from datetime import datetime
import os
from pathlib import Path
import sys
import traceback


def run_logged(path,callback):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    previous=(sys.stdout,sys.stderr)
    with path.open('a',encoding='utf8',buffering=1) as stream:
        sys.stdout=sys.stderr=stream
        try:
            print('\n[%s] UI start pid=%s python=%s' % (datetime.now().astimezone().isoformat(),os.getpid(),sys.version.split()[0]))
            return callback()
        except Exception:
            traceback.print_exc();raise
        finally:
            print('[%s] UI end' % datetime.now().astimezone().isoformat())
            sys.stdout,sys.stderr=previous
