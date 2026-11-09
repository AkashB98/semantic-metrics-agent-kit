import json, pathlib
def default_path():
    return pathlib.Path(__file__).resolve().parent.parent/"metrics.json"
def load_registry(path=None):
    p=pathlib.Path(path) if path else default_path()
    data=json.loads(p.read_text())
    return data["metrics"]
def find_metrics(metrics, metric_id):
    return [m for m in metrics if m["id"]==metric_id]
