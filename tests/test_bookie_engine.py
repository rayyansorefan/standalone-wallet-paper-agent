import importlib.util
import datetime as dt
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location("bookie",Path(__file__).resolve().parents[1]/"research"/"bookie"/"engine.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class BookieEngineTests(unittest.TestCase):
    def fixture(self,with_bet365=True):
        now=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(hours=12)).isoformat()
        books=[]
        for i in range(3):
            books.append({"key":"source"+str(i),"title":"Reference "+str(i),"last_update":module.stamp(),
                          "markets":[{"key":"h2h","outcomes":[{"name":"Home","price":1.53+i*.01},{"name":"Away","price":2.6+i*.02}]}]})
        if with_bet365:
            books.append({"key":"bet365","title":"bet365","last_update":module.stamp(),
                          "markets":[{"key":"h2h","outcomes":[{"name":"Home","price":2.2},{"name":"Away","price":1.7}]}]})
        return {"id":"synthetic-event","sport_key":"basketball_nba","commence_time":now,
                "home_team":"Home","away_team":"Away","bookmakers":books}
    def test_no_bookmaker_quote_is_never_bet(self):
        hist=[];rows=module.event_rows(self.fixture(False),hist)
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r["status"]=="WATCH" and r["book_odds"] is None for r in rows))
    def test_genuine_quote_requires_conservative_edge(self):
        rows=module.event_rows(self.fixture(True),[])
        home=next(r for r in rows if r["selection"]=="Home")
        self.assertEqual(home["status"],"BET_CANDIDATE")
        self.assertGreater(home["conservative_ev"],.02)
        self.assertGreater(home["source_count"],2)
    def test_result_scoring_uses_final_only(self):
        h=[{"id":"test","event_id":"a","selection":"Home","settled":None}]
        module.score_previous(h,module.settlement([{"id":"a","completed":False,"home_team":"Home","away_team":"Away","scores":[{"name":"Home","score":"4"},{"name":"Away","score":"2"}]}]))
        self.assertIsNone(h[0]["settled"])
        module.score_previous(h,module.settlement([{"id":"a","completed":True,"home_team":"Home","away_team":"Away","scores":[{"name":"Home","score":"4"},{"name":"Away","score":"2"}]}]))
        self.assertEqual(h[0]["settled"],1)
    def test_learning_waits_for_sample_and_is_bounded(self):
        hist=[{"sport":"basketball_nba","first_probability":.7,"settled":1} for i in range(39)]
        self.assertEqual(module.calibration(hist,"basketball_nba","high")["bias"],0)
        hist.extend({"sport":"basketball_nba","first_probability":.7,"settled":1} for i in range(30))
        self.assertTrue(0<module.calibration(hist,"basketball_nba","high")["bias"]<=.04)
    def test_does_not_suggest_betting_with_no_source(self):
        self.assertEqual(module.read_data().get("schema"),2)
    def test_reference_probabilities_sum_to_one(self):
        rows=module.event_rows(self.fixture(False),[])
        self.assertAlmostEqual(sum(r["reference_probability"] for r in rows),1,places=3)
class OddsPapiAdapterTests(unittest.TestCase):
    @staticmethod
    def adapter():
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"research"/"bookie"))
        import odds_papi
        return odds_papi
    @staticmethod
    def board(sport=11,market="888"):
        return {"fixtureId":"fixture-1","sportId":sport,"sportName":"Basketball" if sport==11 else "Soccer",
                "startTime":module.stamp(module.now()+dt.timedelta(hours=6)),
                "participant1Name":"Wolves","participant2Name":"Magic",
                "bookmakerOdds":{"bet365":{"bookmakerIsActive":True,"suspended":False,"markets":{market:{
                    "marketActive":True,"outcomes":{
                        market:{"players":{"0":{"active":True,"price":2.01,"changedAt":module.stamp()}}},
                        str(int(market)+1):{"players":{"0":{"active":True,"price":1.8,"changedAt":module.stamp()}}}
                    }}}}}}
    def test_dynamic_two_way_moneyline(self):
        api=self.adapter()
        markets=[{"sportId":11,"marketId":888,"marketLength":2,"marketName":"Moneyline","period":"fulltime","marketType":"moneyline",
                  "playerProp":False,"handicap":0,"outcomes":[{"outcomeId":888,"outcomeName":"1"},{"outcomeId":889,"outcomeName":"2"}]}]
        norm=api.normalize(self.board(),markets)
        self.assertEqual(norm["market_id"],"888")
        self.assertEqual(norm["outcome_ids"]["Wolves"],"888")
        self.assertEqual(norm["bookmakers"][0]["markets"][0]["outcomes"][0]["price"],2.01)
        self.assertIsNone(api.normalize(self.board(),[]))
    def test_no_sport_arithmetic_or_spread_confusion(self):
        api=self.adapter()
        markets=[{"sportId":11,"marketId":888,"marketLength":2,"marketName":"Moneyline","period":"fulltime",
                  "playerProp":False,"handicap":12.5,"outcomes":[{"outcomeId":888,"outcomeName":"1"},{"outcomeId":889,"outcomeName":"2"}]}]
        self.assertIsNone(api.normalize(self.board(),markets))
    def test_football_requires_full_time_three_way(self):
        api=self.adapter()
        market={"sportId":10,"marketId":101,"marketLength":3,"marketName":"Full Time Result","marketType":"1x2",
                "period":"fulltime","handicap":0,"outcomes":[{"outcomeId":101,"outcomeName":"1"},
                {"outcomeId":102,"outcomeName":"X"},{"outcomeId":103,"outcomeName":"2"}]}
        board=self.board(sport=10,market="101")
        board["bookmakerOdds"]["bet365"]["markets"]["101"]["outcomes"]["103"]={"players":{"0":{"active":True,"price":4.3,"changedAt":module.stamp()}}}
        mapping=api.market_name_map(board,[market])
        self.assertEqual(mapping[0],"101")
        self.assertEqual(mapping[1]["102"],"Draw")
        self.assertEqual(mapping[1]["103"],"Magic")
        market["period"]="firsthalf"
        self.assertIsNone(api.market_name_map(board,[market]))
    def test_learning_pauses_when_forward_adjustments_worsen(self):
        hist=[{"first_probability":.65,"first_adjusted_probability":.7,"settled":0,
               "settled_at":module.stamp(),"sport":"basketball","event_id":str(i)} for i in range(35)]
        self.assertFalse(module.adjustment_guard(hist))


class QuotaGuardTests(unittest.TestCase):
    @staticmethod
    def quota():
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"research"/"bookie"))
        import quota
        return quota
    def test_unverified_quota_blocks_all_billable_calls(self):
        q=self.quota()
        with self.assertRaisesRegex(RuntimeError,"quota"):
            q.billable_call({}, "example-test-key", "odds", {"fixtureId":"fake"})
    def test_reserve_blocks_call_before_network(self):
        q=self.quota()
        data={"papi_usage":{"count":220,"hard_cap":220}}
        with self.assertRaisesRegex(RuntimeError,"exhausted"):
            q.billable_call(data, "example-test-key", "odds", {"fixtureId":"fake"})
    def test_account_preflight_enforces_30_call_reserve(self):
        import io
        from unittest.mock import patch
        q=self.quota()
        fake={"current_subscription_id":"s1","subscriptions":[{"subscription_id":"s1","is_active":True,
              "request_limit":250,"request_count":219,"bookmakers":{"bet365":{}}}]}
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self,*args): return __import__("json").dumps(fake).encode()
        with patch.object(q.urllib.request, "urlopen", return_value=Response()) as network:
            data={}
            q.check_quota(data,"example-test-key")
            self.assertEqual(data["quota_remaining"],1)
            with self.assertRaisesRegex(RuntimeError,"exhausted"):
                data["papi_usage"]["count"]=220
                q.billable_call(data,"example-test-key","odds",{})
            self.assertEqual(network.call_count,1) # account check only; no billable request
    def test_account_preflight_fails_closed_without_bet365(self):
        from unittest.mock import patch
        q=self.quota()
        fake={"current_subscription_id":"s1","subscriptions":[{"subscription_id":"s1","is_active":True,
              "request_limit":250,"request_count":0,"bookmakers":{"pinnacle":{}}}]}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,*args):return __import__("json").dumps(fake).encode()
        with patch.object(q.urllib.request,"urlopen",return_value=Response()):
            with self.assertRaisesRegex(RuntimeError,"bet365"):
                q.check_quota({},"example-test-key")

if __name__=="__main__":unittest.main()
