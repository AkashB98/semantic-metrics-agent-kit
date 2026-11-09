import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from semantic_metrics.engine import query, QueryError
from semantic_metrics.data import generate_rows
from semantic_metrics.registry import load_registry

def recompute(req, metrics, rows):
    m=[x for x in metrics if x["id"]==req["metric"] and x["status"]=="certified"][0]
    if req.get("version"): m=[x for x in metrics if x["id"]==req["metric"] and x["version"]==req["version"]][0]
    filters=req.get("filters") or {}
    window=req.get("window") or {}
    filt=[]
    for r in rows:
        if window.get("start") and r["date"]<window["start"]: continue
        if window.get("end") and r["date"]>window["end"]: continue
        if all(r.get(k)==v for k,v in filters.items()): filt.append(r)
    agg=m["aggregation"]
    if agg["op"]=="sum": v=sum(r[agg["field"]] for r in filt)
    elif agg["op"]=="mean": v=sum(r[agg["field"]] for r in filt)/len(filt) if filt else 0.0
    elif agg["op"]=="ratio": 
        den=sum(r[agg["denominator_field"]] for r in filt); v=sum(r[agg["numerator_field"]] for r in filt)/den if den else 0.0
    return round(float(v),6), len(filt)

def main():
    metrics=load_registry(); rows=generate_rows()
    misuse=[
        {"name":"unknown_metric","request":{"metric":"nope_metric","grain":"daily","filters":{}},"expected_error":"UNKNOWN_METRIC"},
        {"name":"uncertified_metric","request":{"metric":"churn_rate","grain":"daily","filters":{}},"expected_error":"UNCERTIFIED_METRIC"},
        {"name":"deprecated_metric","request":{"metric":"legacy_daily_revenue","grain":"daily","filters":{}},"expected_error":"DEPRECATED_METRIC"},
        {"name":"superseded_version","request":{"metric":"revenue","version":1,"grain":"daily","filters":{}},"expected_error":"SUPERSEDED_VERSION"},
        {"name":"grain_mismatch","request":{"metric":"revenue","grain":"weekly","filters":{}},"expected_error":"GRAIN_MISMATCH"},
        {"name":"filter_error_unknown_dimension","request":{"metric":"revenue","grain":"daily","filters":{"planet":"mars"}},"expected_error":"FILTER_ERROR"},
        {"name":"filter_error_type_conflict","request":{"metric":"revenue","grain":"daily","filters":{"channel":123}},"expected_error":"FILTER_ERROR"},
        {"name":"dimension_mismatch","request":{"metric":"active_users","grain":"daily","filters":{"channel":"online"}},"expected_error":"DIMENSION_MISMATCH"},
    ]
    valid=[
        {"name":"valid_revenue_all","request":{"metric":"revenue","grain":"daily","filters":{},"window":{"start":"2026-01-01","end":"2026-01-31"}}},
        {"name":"valid_revenue_channel","request":{"metric":"revenue","grain":"daily","filters":{"channel":"online"},"window":{}}},
        {"name":"valid_conversion_rate","request":{"metric":"conversion_rate","grain":"daily","filters":{"region":"north"},"window":{}}},
        {"name":"valid_avg_order_value","request":{"metric":"avg_order_value","grain":"daily","filters":{},"window":{"start":"2026-02-01","end":"2026-02-28"}}},
        {"name":"valid_active_users","request":{"metric":"active_users","grain":"daily","filters":{"region":"south"},"window":{}}},
        {"name":"valid_gross_margin","request":{"metric":"gross_margin","grain":"daily","filters":{},"window":{}}},
    ]
    cases=[]; tp=fp=fn=0; valid_correct=0
    for c in misuse:
        try:
            query(c["request"], metrics=metrics, rows=rows); got=None
        except QueryError as e: got=e.code
        passed=(got==c["expected_error"])
        if passed: tp+=1
        else:
            if got is not None: fp+=1; fn+=1
            else: fn+=1
        cases.append({"name":c["name"],"kind":"misuse","expected_error":c["expected_error"],"got_error":got,"passed":passed})
    # precision: refusals that were correct / all refusals made. In loop above, a wrong-code refusal counts as fp, correct as tp. If engine refused with wrong code, that's 1 refusal made.
    refusals_made=sum(1 for c in cases if c["got_error"] is not None)
    for c in valid:
        exp,_=recompute(c["request"], metrics, rows)
        try:
            ans=query(c["request"], metrics=metrics, rows=rows); got=ans["value"]; passed=abs(got-exp)<1e-9
        except QueryError as e: got=None; passed=False
        if passed: valid_correct+=1
        cases.append({"name":c["name"],"kind":"valid","expected_value":exp,"got_value":got,"passed":passed})
    precision=round(tp/refusals_made,6) if refusals_made else 0.0
    recall=round(tp/len(misuse),6) if misuse else 0.0
    valid_rate=round(valid_correct/len(valid),6) if valid else 0.0
    report={"cases":cases,"correct_answer_rate":valid_rate,"misuse_total":len(misuse),"refusal_precision":precision,"refusal_recall":recall,"total_cases":len(cases),"valid_correct":valid_correct,"valid_total":len(valid)}
    out=pathlib.Path(__file__).resolve().parent/"eval_report.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if (precision==1.0 and recall==1.0 and valid_rate==1.0) else 1
if __name__=="__main__": raise SystemExit(main())
