import argparse, json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from .registry import load_registry
from .engine import query, QueryError
def main(argv=None):
    p=argparse.ArgumentParser(prog="semantic-metrics")
    sub=p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a=sub.add_parser("ask"); a.add_argument("--request", default=None)
    sub.add_parser("check")
    sub.add_parser("demo")
    s=sub.add_parser("serve"); s.add_argument("--port", type=int, default=8765); s.add_argument("--host", default="127.0.0.1")
    args=p.parse_args(argv)
    if args.cmd=="list":
        print(json.dumps(load_registry(), indent=2, sort_keys=True)); return 0
    if args.cmd=="ask":
        raw=args.request if args.request else sys.stdin.read()
        try: req=json.loads(raw)
        except Exception as e: print(json.dumps({"error":"FILTER_ERROR","message":str(e)})); return 1
        try:
            ans=query(req); print(json.dumps(ans, indent=2, sort_keys=True)); return 0
        except QueryError as e:
            print(json.dumps({"error":e.code,"message":e.message}, indent=2, sort_keys=True)); return 1
    if args.cmd=="check":
        try: metrics=load_registry()
        except Exception as e: print(f"check failed: {e}"); return 2
        certified=[m for m in metrics if m["status"]=="certified"]
        ok=len(certified)==8 and all("aggregation" in m and "supported_dimensions" in m for m in metrics)
        print("ok" if ok else "failed"); return 0 if ok else 1
    if args.cmd=="demo":
        examples=[{"metric":"revenue","grain":"daily","filters":{"channel":"online"},"window":{"start":"2026-01-01","end":"2026-01-31"}},{"metric":"conversion_rate","grain":"daily","filters":{},"window":{}},{"metric":"churn_rate","grain":"daily","filters":{}}]
        for req in examples:
            try: print(json.dumps({"request":req,"answer":query(req)}, sort_keys=True))
            except QueryError as e: print(json.dumps({"request":req,"error":e.code,"message":e.message}, sort_keys=True))
        return 0
    if args.cmd=="serve":
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path=="/health":
                    body=b'{"status":"ok"}'; self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
                else:
                    self.send_response(404); self.end_headers()
            def do_POST(self):
                if self.path!="/ask": self.send_response(404); self.end_headers(); return
                length=int(self.headers.get("Content-Length",0)); raw=self.rfile.read(length)
                try: req=json.loads(raw or b"{}")
                except Exception as e: body=json.dumps({"error":"FILTER_ERROR","message":str(e)}).encode(); self.send_response(400); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
                try:
                    ans=query(req); body=json.dumps(ans, sort_keys=True).encode(); code=200
                except QueryError as e:
                    body=json.dumps({"error":e.code,"message":e.message}, sort_keys=True).encode(); code=400
                self.send_response(code); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self, *a, **k): pass
        HTTPServer((args.host, args.port), H).serve_forever(); return 0
    return 2
if __name__=="__main__": raise SystemExit(main())
