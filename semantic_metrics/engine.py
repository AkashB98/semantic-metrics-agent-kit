import hashlib, json
from .data import generate_rows
from .registry import load_registry
KNOWN_DIMENSIONS={"channel","region"}
class QueryError(Exception):
    def __init__(self, code, message):
        super().__init__(message); self.code=code; self.message=message
def canonical_hash(filters):
    canon=json.dumps(filters or {}, sort_keys=True, separators=(",",":"))
    return hashlib.sha256(canon.encode()).hexdigest()
def query(request, metrics=None, rows=None):
    if not isinstance(request, dict):
        raise QueryError("FILTER_ERROR","request must be an object")
    metric_id=request.get("metric")
    grain=request.get("grain","daily")
    filters=request.get("filters") or {}
    window=request.get("window") or {}
    version=request.get("version")
    if metrics is None: metrics=load_registry()
    candidates=[m for m in metrics if m["id"]==metric_id]
    if not candidates:
        raise QueryError("UNKNOWN_METRIC", f"unknown metric: {metric_id}")
    # resolve version
    chosen=None
    if version is not None:
        for m in candidates:
            if m["version"]==version: chosen=m; break
        if chosen is None:
            raise QueryError("UNKNOWN_METRIC", f"unknown version {version} for metric {metric_id}")
        if chosen["status"]=="superseded":
            raise QueryError("SUPERSEDED_VERSION", f"metric {metric_id} version {version} is superseded")
        if chosen["status"]=="deprecated":
            raise QueryError("DEPRECATED_METRIC", f"metric {metric_id} is deprecated")
        if chosen["status"]=="draft":
            raise QueryError("UNCERTIFIED_METRIC", f"metric {metric_id} is not certified")
        if chosen["status"]!="certified":
            raise QueryError("UNCERTIFIED_METRIC", f"metric {metric_id} status {chosen['status']} is not certified")
    else:
        certified=[m for m in candidates if m["status"]=="certified"]
        if not certified:
            # determine reason from highest priority status present
            statuses={m["status"] for m in candidates}
            if "draft" in statuses:
                raise QueryError("UNCERTIFIED_METRIC", f"metric {metric_id} is not certified")
            if "deprecated" in statuses:
                raise QueryError("DEPRECATED_METRIC", f"metric {metric_id} is deprecated")
            if "superseded" in statuses:
                raise QueryError("SUPERSEDED_VERSION", f"metric {metric_id} is superseded")
            raise QueryError("UNCERTIFIED_METRIC", f"metric {metric_id} is not certified")
        chosen=max(certified, key=lambda m: m["version"])
    if grain!=chosen["grain"]:
        raise QueryError("GRAIN_MISMATCH", f"metric {metric_id} grain is {chosen['grain']}, requested {grain}")
    if not isinstance(filters, dict):
        raise QueryError("FILTER_ERROR","filters must be an object")
    for k,v in filters.items():
        if k not in KNOWN_DIMENSIONS:
            raise QueryError("FILTER_ERROR", f"unknown dimension: {k}")
        if k not in chosen.get("supported_dimensions",[]):
            raise QueryError("DIMENSION_MISMATCH", f"metric {metric_id} does not support dimension {k}")
        if not isinstance(v, str):
            raise QueryError("FILTER_ERROR", f"value for dimension {k} must be a string")
    if rows is None: rows=generate_rows()
    filtered=[]
    start=window.get("start"); end=window.get("end")
    # validate window types
    if start is not None and not isinstance(start,str): raise QueryError("FILTER_ERROR","window start must be a string date")
    if end is not None and not isinstance(end,str): raise QueryError("FILTER_ERROR","window end must be a string date")
    for r in rows:
        if start and r["date"]<start: continue
        if end and r["date"]>end: continue
        ok=True
        for k,v in filters.items():
            if r.get(k)!=v: ok=False; break
        if ok: filtered.append(r)
    agg=chosen["aggregation"]; op=agg["op"]
    if op=="sum":
        value=sum(r[agg["field"]] for r in filtered)
    elif op=="mean":
        value=(sum(r[agg["field"]] for r in filtered)/len(filtered)) if filtered else 0.0
    elif op=="ratio":
        num=sum(r[agg["numerator_field"]] for r in filtered); den=sum(r[agg["denominator_field"]] for r in filtered)
        value=(num/den) if den else 0.0
    else:
        raise QueryError("FILTER_ERROR", f"unsupported op {op}")
    value=round(float(value),6)
    return {"value":value,"metric":chosen["id"],"grain":chosen["grain"],"unit":chosen["unit"],"provenance":{"definition_id":chosen["id"],"version":chosen["version"],"filter_hash":canonical_hash(filters),"filters_hash":canonical_hash(filters),"source_row_count":len(filtered),"row_count":len(filtered),"certification_status":chosen["status"],"status":chosen["status"]}}
