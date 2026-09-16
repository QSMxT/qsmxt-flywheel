"""Shared helpers for the gear tests: running the container the way Flywheel
does, and reporting checks."""

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = json.loads((REPO / "v0" / "manifest.json").read_text())

failures = []


def check(condition, message):
    print(f"  {'ok  ' if condition else 'FAIL'} {message}")
    if not condition:
        failures.append(message)
    return bool(condition)


def run_gear(image, work, mag_zip, phs_zip, config_overrides=None, network="none"):
    """Run the gear on a pair of DICOM zips and return (output_dir, result).

    The container is given no network by default, so a run that quietly
    depended on a download fails here rather than at a customer site.
    """
    gear_dir = work / "gear"
    if gear_dir.exists():
        shutil.rmtree(gear_dir)
    for sub in ("input/magnitude", "input/phase", "output"):
        (gear_dir / sub).mkdir(parents=True)
    shutil.copy(mag_zip, gear_dir / "input" / "magnitude" / "mag.zip")
    shutil.copy(phs_zip, gear_dir / "input" / "phase" / "phs.zip")

    config = {key: spec["default"] for key, spec in MANIFEST["config"].items()}
    config.update(config_overrides or {})
    (gear_dir / "config.json").write_text(json.dumps({
        "config": config,
        "inputs": {
            "magnitude": {"base": "file", "location": {
                "path": "/flywheel/v0/input/magnitude/mag.zip", "name": "mag.zip"}},
            "phase": {"base": "file", "location": {
                "path": "/flywheel/v0/input/phase/phs.zip", "name": "phs.zip"}},
        },
        "destination": {"type": "session", "id": "test"},
    }, indent=2))

    result = subprocess.run([
        "docker", "run", "--rm", f"--network={network}",
        "-v", f"{gear_dir / 'input'}:/flywheel/v0/input",
        "-v", f"{gear_dir / 'output'}:/flywheel/v0/output",
        "-v", f"{gear_dir / 'config.json'}:/flywheel/v0/config.json",
        image, "python3", "run.py",
    ], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-4000:], file=sys.stderr)
    return gear_dir / "output", result


def extract(zip_path, pattern, into):
    """Pull the first member matching `pattern` out of an archive."""
    with zipfile.ZipFile(zip_path) as archive:
        matches = [n for n in archive.namelist() if n.endswith(pattern)]
        if not matches:
            return None
        return Path(archive.extract(matches[0], into))


def report():
    print()
    if failures:
        print(f"{len(failures)} check(s) failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("All checks passed")
    return 0
