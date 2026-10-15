"""Publish a minimal, public and read-only state for the JS visualiser."""
import json
from pathlib import Path


def publish_json(state, path='docs/state.json'):
    dst=Path(path)
    dst.parent.mkdir(parents=True,exist_ok=True)
    # Public repository: wallet sender addresses and trading history are visible.
    # The full deduplication list is unnecessary for the chart and is excluded.
    public={k:v for k,v in state.items() if k not in {'seen_trades'}}
    tmp=dst.with_suffix('.tmp')
    tmp.write_text(json.dumps(public,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf8')
    tmp.replace(dst)


def html_dashboard(s,path):
    """Legacy static-report helper, retained for backwards-compatible tests."""
    import html
    def esc(x):return html.escape(str(x),quote=True)
    html_body='<h1>Standalone Wallet Paper Research</h1><p>PAPER ONLY</p>'
    for d in s.get('decisions',[]):
        html_body+='<p>'+esc(d.get('action'))+' '+esc(d.get('reason'))+'</p>'
    Path(path).write_text('<!doctype html><html><meta charset="utf-8">'+html_body+'</html>',encoding='utf8')
