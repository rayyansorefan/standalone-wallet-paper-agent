import datetime as dt
import tempfile
import unittest
from pathlib import Path
from agent import core


class PaperTradingTests(unittest.TestCase):
    def test_state_starts_with_zero_profits_and_paper_only(self):
        s=core.blank_state()
        self.assertTrue(s['paper_only'])
        self.assertEqual(core.equity(s,{}),2000)
        self.assertFalse(s['closed'])

    def test_profitable_copy_and_learning_adjustment(self):
        s=core.blank_state(); w='A'*32; t='TOKEN'
        s['observed'][w]={'count':4,'last_seen':core.now_iso()}
        now=dt.datetime.now(core.UTC)
        event=dict(id='trade_1', wallet=w, token=t, pool_name='TEST', timestamp=now)
        core.maybe_open(s,event,1,now,{t:1})
        self.assertEqual(len(s['positions']),1)
        self.assertEqual(s['cash_gbp'],1989.9)
        core.close_position(s,s['positions'][0],1.5,'test exit')
        self.assertEqual(len(s['closed']),1)
        self.assertGreater(s['closed'][0]['net_pnl_gbp'],0)
        self.assertEqual(s['cash_gbp'],2004.75)
        self.assertGreater(core.wallet_stats(s,w)['shrunk_roi_pct'],0)

    def test_no_empty_evidence_trading(self):
        s=core.blank_state();now=dt.datetime.now(core.UTC)
        core.maybe_open(s,dict(wallet='A'*32, token='x',id='x',pool_name='x',timestamp=now),1,now,{'x':1})
        self.assertEqual(s['positions'],[])
        self.assertEqual(s['decisions'][-1]['action'],'SKIP')

    def test_first_scan_records_but_does_not_copy_past_signals(self):
        now=dt.datetime.now(core.UTC)
        stamp=(now-dt.timedelta(seconds=10)).isoformat().replace('+00:00','Z')
        pool=dict(id='solana_'+ 'B'*32, relationships={'base_token':{'data':{'id':'solana_'+ 'C'*32}}}, attributes=dict(address='B'*32, name='AAA/SOL',reserve_in_usd='200000',volume_usd={'h24':'500000'},base_token_price_usd='1',pool_created_at=(now-dt.timedelta(days=5)).isoformat()))
        trade=dict(id='tx_1',attributes=dict(tx_hash='tx_1',tx_from_address='A'*32,kind='buy',block_timestamp=stamp,volume_in_usd='200',price_to_in_usd='1'))
        def fetch(path, params=None):
            return dict(data=[pool] if 'trending_pools' in path else [trade])
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'state.json'
            s=core.run_cycle(fetch=fetch,path=p,screen_token=lambda _: True)
            self.assertEqual(s['last_status'],'BOOTSTRAPPED_NO_TRADES')
            self.assertEqual(len(s['positions']),0)
            self.assertEqual(s['observed']['A'*32]['count'],1)
            s2=core.run_cycle(fetch=fetch,path=p,screen_token=lambda _: True)
            self.assertEqual(s2['observed']['A'*32]['count'],1)
            self.assertEqual(s2['positions'],[])

    def test_canonical_mint_duplicate_pool_is_not_second_paper_exposure(self):
        from unittest import mock
        state=core.blank_state()
        now=dt.datetime.now(core.UTC)
        a,b='A'*32,'B'*32
        first,second='P'*32,'Q'*32
        mint='M'*32
        state['observed'][a]={'count':3,'last_seen':core.now_iso()}
        state['observed'][b]={'count':3,'last_seen':core.now_iso()}
        first_event=dict(id='first',wallet=a,token=first,pool_name='ONE',timestamp=now)
        second_event=dict(id='second',wallet=b,token=second,pool_name='TWO',timestamp=now)
        core.maybe_open(state,first_event,1,now,{first:1})
        self.assertEqual(len(state['positions']),1)
        state['positions'][0]['mint']=mint
        state['research']={'decision_v1':{'pool_mints':{first:mint,second:mint}}}
        existing_cash=state['cash_gbp']
        with mock.patch('agent.decision.entry_assessment',return_value=None):
            core.maybe_open(state,second_event,1,now,{first:1,second:1})
        self.assertEqual(len(state['positions']),1)
        self.assertEqual(state['cash_gbp'],existing_cash)
        self.assertEqual(state['decisions'][-1]['action'],'SKIP')
        self.assertIn('canonical mint',state['decisions'][-1]['reason'])

    def test_missing_price_never_closes_at_guess(self):
        s=core.blank_state();w='A'*32;now=dt.datetime.now(core.UTC)
        s['observed'][w]={'count':3,'last_seen':core.now_iso()}
        core.maybe_open(s,dict(wallet=w,token='x',id='x',pool_name='x',timestamp=now),1,now,{'x':1})
        core.maintain_positions(s,{},now+dt.timedelta(hours=8))
        self.assertEqual(len(s['positions']),1)

if __name__ == '__main__': unittest.main()
