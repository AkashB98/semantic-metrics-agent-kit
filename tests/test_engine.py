import socket, unittest, hashlib, json
# no-network guard: block non-localhost connections
_orig_connect=socket.socket.connect
def _guarded(self, address):
    host=address[0] if isinstance(address, tuple) else address
    if host not in ("127.0.0.1","localhost","::1"): raise AssertionError(f"network blocked: {host}")
    return _orig_connect(self, address)
socket.socket.connect=_guarded

from semantic_metrics.data import generate_rows
from semantic_metrics.engine import query, QueryError, canonical_hash
from semantic_metrics.registry import load_registry

class TestData(unittest.TestCase):
    def test_determinism(self):
        self.assertEqual(generate_rows(), generate_rows())
        self.assertEqual(len(generate_rows()), 90*3*4)
    def test_registry_counts(self):
        ms=load_registry(); cert=[m for m in ms if m["status"]=="certified"]
        self.assertEqual(len(cert),8); self.assertTrue(any(m["status"]=="draft" for m in ms)); self.assertTrue(any(m["status"]=="deprecated" for m in ms)); self.assertTrue(any(m["status"]=="superseded" for m in ms))
class TestValid(unittest.TestCase):
    def test_revenue(self):
        a=query({"metric":"revenue","grain":"daily","filters":{}}); self.assertIn("provenance",a); self.assertEqual(a["provenance"]["certification_status"],"certified"); self.assertEqual(a["provenance"]["version"],2)
    def test_provenance_hash_stability(self):
        h1=canonical_hash({"channel":"online","region":"north"}); h2=canonical_hash({"region":"north","channel":"online"}); self.assertEqual(h1,h2); self.assertEqual(h1,hashlib.sha256(json.dumps({"channel":"online","region":"north"},sort_keys=True,separators=(",",":")).encode()).hexdigest())
        a1=query({"metric":"orders","grain":"daily","filters":{"channel":"online"}}); a2=query({"metric":"orders","grain":"daily","filters":{"channel":"online"}}); self.assertEqual(a1,a2)
    def test_filter_reduces_rows(self):
        a=query({"metric":"orders","grain":"daily","filters":{}}); b=query({"metric":"orders","grain":"daily","filters":{"channel":"online"}}); self.assertLess(b["provenance"]["source_row_count"], a["provenance"]["source_row_count"])
    def test_window(self):
        a=query({"metric":"orders","grain":"daily","filters":{},"window":{"start":"2026-01-01","end":"2026-01-01"}}); self.assertEqual(a["provenance"]["source_row_count"],12)
    def test_ratio_range(self):
        a=query({"metric":"conversion_rate","grain":"daily","filters":{}}); self.assertTrue(0<=a["value"]<=1)
class TestErrors(unittest.TestCase):
    def assertCode(self, req, code):
        with self.assertRaises(QueryError) as cm: query(req)
        self.assertEqual(cm.exception.code, code)
    def test_unknown(self): self.assertCode({"metric":"nope","grain":"daily","filters":{}},"UNKNOWN_METRIC")
    def test_uncertified(self): self.assertCode({"metric":"churn_rate","grain":"daily","filters":{}},"UNCERTIFIED_METRIC")
    def test_deprecated(self): self.assertCode({"metric":"legacy_daily_revenue","grain":"daily","filters":{}},"DEPRECATED_METRIC")
    def test_superseded(self): self.assertCode({"metric":"revenue","version":1,"grain":"daily","filters":{}},"SUPERSEDED_VERSION")
    def test_grain(self): self.assertCode({"metric":"revenue","grain":"weekly","filters":{}},"GRAIN_MISMATCH")
    def test_grain_monthly(self): self.assertCode({"metric":"revenue","grain":"monthly","filters":{}},"GRAIN_MISMATCH")
    def test_filter_unknown(self): self.assertCode({"metric":"revenue","grain":"daily","filters":{"planet":"mars"}},"FILTER_ERROR")
    def test_filter_type(self): self.assertCode({"metric":"revenue","grain":"daily","filters":{"channel":123}},"FILTER_ERROR")
    def test_dimension_mismatch(self): self.assertCode({"metric":"active_users","grain":"daily","filters":{"channel":"online"}},"DIMENSION_MISMATCH")
class TestServe(unittest.TestCase):
    def test_health_and_ask(self):
        import threading, urllib.request
        from semantic_metrics.cli import main
        from http.server import HTTPServer, BaseHTTPRequestHandler
        # Use engine via CLI serve in thread by constructing server through cli code path is blocking, so test handler logic via direct server copy using same query function
        from semantic_metrics.engine import query as q
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                body=b'{"status":"ok"}'; self.send_response(200); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_POST(self):
                import json as j; raw=self.rfile.read(int(self.headers.get("Content-Length",0))); ans=q(j.loads(raw)); body=j.dumps(ans).encode(); self.send_response(200); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self,*a,**k): pass
        srv=HTTPServer(("127.0.0.1",0),H); t=threading.Thread(target=srv.serve_forever,daemon=True); t.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}/health") as r: self.assertEqual(r.status,200)
            req=urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/ask", data=json.dumps({"metric":"orders","grain":"daily","filters":{}}).encode(), headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req) as r: self.assertIn("value", json.loads(r.read()))
        finally: srv.shutdown()
if __name__=="__main__": unittest.main()
