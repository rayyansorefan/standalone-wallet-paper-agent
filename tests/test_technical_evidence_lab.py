"""No-fill TA evidence laboratory: provenance, cost, gaps, fixed trials and isolation."""
import copy
import datetime as dt
import json
import unittest

from agent import technical_evidence_lab as lab

NOW=dt.datetime(2026,10,18,15,0,tzinfo=dt.timezone.utc)


def bars(now=NOW, count=39, pool='POOL1', mint='MINT1', interval=5):
    out=[]
    for i in range(count):
        t=now-dt.timedelta(minutes=(count-i-1)*interval)
        # Trending with alternating pullbacks; indicators are market observations,
        # not synthetic realized account trades.
        price=1+0.0015*i+(0.002 if i%4==0 else -0.001 if i%4==1 else 0.)
        out.append(dict(at=t.isoformat(),pool=pool,mint=mint,price_usd=price,
            change_5m_pct=1.,change_1h_pct=5.,
            volume_1h_usd=50000,volume_24h_usd=600000,
            buys_1h=65,sells_1h=35,liquidity_usd=400000,age_hours=100))
    return out


def state(rows=None, passing=True):
    return dict(paper_only=True,cash_gbp=1990,closed=[{'net_pnl_gbp':-1}],
                positions=[{'token':'held'}],research={'pool_observations':rows if rows is not None else bars()},
                screening=[{'mint':'MINT1','status':'PASS' if passing else 'REJECTED'}])


class TechnicalResearch(unittest.TestCase):
    def test_indicator_inputs_are_past_only_and_regular(self):
        rows=bars()
        out=lab.indicators(lab.price_marks(rows,NOW)['POOL1'],NOW)
        self.assertIsNotNone(out)
        self.assertTrue(0 <= out['rsi14'] <= 100)
        self.assertIn('macd_hist_pct',out)
        # A large observation gap cannot masquerade as regular candles.
        broken=rows[:25]+[dict(r,at=(dt.datetime.fromisoformat(r['at'])+
                      dt.timedelta(hours=2)).isoformat()) for r in rows[25:]]
        self.assertIsNone(lab.indicators(lab.price_marks(broken,NOW).get('POOL1',[]),NOW))
        future=bars(NOW+dt.timedelta(minutes=15))
        self.assertTrue(all(t<=NOW for t,*_ in lab.price_marks(future,NOW).get('POOL1',[])))

    def test_security_failure_never_creates_shadow_sample(self):
        s=state(passing=False)
        lab.advance(s,NOW)
        self.assertEqual(s['research'][lab.KEY]['pending_count'],0)
        self.assertFalse(s['research'][lab.KEY]['automatic_promotion'])

    def test_registered_mark_cannot_change_existing_money_or_policy(self):
        s=state()
        ledger={k:copy.deepcopy(s[k]) for k in ('cash_gbp','closed','positions')}
        b=lab.advance(s,NOW)
        self.assertGreaterEqual(b['pending_count'],1)
        for k in ledger:self.assertEqual(s[k],ledger[k])
        self.assertEqual(b['registered_at'],NOW.isoformat())
        self.assertTrue(all(not r['paper_entry_enabled'] for r in b['reports'].values()))
        self.assertFalse(b['automatic_promotion'])
        self.assertEqual(b['requests_added'],0)
        self.assertEqual(lab.advance(s,NOW)['cycles'],1)

    def test_outcomes_are_future_only_cost_adjusted_and_missing_is_counted(self):
        s=state()
        first=lab.advance(s,NOW)
        selected=first['pending'][0]
        entry=selected['price']
        future=dict(bars()[-1],at=(NOW+dt.timedelta(minutes=5)).isoformat(),
                    price_usd=entry*1.1)
        s['research']['pool_observations'].append(future)
        lab.advance(s,NOW+dt.timedelta(minutes=6))
        pnl=selected['outcomes']['5m']['net_quote_roi_pct']
        self.assertAlmostEqual(pnl,100*(1.1*.99/1.01-1),places=4)
        self.assertNotIn('30m',selected['outcomes'])
        # No future quotes: later horizon becomes explicitly missing, NOT a loss.
        lab.advance(s,NOW+dt.timedelta(minutes=75))
        self.assertEqual(selected['outcomes']['30m']['status'],'MISSING_TIMELY_FRESH_MARK')
        self.assertEqual(selected['outcomes']['60m']['status'],'MISSING_TIMELY_FRESH_MARK')
        reported=s['research'][lab.KEY]['reports']['existing_technical_gate']['30m']
        self.assertEqual(reported['missing'],1)
        self.assertEqual(reported['priced'],0)

    def test_previous_fingerprint_mismatch_freezes_no_restart(self):
        s=state()
        before=lab.advance(s,NOW)
        registration=before['registered_at']
        before['fingerprint']='economic-source-changed'
        lab.advance(s,NOW+dt.timedelta(minutes=5))
        self.assertEqual(before['status'],'FROZEN_CONFIGURATION_MISMATCH')
        self.assertEqual(before['registered_at'],registration)
        self.assertFalse(before['automatic_promotion'])

    def test_no_pool_or_wallet_names_in_published_summary(self):
        s=state()
        b=lab.advance(s,NOW)
        public={k:v for k,v in b.items()
                if k not in ('pending','completed')}
        as_json=json.dumps(public)
        self.assertNotIn('POOL1',as_json)
        self.assertNotIn('MINT1',as_json)
        self.assertNotIn('held',as_json)


if __name__=='__main__':
    unittest.main()
