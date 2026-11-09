import json, subprocess, sys, threading, time, urllib.request, urllib.error, pathlib
root=pathlib.Path(__file__).resolve().parent
def run_cli(*args, input_data=None):
    return subprocess.run([sys.executable,"-m","semantic_metrics.cli",*args], cwd=root, capture_output=True, text=True, input=input_data)
def main():
    # list
    r=run_cli("list"); assert r.returncode==0, r.stderr; print("list ok")
    # ask valid
    req=json.dumps({"metric":"revenue","grain":"daily","filters":{"channel":"online"},"window":{"start":"2026-01-01","end":"2026-01-31"}})
    r=run_cli("ask","--request",req); assert r.returncode==0, r.stdout+r.stderr; ans=json.loads(r.stdout); assert "provenance" in ans; print(f"ask ok value={ans['value']}")
    # ask invalid should exit 1 with typed error
    r=run_cli("ask","--request",json.dumps({"metric":"churn_rate","grain":"daily","filters":{}})); assert r.returncode==1; assert "UNCERTIFIED_METRIC" in r.stdout; print("ask refusal ok")
    # check
    r=run_cli("check"); assert r.returncode==0, r.stdout; print("check ok")
    # demo command
    r=run_cli("demo"); assert r.returncode==0; print("cli demo ok")
    # serve round-trip
    proc=subprocess.Popen([sys.executable,"-m","semantic_metrics.cli","serve","--port","18765"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen("http://127.0.0.1:18765/health", timeout=1) as resp: assert resp.status==200; break
            except Exception: time.sleep(0.1)
        else: raise RuntimeError("serve did not start")
        print("serve health ok")
        data=json.dumps({"metric":"orders","grain":"daily","filters":{}}).encode()
        req2=urllib.request.Request("http://127.0.0.1:18765/ask", data=data, headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req2, timeout=5) as resp: body=json.loads(resp.read()); assert "value" in body; print(f"serve ask ok value={body['value']}")
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except Exception: proc.kill()
    print("demo: all ok")
    return 0
if __name__=="__main__": raise SystemExit(main())
