import copy
import datetime as dt
import unittest
from unittest.mock import patch
from agent import core, decision, news

NOW=dt.datetime(2026,10,16,19,0,tzinfo=dt.timezone.utc)


def fixture():
    s=core.blank_state();s['observed']['wallet']={'count':4}
    s['research']={'news_v1':{'status':'OK','checked_at':NOW.isoformat(),'risk_off':False}}
    m=dict(pool='pool',mint='mint',change_5m_pct=1,change_1h_pct=4,
           volume_1h_usd=10000,volume_24h_usd=200000,buys_1h=100,sells_1h=80)
    return s,m


def trade(i,pnl=-1,minutes=10,token='pool'):
    return dict(wallet='old'+str(i),token=token,signal_id=str(i),net_pnl_gbp=pnl,
                roi_pct=pnl*10,exit_at=(NOW-dt.timedelta(minutes=minutes)).isoformat())


class Decisions(unittest.TestCase):
    def test_cross_wallet_loss_reentry_block_and_expiry(self):
        s,m=fixture();s['closed']=[trade(1)]
        decision.prepare(s,[m],NOW)
        ev=dict(wallet='wallet',token='pool',id='new',pool_name='P',timestamp=NOW)
        core.maybe_open(s,ev,1,NOW,{'pool':1})
        self.assertEqual(s['positions'],[])
        self.assertIn('token-wide',s['decisions'][-1]['reason'])
        self.assertFalse(decision.history(s,'pool',NOW+dt.timedelta(hours=3))['cooldown_until'] is None)
        self.assertLess(decision.stamp(decision.history(s,'pool',NOW+dt.timedelta(hours=3))['cooldown_until']),NOW+dt.timedelta(hours=3))

    def test_repeated_losses_block_even_after_different_wallet_wins(self):
        s,m=fixture();s['closed']=[trade(i,minutes=300+i) for i in range(3)]+[trade(4,pnl=.2,minutes=240)]
        self.assertFalse(decision.prepare(s,[m],NOW)['assessments']['pool']['allowed'])

    def test_token_mint_alias_blocks_different_pool(self):
        s,m=fixture();s['closed']=[trade(1,token='other')]
        decision.remember(s,[dict(pool='other',mint='mint')],NOW)
        self.assertFalse(decision.prepare(s,[m],NOW)['assessments']['pool']['allowed'])

    def test_same_cycle_close_invalidates_prepared_allow(self):
        s,m=fixture();decision.prepare(s,[m],NOW)
        s['closed'].append(trade(1,minutes=0))
        self.assertFalse(decision.entry_assessment(s,dict(token='pool'),NOW)['allowed'])

    def test_positive_evidence_ranks_without_raising_unproven_exposure(self):
        s,m=fixture();s['closed']=[trade(1,pnl=1,minutes=240),trade(2,pnl=1,minutes=200)]
        a=decision.prepare(s,[m],NOW)['assessments']['pool']
        self.assertTrue(a['allowed']);self.assertGreater(a['selection_score'],0)
        ev=dict(wallet='wallet',token='pool',id='new',pool_name='P',timestamp=NOW)
        core.maybe_open(s,ev,1,NOW,{'pool':1})
        self.assertEqual(s['positions'][0]['notional_gbp'],10)
        self.assertIsNotNone(s['positions'][0]['entry_assessment'])

    def test_missing_fading_overheated_or_sell_dominated_technicals_block(self):
        for k,v in [('change_1h_pct',-10),('change_5m_pct',0),('change_5m_pct',13),
                    ('volume_1h_usd',1),('buys_1h',1),('change_1h_pct',None)]:
            s,m=fixture();m[k]=v
            self.assertFalse(decision.prepare(s,[m],NOW)['assessments']['pool']['allowed'])

    def test_news_stale_missing_or_adverse_blocks(self):
        for update in [dict(status='UNAVAILABLE'),dict(risk_off=True),dict(checked_at=(NOW-dt.timedelta(hours=1)).isoformat())]:
            s,m=fixture();s['research']['news_v1'].update(update)
            self.assertFalse(decision.prepare(s,[m],NOW)['assessments']['pool']['allowed'])

    def test_future_and_old_closures_do_not_influence(self):
        s,m=fixture();s['closed']=[trade(1,minutes=-1),trade(2,minutes=1500)]
        self.assertEqual(decision.prepare(s,[m],NOW)['assessments']['pool']['history']['closed'],0)

    def test_forward_no_backfill_or_repeated_wallet_pseudoreplication(self):
        s,m=fixture();decision.prepare(s,[m],NOW)
        ev=dict(wallet='wallet',token='pool',id='new',kind='buy',timestamp=NOW)
        decision.observe_forward(s,[ev,ev],{'pool':1},NOW)
        d=s['research']['decision_v1'];self.assertEqual(len(d['forward_pending']),1)
        decision.observe_forward(s,[],{'pool':1.1},NOW+dt.timedelta(minutes=5))
        self.assertAlmostEqual(d['forward_pending'][0]['outcomes']['5m']['net_quote_roi_pct'],7.8218)
        self.assertEqual(d['forward_summary']['accepted']['5m']['priced'],1)
        self.assertEqual(d['forward_summary']['accepted']['30m']['priced'],0)
        self.assertEqual(d['forward_summary']['accepted']['30m']['missing'],0)
        self.assertEqual(d['forward_summary']['accepted']['30m']['pending'],1)
        decision.observe_forward(s,[],{'pool':2},NOW+dt.timedelta(minutes=75))
        self.assertEqual(d['forward_outcomes'][0]['outcomes']['60m']['status'],'MISSING_FRESH_QUOTE')
        self.assertEqual(d['forward_summary']['accepted']['60m']['priced'],0)

    def test_news_failure_cached_and_preserves_account(self):
        s,_=fixture();before=copy.deepcopy(s)
        with patch.object(news,'download',side_effect=TimeoutError):
            n=news.refresh(s,NOW+dt.timedelta(minutes=16),fetch=news.download)
        self.assertEqual(n['status'],'UNAVAILABLE');self.assertEqual(s['cash_gbp'],before['cash_gbp'])
        with patch.object(news,'download',side_effect=AssertionError('must cache')):
            news.refresh(s,NOW+dt.timedelta(minutes=17),fetch=news.download)

    def test_news_dates_relevance_and_resolved_incidents(self):
        def rss(title,date='Fri, 16 Oct 2026 18:00:00 +0000'):
            return f'<rss><channel><item><title>{title}</title><link>https://example.org/a</link><pubDate>{date}</pubDate></item></channel></rss>'.encode()
        self.assertTrue(news.parse(rss('Solana exploit reported'),'coindesk',NOW)[0]['risk_flag'])
        self.assertFalse(news.parse(rss('Solana outage resolved'),'solana_status',NOW)[0]['risk_flag'])
        with self.assertRaises(ValueError):
            news.parse(rss('Solana hack','Fri, 16 Oct 2026 20:00:00 +0000'),'coindesk',NOW)
        self.assertFalse(news.parse(rss('Unrelated small token hacked'),'coindesk',NOW))

    def test_stale_news_feed_is_unavailable_not_a_clean_bill_of_health(self):
        payload=b'<rss><channel><item><title>Crypto news</title><pubDate>Wed, 14 Oct 2026 18:00:00 +0000</pubDate></item></channel></rss>'
        with self.assertRaises(ValueError):news.parse(payload,'coindesk',NOW)

    def test_partial_news_reduces_size_without_disabling_existing_exits(self):
        s,m=fixture();s['research']['news_v1']['status']='PARTIAL'
        decision.prepare(s,[m],NOW)
        ev=dict(wallet='wallet',token='pool',id='new',pool_name='P',timestamp=NOW)
        core.maybe_open(s,ev,1,NOW,{'pool':1})
        self.assertEqual(s['positions'][0]['notional_gbp'],5)
        core.maintain_positions(s,{'pool':.8},NOW)
        self.assertFalse(s['positions']);self.assertEqual(len(s['closed']),1)


    def test_conflicting_sells_do_not_create_forward_buy_cohort(self):
        s,m=fixture();decision.prepare(s,[m],NOW)
        ev=dict(wallet='wallet',token='pool',id='new',kind='buy',timestamp=NOW)
        decision.observe_forward(s,[ev,{**ev,'kind':'sell'}],{'pool':1},NOW)
        self.assertFalse(s['research']['decision_v1']['forward_pending'])

    def test_no_retrospective_technical_reinforcement_cohort(self):
        from agent.adaptive import feature_buckets
        keys=feature_buckets(dict(change_5m_pct=1,change_1h_pct=4))
        self.assertFalse(any(k.startswith('technical:') for k in keys))


class FullPolicyCycle(unittest.TestCase):
    def run_cycle(self, sell=False):
        import tempfile
        from pathlib import Path
        now=dt.datetime.now(core.UTC)
        s=core.blank_state();s['last_run']=(now-dt.timedelta(minutes=5)).isoformat()
        w,p,m='A'*32,'B'*32,'C'*32
        s['observed'][w]={'count':4}
        s['research']={'news_v1':{'status':'OK','checked_at':now.isoformat(),'risk_off':False}}
        raw={'id':'solana_'+p,'relationships':{'base_token':{'data':{'id':'solana_'+m}}},
             'attributes':dict(address=p,name='TEST/SOL',reserve_in_usd=400000,
             volume_usd={'h24':400000,'h1':100000},price_change_percentage={'h24':5,'h1':2,'m5':1},
             transactions={'h1':{'buys':100,'sells':60}},base_token_price_usd=1,
             pool_created_at=(now-dt.timedelta(days=5)).isoformat())}
        rows=[{'attributes':dict(tx_hash='buy',tx_from_address=w,kind='buy',
              block_timestamp=(now-dt.timedelta(seconds=20)).isoformat(),volume_in_usd=200)}]
        if sell:
            s['cash_gbp']=1989.9
            s['positions']=[dict(wallet='D'*32,token=p,pool_name='TEST/SOL',opened_at=(now-dt.timedelta(hours=1)).isoformat(),
                entry_price_usd=1,last_mark_price_usd=1,notional_gbp=10,cost_gbp=10.1,signal_id='previous')]
            rows.append({'attributes':dict(tx_hash='sell',tx_from_address='D'*32,kind='sell',
                block_timestamp=(now-dt.timedelta(seconds=5)).isoformat(),volume_in_usd=200)})
        def fetch(path,params=None):return {'data':[raw] if 'trending_pools' in path else rows}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'s.json';core.save(s,path)
            result=core.run_cycle(fetch=fetch,path=path,screen_token=lambda _:True)
            self.assertEqual(result,core.load(path))
        self.assertEqual(result['starting_gbp'],2000)
        self.assertEqual(result['initialized_at'],s['initialized_at'])
        return result

    def test_full_cycle_allows_informed_entry_and_captures_evidence(self):
        s=self.run_cycle()
        self.assertEqual(len(s['positions']),1)
        self.assertTrue(s['positions'][0]['entry_assessment']['allowed'])
        self.assertEqual(s['positions'][0]['notional_gbp'],10)
        self.assertEqual(len(s['research']['decision_v1']['forward_pending']),1)

    def test_sell_precedes_earlier_cross_wallet_buy_then_cooldown_blocks(self):
        s=self.run_cycle(sell=True)
        self.assertFalse(s['positions']);self.assertEqual(len(s['closed']),1)
        self.assertTrue(any(x['action']=='SKIP_POLICY' and 'token-wide' in x['reason'] for x in s['decisions']))
        self.assertAlmostEqual(s['cash_gbp'],1999.8)
