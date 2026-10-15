"""Infrastructure gate for scheduled paper cycles; trading rules stay in core."""
import datetime as dt
import json
import os
from pathlib import Path

from . import core
from .dashboard import publish_json

MIN_INTERVAL_SECONDS = 240


def should_run(state, current):
    previous = core.parse_time(state.get('last_run'))
    if previous is None:
        raise ValueError('Existing paper account has no valid last_run; refusing to reset it')
    # A persisted interval check also covers triggers straddling a clock slot.
    if (current - previous).total_seconds() < MIN_INTERVAL_SECONDS:
        return False
    execution = state.get('execution') or {}
    return execution.get('slot') != int(current.timestamp()) // 300


def set_output(executed):
    output = os.getenv('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf8') as stream:
            stream.write('executed=' + str(executed).lower() + '\n')


def execute(path=core.STATE, dashboard_path='docs/state.json', current=None, runner=None):
    # Workflow concurrency serializes writers. Its checkout must use latest main
    # so queued or fallback triggers inspect the most recently persisted account.
    if not Path(path).is_file():
        raise FileNotFoundError('Persisted paper account missing; refusing to create a replacement')
    state = core.load(Path(path))
    current = current or dt.datetime.now(core.UTC)
    if not should_run(state, current):
        set_output(False)
        print('SKIPPED_DUPLICATE: a paper observation was already persisted recently')
        return False
    set_output(True)
    state = (runner or core.run_cycle)(path=Path(path))
    state['execution'] = {
        'event': os.getenv('GITHUB_EVENT_NAME', 'local'),
        'scheduler': os.getenv('PAPER_SCHEDULER'),
        'scheduled_at': os.getenv('PAPER_SCHEDULED_AT'),
        'trigger_uid': os.getenv('PAPER_TRIGGER_UID'),
        'run_id': os.getenv('GITHUB_RUN_ID'),
        'run_attempt': os.getenv('GITHUB_RUN_ATTEMPT'),
        'started_at': current.isoformat(timespec='seconds'),
        'slot': int(current.timestamp()) // 300,
    }
    core.save(state, Path(path))
    publish_json(state, dashboard_path)
    print('PAPER_EXECUTION ' + json.dumps({
        **state['execution'], 'completed_cycles': state['completed_cycles'],
        'status': state['last_status'], 'last_data_at': state['last_data_at'],
        'open_positions': len(state['positions']),
    }))
    return True


if __name__ == '__main__':
    execute()
