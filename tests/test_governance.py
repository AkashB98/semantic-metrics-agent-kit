import socket, unittest
# no-network guard: block non-localhost connections
_orig_connect=socket.socket.connect
def _guarded(self, address):
    host=address[0] if isinstance(address, tuple) else address
    if host not in ("127.0.0.1","localhost","::1"): raise AssertionError(f"network blocked: {host}")
    return _orig_connect(self, address)
socket.socket.connect=_guarded

from semantic_metrics.data import generate_rows
from semantic_metrics.engine import query
from semantic_metrics.governance import (GovernanceError, audit, definition_fingerprint,
    load_tiles, record_review, review_summary, spec_fingerprint, trace_tile)
from semantic_metrics.registry import load_registry

EXPECTED={"exec-revenue-online-jan":"OK","exec-revenue-all-legacy":"DEFINITION_DRIFT",
    "finance-revenue-v1-pin":"STALE_VERSION","growth-conversion-feb":"VALUE_MISMATCH",
    "product-churn-draft":"UNCERTIFIED_SOURCE"}

def _tile(**over):
    t={"id":"t1","dashboard":"D","title":"T","metric":"orders","version":1,
       "aggregation":{"field":"orders_count","op":"sum"},"grain":"daily","unit":"count",
       "filters":{},"window":{},"stakes":"low","reported_value":0}
    t.update(over); return t

class TestFingerprints(unittest.TestCase):
    def test_stability(self):
        ms=load_registry(); rev=[m for m in ms if m["id"]=="revenue" and m["version"]==2][0]
        self.assertEqual(definition_fingerprint(rev), definition_fingerprint(dict(rev)))
    def test_formula_rewording_is_not_spec_drift(self):
        ms=load_registry(); rev=[m for m in ms if m["id"]=="revenue" and m["version"]==2][0]
        reworded=dict(rev); reworded["formula"]="Total money in, restated in other words"
        self.assertNotEqual(definition_fingerprint(rev), definition_fingerprint(reworded))
        self.assertEqual(spec_fingerprint(rev["aggregation"],rev["grain"],rev["unit"]),
                         spec_fingerprint(reworded["aggregation"],reworded["grain"],reworded["unit"]))
    def test_field_change_is_spec_drift(self):
        self.assertNotEqual(spec_fingerprint({"field":"revenue_amount","op":"sum"},"daily","USD"),
                            spec_fingerprint({"field":"revenue_legacy_amount","op":"sum"},"daily","USD"))

class TestPlantedTiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.report=audit()
    def test_each_tile_exactly_its_planted_finding(self):
        for t in self.report["tiles"]:
            self.assertEqual(t["status"], EXPECTED[t["tile_id"]], t["tile_id"])
            want=[] if t["status"]=="OK" else [t["status"]]
            self.assertEqual(t["findings"], want, t["tile_id"])
    def test_clean_tile_values_agree(self):
        t=[x for x in self.report["tiles"] if x["tile_id"]=="exec-revenue-online-jan"][0]
        self.assertEqual(t["tile_value"], t["certified_value"])
        self.assertEqual(t["lineage"]["resolved_definition"]["owner"], "finance-analytics")
        self.assertEqual(t["lineage"]["resolved_definition"]["status"], "certified")
    def test_drift_tile_value_gap(self):
        t=[x for x in self.report["tiles"] if x["tile_id"]=="exec-revenue-all-legacy"][0]
        self.assertNotEqual(t["tile_value"], t["certified_value"])  # legacy field understates revenue
    def test_summary(self):
        s=self.report["summary"]; self.assertEqual(s["total"],5); self.assertEqual(s["ok"],1); self.assertEqual(s["findings_total"],4)

class TestFindingVariants(unittest.TestCase):
    def test_unknown_version(self):
        t=_tile(metric="revenue", version=3, aggregation={"field":"revenue_amount","op":"sum"}, unit="USD")
        r=trace_tile(t); self.assertEqual(r["status"],"UNKNOWN_METRIC"); self.assertIsNone(r["lineage"]["resolved_definition"])
    def test_unknown_metric(self):
        r=trace_tile(_tile(metric="nope_metric")); self.assertEqual(r["status"],"UNKNOWN_METRIC")
    def test_invalid_query(self):
        # active_users does not support the channel dimension: the certified
        # recompute raises, which the audit must surface, not crash on.
        rows=generate_rows(); total=sum(r["active_users_count"] for r in rows)/len(rows)
        t=_tile(metric="active_users", aggregation={"field":"active_users_count","op":"mean"},
                unit="count", filters={"channel":"online"}, reported_value=round(total,6))
        r=trace_tile(t); self.assertEqual(r["status"],"INVALID_QUERY")
    def test_value_tolerance_two_dp(self):
        rows=generate_rows(); total=query({"metric":"orders","grain":"daily","filters":{}}, rows=rows)["value"]
        ok=trace_tile(_tile(reported_value=total+0.001), rows=rows); self.assertEqual(ok["status"],"OK")
        bad=trace_tile(_tile(reported_value=total+0.5), rows=rows); self.assertEqual(bad["status"],"VALUE_MISMATCH")
    def test_malformed_tile(self):
        t=_tile(); del t["stakes"]
        with self.assertRaises(GovernanceError) as cm: trace_tile(t)
        self.assertEqual(cm.exception.code,"MALFORMED_TILE")
    def test_audit_cli_exit_codes(self):
        from semantic_metrics.cli import main
        self.assertEqual(main(["audit"]),1)  # planted findings present, by design

class TestReviewLog(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.report=audit()
    def test_approve_ok_tile(self):
        entries=record_review([], self.report, "exec-revenue-online-jan", "sam", "approved")
        self.assertEqual(len(entries),1); self.assertEqual(entries[0]["stakes"],"high")  # stakes from the tile, not the reviewer
    def test_approve_finding_tile_refused(self):
        with self.assertRaises(GovernanceError) as cm:
            record_review([], self.report, "exec-revenue-all-legacy", "sam", "approved")
        self.assertEqual(cm.exception.code,"REVIEW_APPROVES_FINDING")
    def test_pure_function(self):
        before=[]; record_review(before, self.report, "exec-revenue-online-jan", "sam", "approved")
        self.assertEqual(before,[])
    def test_high_stakes_waiver_escalates(self):
        entries=record_review([], self.report, "exec-revenue-all-legacy", "sam", "waived", note="board pack already sent")
        s=review_summary(entries, self.report)
        self.assertEqual(s["requires_escalation"],["exec-revenue-all-legacy"])
    def test_unreviewed_findings(self):
        s=review_summary([], self.report)
        self.assertEqual(sorted(s["unreviewed_findings"]),
            sorted(["exec-revenue-all-legacy","finance-revenue-v1-pin","growth-conversion-feb","product-churn-draft"]))
        entries=record_review([], self.report, "product-churn-draft", "sam", "flagged")
        s=review_summary(entries, self.report)
        self.assertNotIn("product-churn-draft", s["unreviewed_findings"])
    def test_bad_decision_and_unknown_tile(self):
        with self.assertRaises(GovernanceError): record_review([], self.report, "exec-revenue-online-jan", "sam", "shrugged")
        with self.assertRaises(GovernanceError): record_review([], self.report, "nope", "sam", "flagged")
if __name__=="__main__": unittest.main()
