"""EvidenceManifest — per-stage artifact scanning and manifest generation."""

import hashlib
import json
import time
from pathlib import Path


def compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def scan_stage_dir(stage_dir: str, stage_name: str, spec_required_paths: list[str] = None) -> list[dict]:
    stage_path = Path(stage_dir)
    if not stage_path.exists():
        return []

    spec_required_paths = spec_required_paths or []
    hints_map = {}
    hints_file = stage_path / "manifest.hints.json"
    if hints_file.exists():
        for h in json.loads(hints_file.read_text()):
            hints_map[h["path"]] = h

    entries = []
    for f in sorted(stage_path.iterdir()):
        if f.name.startswith("manifest.hints"):
            continue
        if not f.is_file():
            continue
        rel_path = f.name
        hint = hints_map.get(rel_path, {})
        role = hint.get("role", "auxiliary")
        if any(rel_path in p or p.endswith(rel_path) for p in spec_required_paths):
            role = "required"

        entries.append({
            "path": str(f),
            "size": f.stat().st_size,
            "sha256": compute_sha256(str(f)),
            "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(f.stat().st_mtime)),
            "produced_by_stage": stage_name,
            "role": role,
            "label": hint.get("label", ""),
            "description": hint.get("description", ""),
        })
    return entries


def merge_manifests(stage_manifests: list[dict], task_id: str, task_type: str) -> dict:
    stages = []
    total_files = 0
    total_size = 0
    all_hashes = []

    for sm in stage_manifests:
        manifest_path = Path(sm["manifest_path"])
        if not manifest_path.exists():
            stages.append({"name": sm["name"], "entries": []})
            continue
        entries = json.loads(manifest_path.read_text())
        stages.append({"name": sm["name"], "entries": entries})
        total_files += len(entries)
        total_size += sum(e.get("size", 0) for e in entries)
        all_hashes.extend(e.get("sha256", "") for e in entries)

    combined = "".join(sorted(all_hashes))
    manifest_sha256 = hashlib.sha256(combined.encode()).hexdigest()
    required_count = sum(1 for s in stages for e in s["entries"] if e.get("role") == "required")

    return {
        "task_id": task_id,
        "task_type": task_type,
        "stages": stages,
        "summary": {
            "total_files": total_files,
            "total_size_bytes": total_size,
            "required_count": required_count,
            "manifest_sha256": manifest_sha256,
        },
    }
