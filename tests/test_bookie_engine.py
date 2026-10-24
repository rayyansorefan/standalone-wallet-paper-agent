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
if __name__=="__main__":unittest.main()
