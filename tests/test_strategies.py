import copy
import datetime as dt
import unittest
from unittest import mock
from agent import strategies as s

NOW=dt.datetime(2026,10,16,21,0,tzinfo=s.UTC)


def fixture():
    state={'cash_gbp':1234,'positions':[{'original':True}],'closed':[{'old':True}],
           'research':{'news_v1':{'checked_at':NOW.isoformat(),'sources':{'coindesk':{'status':'OK'}},'risk_off':False}}}
    q={'X':dict(bid=99.99,ask=100.01,mid=100.,relativeFundingRate=.00001)}
    f=dict(close=100,previous=99.9,atr=.3,ema_fast=99.9,ema_slow=99.5,
           r1h=.02,r15m=.004,volume_ratio=1.5,fade_volume_ratio=1,
           pump=.01,drawdown=0,peak_age=0,lower_closes=False)
    return state,q,{'X':f}


def step(state,q,f,minutes=0):
    now=NOW+dt.timedelta(minutes=minutes)
    state['research']['news_v1']['checked_at']=now.isoformat()
    return s.advance(state,now,q,f,set(q))


class Strategies(unittest.TestCase):
    def test_long_short_and_fade_are_distinct_qualified_setups(self):
        _,_,fs=fixture();f=fs['X']
        self.assertEqual(s.setups(f)[0][0],'momentum_long')
        f.update(ema_fast=99,ema_slow=100,r1h=-.02,r15m=-.004)
        self.assertEqual(s.setups(f)[0][0],'momentum_short')
        f.update(volume_ratio=.5,pump=.06,peak_age=3,drawdown=2,fade_volume_ratio=.4,lower_closes=True)
        self.assertEqual(s.setups(f)[0][0],'pump_fade')
        f['r15m']=.002
        self.assertEqual(s.setups(f),[])

    def test_selected_trade_identity_is_not_stale_indicators_loop_variable(self):
        # White paper D01 reproduction: best X selected while Y is iterated
        # last, and the old code incorrectly labelled Y as ENTERED.
        state,q,indicators=fixture()
        q['Y']=dict(bid=99.99,ask=100.01,mid=100.,relativeFundingRate=.00001)
        weak=copy.deepcopy(indicators['X'])
        weak.update(r1h=.0065,r15m=.0011,volume_ratio=1.31)
        indicators['Y']=weak
        book=step(state,q,indicators)
        self.assertEqual(book['position']['symbol'],'X')
        entered=[r for r in book['forward_signals'] if r['decision']=='ENTERED']
        self.assertEqual(len(entered),1)
        self.assertEqual((entered[0]['symbol'],entered[0]['setup']),
                         ('X','momentum_long'))
        self.assertEqual(entered[0]['entry_trade_id'],
                         book['position']['entry_trade_id'])
        rejected=[r for r in book['forward_signals'] if r['symbol']=='Y']
        self.assertTrue(rejected)
        self.assertTrue(all(r['decision']=='OBSERVED_NOT_ENTERED' for r in rejected))
        self.assertFalse(any(r.get('entry_trade_id') for r in rejected))

    def test_legacy_label_conflicts_remain_original_and_are_excluded_from_learning(self):
        from agent.strategy_lab import reconcile_forward_entries,missed_winners
        state,q,f=fixture()
        b=s.initialize(state,NOW)
        # Existing historical positions are authoritative evidence for this
        # audit, but original forward labels must never be rewritten.
        b['closed']=[{'opened_at':NOW.isoformat(),'symbol':'X',
                      'setup':'momentum_long'}]
        b['forward_signals']=[
            {'at':NOW.isoformat(),'symbol':'X','setup':'momentum_long',
             'decision':'OBSERVED_NOT_ENTERED','policy_revision':'v4.1',
             'outcomes':{'60m':{'net_roi_pct':3.}}},
            {'at':NOW.isoformat(),'symbol':'Y','setup':'momentum_long',
             'decision':'ENTERED','outcomes':{'60m':{'net_roi_pct':2.}}}]
        self.assertEqual(reconcile_forward_entries(b),2)
        self.assertEqual(b['forward_identity_audit']['historical_conflicts'],2)
        self.assertEqual(b['forward_signals'][0]['decision'],'OBSERVED_NOT_ENTERED')
        self.assertEqual(b['forward_signals'][1]['decision'],'ENTERED')
        self.assertTrue(all(r['learning_excluded'] for r in b['forward_signals']))
        self.assertEqual(missed_winners(b['forward_signals'])['evaluated'],0)

    def test_original_account_untouched_and_one_position_only(self):
        state,q,f=fixture();original=copy.deepcopy(state)
        b=step(state,q,f);step(state,q,f,5)
        for k in ('cash_gbp','positions','closed'):
            self.assertEqual(state[k],original[k])
        self.assertEqual(b['entries_today'],1)
        self.assertLessEqual(b['position']['entry_notional'],500)

    def test_flat_roundtrip_loses_costs_and_cash_reconciles(self):
        state,q,f=fixture();b=step(state,q,f)
        b['position']['stop']=101
        step(state,q,f,5)
        self.assertIsNone(b['position']);self.assertLess(b['closed'][0]['net_usd'],0)
        self.assertAlmostEqual(b['cash_usd'],2000+b['closed'][0]['net_usd'])
        self.assertEqual(b['entries_today'],1)

    def test_short_profit_and_costs_reconcile(self):
        state,q,f=fixture();f['X'].update(ema_fast=99,ema_slow=100,r1h=-.02,r15m=-.004)
        b=step(state,q,f);self.assertEqual(b['position']['direction'],-1)
        q['X'].update(bid=94.99,ask=95.01,mid=95)
        f['X'].update(ema_fast=101,ema_slow=100)
        step(state,q,f,20)
        self.assertGreater(b['closed'][0]['net_usd'],0)
        self.assertAlmostEqual(b['cash_usd'],2000+b['closed'][0]['net_usd'])
        self.assertLess(b['closed'][0]['stress_net_usd'],b['closed'][0]['net_usd'])

    def test_stop_gaps_fill_at_observed_market_not_old_stop(self):
        state,q,f=fixture();b=step(state,q,f);stop=b['position']['stop']
        q['X'].update(bid=89.99,ask=90.01,mid=90)
        step(state,q,f,5)
        self.assertLess(b['closed'][0]['exit_price'],stop)
        self.assertLess(b['closed'][0]['net_usd'],-b['closed'][0]['risk_usd'])

    def test_winner_add_once_and_cash_reconciles_after_exit(self):
        state,q,f=fixture();b=step(state,q,f)
        q['X'].update(bid=102.99,ask=103.01,mid=103)
        step(state,q,f,5);p=b['position'];self.assertTrue(p['added'])
        units=p['units'];step(state,q,f,10);self.assertEqual(p['units'],units)
        self.assertLessEqual(p['units']*103,b['equity_usd']*.38)
        q['X'].update(bid=104.99,ask=105.01,mid=105)
        f['X'].update(ema_fast=99,ema_slow=100)
        step(state,q,f,20)
        self.assertAlmostEqual(b['cash_usd'],2000+b['closed'][0]['net_usd'])

    def test_no_add_to_loser_and_missing_quote_never_fabricates_exit(self):
        state,q,f=fixture();b=step(state,q,f)
        q['X'].update(bid=99.89,ask=99.91,mid=99.9)
        step(state,q,f,5);self.assertFalse(b['position']['added'])
        step(state,{},f,10);self.assertIsNotNone(b['position'])
        self.assertEqual(b['events'][-1]['action'],'HOLD_UNPRICED')

    def test_news_veto_blocks_entries_and_adds_but_not_exits(self):
        state,q,f=fixture();state['research']['news_v1']['risk_off']=True
        self.assertIsNone(step(state,q,f)['position'])
        state['research']['news_v1']['risk_off']=False;b=step(state,q,f,5)
        state['research']['news_v1']['risk_off']=True;q['X'].update(bid=89,ask=90,mid=89.5)
        step(state,q,f,10);self.assertEqual(len(b['closed']),1)

    def test_repeated_losses_pause_setup_across_symbols(self):
        state,q,f=fixture();b=s.initialize(state,NOW)
        b['closed']=[dict(setup='momentum_long',symbol='OTHER',exit_at=(NOW-dt.timedelta(minutes=i+10)).isoformat(),net_usd=-1,risk_usd=5,stress_net_usd=-2) for i in (30,20,10)]
        self.assertTrue(s.feedback(b,'momentum_long','X',NOW)['paused'])
        self.assertIsNone(step(state,q,f)['position'])

    def test_loss_cooldown_cannot_be_bypassed_by_another_setup(self):
        state,_,_=fixture();b=s.initialize(state,NOW)
        b['closed']=[dict(setup='momentum_long',symbol='X',exit_at=(NOW-dt.timedelta(minutes=20)).isoformat(),net_usd=-1,risk_usd=5,stress_net_usd=-2)]
        self.assertFalse(s.feedback(b,'pump_fade','X',NOW)['allowed'])
        self.assertTrue(s.feedback(b,'pump_fade','X',NOW+dt.timedelta(hours=3))['allowed'])

    def test_reinforcement_needs_separate_future_validation_and_time(self):
        state,_,_=fixture();b=s.initialize(state,NOW-dt.timedelta(days=20))
        rows=[dict(setup='momentum_long',symbol=str(i%3),exit_at=(NOW-dt.timedelta(hours=40-i)).isoformat(),net_usd=2,risk_usd=5,stress_net_usd=1) for i in range(30)]
        b['closed']=rows[:20];self.assertFalse(s.feedback(b,'momentum_long','X',NOW)['reinforced'])
        b['closed']=rows
        report=s.feedback(b,'momentum_long','X',NOW)
        self.assertTrue(report['provisional_positive'])
        self.assertFalse(report['reinforced'])
        self.assertEqual(report['risk_multiplier'],1.)
        self.assertEqual(report['reinforcement_status'],'AWAITING_SHARED_FROZEN_OOS_AND_BASELINE')
        b['closed'][-1]['stress_net_usd']=-100
        self.assertFalse(s.feedback(b,'momentum_long','X',NOW)['reinforced'])

    def test_futures_candidate_order_does_not_grant_automatic_positive_sizing(self):
        state,q,f=fixture()
        b=s.initialize(state,NOW-dt.timedelta(days=30))
        b['closed']=[dict(setup='pump_fade',symbol='SY'+str(i%4),
            exit_at=(NOW-dt.timedelta(days=12)+dt.timedelta(hours=i)).isoformat(),
            net_usd=2.,risk_usd=5.,stress_net_usd=1.)
            for i in range(30)]
        report=s.feedback(b,'pump_fade','X',NOW)
        self.assertTrue(report['provisional_positive'])
        self.assertFalse(report['reinforced'])
        self.assertEqual(report['risk_multiplier'],1.)

    def test_completed_candles_only_no_gaps_or_future_data(self):
        bars=[dict(time=int((NOW.timestamp()-(100-i)*300)*1000),open=100,high=102,low=99,close=101,volume=10) for i in range(100)]
        f=s.features(bars+[dict(time=NOW.timestamp()*1000,open=100,high=900,low=1,close=800,volume=1000)],NOW)
        self.assertEqual(f['close'],101)
        with self.assertRaises(ValueError):s.features(bars[:90],NOW)
        with self.assertRaises(ValueError):s.features(bars[:70]+bars[71:],NOW)

    def test_futures_deep_candle_scan_rotates_without_exceeding_free_budget(self):
        b={}
        names=['PF_T'+str(i)+'USD' for i in range(18)]
        ticks=[dict(symbol=name,bid=99.99,ask=100.01,tag='perpetual',
                    volumeQuote=2_000_000,relativeFundingRate=.0001,
                    change24h=100-i) for i,name in enumerate(names)]
        seen=[]
        def fetch(path):
            if path=='/derivatives/api/v3/tickers':
                return dict(result='success',serverTime=NOW.isoformat(),tickers=ticks)
            if '/api/charts/v1/trade/' in path:
                seen.append(path.split('/')[5])
                return {'candles':[]}
            self.fail(path)
        with mock.patch.object(s,'features',return_value={'close':100}):
            for _ in range(4):
                start=len(seen)
                quotes,indicators,eligible=s.market(b,NOW,fetch)
                scanned=seen[start:]
                self.assertEqual(len(scanned),6)
                self.assertIn(names[0],scanned)
                self.assertIn(names[1],scanned)
                self.assertEqual(b['feed']['bulk_tickers_evaluated'],18)
                self.assertEqual(b['feed']['requests'],7)
                self.assertEqual(len(indicators),6)
        self.assertEqual(len(set(seen)),18)
        self.assertEqual(len(eligible),18)

    def test_held_experiment_symbols_preempt_rotation_without_more_requests(self):
        names=['PF_T'+str(i)+'USD' for i in range(18)]
        ticks=[dict(symbol=name,bid=99.99,ask=100.01,tag='perpetual',
                    volumeQuote=2_000_000,relativeFundingRate=.0001,
                    change24h=100-i) for i,name in enumerate(names)]
        book={'position':{'symbol':names[10]}}
        seen=[]
        def fetch(path):
            if path=='/derivatives/api/v3/tickers':
                return dict(result='success',serverTime=NOW.isoformat(),tickers=ticks)
            if '/api/charts/v1/trade/' in path:
                seen.append(path.split('/')[5])
                return {'candles':[]}
            self.fail(path)
        with mock.patch.object(s,'features',return_value={'close':100}):
            _,indicators,_=s.market(
                book,NOW,fetch,priority_symbols=[names[11],names[12],names[11]])
        self.assertEqual(len(seen),6)
        self.assertEqual(len(set(seen)),6)
        for symbol in (names[10],names[11],names[12],names[0],names[1]):
            self.assertIn(symbol,seen)
        self.assertEqual(book['feed']['requests'],7)
        self.assertEqual(book['feed']['priority_held_symbols'],3)
        self.assertEqual(book['feed']['priority_held_scanned'],3)
        self.assertEqual(len(indicators),6)

    def test_feed_failure_is_visible_without_touching_account(self):
        state,_,_=fixture();s.run(state,NOW,fetch=lambda _: (_ for _ in ()).throw(TimeoutError('timeout')))
        self.assertEqual(state['research']['strategies_v1']['status'],'DATA_UNAVAILABLE')
        self.assertEqual(state['cash_gbp'],1234)


if __name__=='__main__':unittest.main()
