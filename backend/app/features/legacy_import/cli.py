import argparse,json
from datetime import datetime
from pathlib import Path
def build_parser()->argparse.ArgumentParser:
    p=argparse.ArgumentParser(prog='da-legacy-import'); p.add_argument('--source-root',required=True); p.add_argument('--effective-at',required=True); p.add_argument('--portfolio-id',required=True); p.add_argument('--imports-root',default='data/imports'); return p
