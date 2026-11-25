import hashlib, json, pathlib
from .data import generate_rows
from .engine import query, QueryError
from .registry import load_registry, find_metrics

# Finding precedence: a tile's status is its highest-precedence finding, or OK.
FINDING_ORDER = ["UNKNOWN_METRIC", "INVALID_QUERY", "UNCERTIFIED_SOURCE",
                 "STALE_VERSION", "DEFINITION_DRIFT", "VALUE_MISMATCH"]
REQUIRED_TILE_FIELDS = ["id", "dashboard", "title", "metric", "version",
                        "aggregation", "grain", "unit", "filters", "window",
                        "stakes", "reported_value"]
DECISIONS = {"approved", "flagged", "waived"}

class GovernanceError(Exception):
    def __init__(self, code, message):
        super().__init__(message); self.code = code; self.message = message

def default_tiles_path():
    return pathlib.Path(__file__).resolve().parent.parent / "dashboards.json"

def load_tiles(path=None):
    p = pathlib.Path(path) if path else default_tiles_path()
    data = json.loads(p.read_text())
    return data["tiles"]

def _canonical(obj):
    canon = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()

def definition_fingerprint(entry):
    """Fingerprint of a registry definition's full semantic content."""
    return _canonical({"id": entry["id"], "version": entry["version"],
                       "formula": entry["formula"], "aggregation": entry["aggregation"],
                       "grain": entry["grain"], "unit": entry["unit"]})

def spec_fingerprint(aggregation, grain, unit):
    """Fingerprint of a computable spec only — what drift detection compares.
    Prose (formula wording) is excluded: rewording a formula is not drift."""
    return _canonical({"aggregation": aggregation, "grain": grain, "unit": unit})

def _validate_tile(tile):
    if not isinstance(tile, dict):
        raise GovernanceError("MALFORMED_TILE", "tile must be an object")
    missing = [f for f in REQUIRED_TILE_FIELDS if f not in tile]
    if missing:
        raise GovernanceError("MALFORMED_TILE",
                              f"tile {tile.get('id', '?')} missing fields: {', '.join(missing)}")
    if tile["stakes"] not in ("low", "medium", "high"):
        raise GovernanceError("MALFORMED_TILE",
                              f"tile {tile['id']} stakes must be low/medium/high")

def _tile_value(tile, rows):
    """The tile's own value, computed by the existing engine running a
    synthetic certified entry built from the tile's declared spec — the kit
    has exactly one aggregator, so tile and certified values cannot diverge
    through code differences."""
    entry = {"id": tile["metric"], "version": tile["version"], "formula": "",
             "aggregation": tile["aggregation"], "grain": tile["grain"],
             "unit": tile["unit"], "owner": "tile", "status": "certified",
             "supported_dimensions": sorted(tile["filters"].keys())}
    req = {"metric": tile["metric"], "grain": tile["grain"],
           "filters": tile["filters"], "window": tile["window"]}
    return query(req, metrics=[entry], rows=rows)["value"]

def _certified_value(tile, metrics, rows):
    req = {"metric": tile["metric"], "grain": tile["grain"],
           "filters": tile["filters"], "window": tile["window"]}
    return query(req, metrics=metrics, rows=rows)["value"]

def trace_tile(tile, metrics=None, rows=None):
    _validate_tile(tile)
    if metrics is None: metrics = load_registry()
    if rows is None: rows = generate_rows()
    findings = []
    pinned = None
    for m in find_metrics(metrics, tile["metric"]):
        if m["version"] == tile["version"]: pinned = m; break
    lineage = {"tile_id": tile["id"], "dashboard": tile["dashboard"],
               "title": tile["title"], "metric": tile["metric"],
               "pinned_version": tile["version"], "resolved_definition": None,
               "tile_spec_fingerprint": spec_fingerprint(tile["aggregation"], tile["grain"], tile["unit"]),
               "definition_spec_fingerprint": None}
    tile_value = None; certified_value = None
    if pinned is None:
        findings.append("UNKNOWN_METRIC")
    else:
        lineage["resolved_definition"] = {
            "id": pinned["id"], "version": pinned["version"],
            "owner": pinned["owner"], "status": pinned["status"],
            "definition_fingerprint": definition_fingerprint(pinned)}
        lineage["definition_spec_fingerprint"] = spec_fingerprint(
            pinned["aggregation"], pinned["grain"], pinned["unit"])
        if pinned["status"] in ("draft", "deprecated"):
            findings.append("UNCERTIFIED_SOURCE")
        if pinned["status"] == "superseded":
            findings.append("STALE_VERSION")
        # Drift is measured against the PINNED version's spec: a tile that
        # faithfully implements an old version is stale, not drifted.
        if lineage["tile_spec_fingerprint"] != lineage["definition_spec_fingerprint"]:
            findings.append("DEFINITION_DRIFT")
        try:
            tile_value = _tile_value(tile, rows)
        except QueryError:
            tile_value = None
        if pinned["status"] == "certified":
            try:
                certified_value = _certified_value(tile, metrics, rows)
            except QueryError:
                findings.append("INVALID_QUERY")
        # Dashboards display rounded numbers: compare at 2 decimal places.
        if tile_value is not None and round(float(tile["reported_value"]), 2) != round(tile_value, 2):
            findings.append("VALUE_MISMATCH")
    findings.sort(key=FINDING_ORDER.index)
    status = findings[0] if findings else "OK"
    return {"tile_id": tile["id"], "dashboard": tile["dashboard"],
            "title": tile["title"], "stakes": tile["stakes"], "status": status,
            "findings": findings, "lineage": lineage,
            "tile_value": tile_value, "certified_value": certified_value,
            "reported_value": tile["reported_value"]}

def audit(tiles=None, metrics=None, rows=None):
    if tiles is None: tiles = load_tiles()
    if metrics is None: metrics = load_registry()
    if rows is None: rows = generate_rows()
    traces = [trace_tile(t, metrics=metrics, rows=rows) for t in tiles]
    by_status = {}
    for t in traces: by_status[t["status"]] = by_status.get(t["status"], 0) + 1
    return {"tiles": traces,
            "summary": {"total": len(traces), "ok": by_status.get("OK", 0),
                        "by_status": by_status,
                        "findings_total": sum(len(t["findings"]) for t in traces)}}

def record_review(entries, audit_result, tile_id, reviewer, decision, note=""):
    """Append one review entry (pure: returns a new list). Stakes come from
    the tile itself, never from the reviewer. Approving a tile whose audit
    finding is not OK is refused — that approval is the governance failure
    this log exists to prevent."""
    if decision not in DECISIONS:
        raise GovernanceError("REVIEW_BAD_DECISION", f"unknown decision: {decision}")
    trace = None
    for t in audit_result["tiles"]:
        if t["tile_id"] == tile_id: trace = t; break
    if trace is None:
        raise GovernanceError("REVIEW_UNKNOWN_TILE", f"no audited tile: {tile_id}")
    if decision == "approved" and trace["status"] != "OK":
        raise GovernanceError("REVIEW_APPROVES_FINDING",
                              f"tile {tile_id} has finding {trace['status']} and cannot be approved")
    entry = {"tile_id": tile_id, "reviewer": reviewer, "decision": decision,
             "stakes": trace["stakes"], "finding": trace["status"], "note": note}
    return list(entries) + [entry]

def review_summary(entries, audit_result):
    decisions = {}
    for e in entries: decisions[e["decision"]] = decisions.get(e["decision"], 0) + 1
    reviewed = {e["tile_id"] for e in entries}
    return {"decisions": decisions,
            "requires_escalation": [e["tile_id"] for e in entries
                                    if e["decision"] == "waived" and e["stakes"] == "high"],
            "unreviewed_findings": [t["tile_id"] for t in audit_result["tiles"]
                                    if t["status"] != "OK" and t["tile_id"] not in reviewed]}
