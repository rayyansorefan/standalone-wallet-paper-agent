"""Paper-only CLI, one genuine market-data cycle or continuous five-minute checks."""
import argparse, json, logging, os, time
from .core import run_cycle
from .dashboard import publish_json

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

def once():
    state=run_cycle()
    publish_json(state,'docs/state.json')
    logging.info('PAPER cycle %s: %s',state.get('last_status'),json.dumps({'equity_gbp':state['snapshots'][-1]['equity_gbp'],'open_positions':len(state['positions']),'closed_trades':len(state['closed'])}))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['once','loop'],default='once',nargs='?')
    args=parser.parse_args()
    if args.mode=='once':once();return
    while True:
        start=time.monotonic()
        try:once()
        except Exception:logging.exception('Cycle failed; no success recorded; retry on next schedule')
        time.sleep(max(5,300-(time.monotonic()-start)))

if __name__=='__main__':main()
