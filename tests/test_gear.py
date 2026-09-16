#!/usr/bin/env python3
"""End-to-end test of the gear container.

Generates a synthetic multi-echo GRE acquisition as DICOM, runs the gear on it
exactly as Flywheel would, and checks what comes out.

    python3 tests/test_gear.py [--image qsmxt_flywheel:test]

Needs docker, plus numpy, pydicom and nibabel for generating the input and
reading the output. The container itself is run with no network, so a run that
quietly depended on downloading something would fail here.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import nibabel as nib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gearlib import REPO, check, extract, failures, report, run_gear  # noqa: E402

# What the phantom in make_test_dicoms.py contains, in ppm.
SIMULATED_CHI = (-0.04, 0.06)


def test_default_pipeline(image, work, dicoms):
    print("\nA default run reconstructs a susceptibility map:")
    # TKD is the fastest inversion; every other stage is left on its default.
    out, result = run_gear(image, work, dicoms / "mag.zip", dicoms / "phs.zip",
                           {"qsm_algorithm": "tkd"})
    check(result.returncode == 0, f"gear exits 0 (got {result.returncode})")
    check((out / "qsm.zip").is_file(), "qsm.zip written")
    check((out / "workflow.zip").is_file(), "workflow.zip written")
    check((out / "qsmxt.log").is_file(), "qsmxt.log written")
    check(not (out / "bids.zip").exists(), "no bids.zip unless asked for")
    if not (out / "qsm.zip").is_file():
        return

    tmp = work / "extract-default"
    chimap_path = extract(out / "qsm.zip", "_Chimap.nii", tmp)
    check(chimap_path is not None, "qsm.zip contains a Chimap")
    check(extract(out / "qsm.zip", "_mask.nii", tmp) is not None, "qsm.zip contains a mask")
    check(extract(out / "qsm.zip", "methods.md", tmp) is not None,
          "qsm.zip contains methods.md citing what ran")
    if chimap_path is None:
        return

    chimap = np.asarray(nib.load(chimap_path).dataobj)
    check(np.isfinite(chimap).all(), "Chimap is all finite")
    check((chimap != 0).sum() > 1000,
          f"Chimap is not empty ({int((chimap != 0).sum())} nonzero voxels)")

    # The phantom's two sources should come back roughly where they were put.
    # A tolerance this loose only catches a reconstruction that is broken, not
    # one that is merely imprecise on a 64x64x48 phantom.
    low, high = float(chimap.min()), float(chimap.max())
    check(abs(low - SIMULATED_CHI[0]) < 0.03,
          f"diamagnetic source recovered ({low:+.3f} ppm, simulated {SIMULATED_CHI[0]:+.3f})")
    check(abs(high - SIMULATED_CHI[1]) < 0.03,
          f"paramagnetic source recovered ({high:+.3f} ppm, simulated {SIMULATED_CHI[1]:+.3f})")


def test_output_options(image, work, dicoms):
    print("\nsave_bids and clean_intermediates change what is packaged:")
    out, result = run_gear(image, work, dicoms / "mag.zip", dicoms / "phs.zip", {
        "qsm_algorithm": "tkd", "save_bids": True, "clean_intermediates": True,
    })
    check(result.returncode == 0, f"gear exits 0 (got {result.returncode})")
    check((out / "bids.zip").is_file(), "save_bids -> bids.zip written")
    check((out / "qsm.zip").is_file(), "qsm.zip still written")
    if (out / "bids.zip").is_file():
        with zipfile.ZipFile(out / "bids.zip") as archive:
            phase = [n for n in archive.namelist() if "part-phase" in n and n.endswith(".nii.gz")]
        check(len(phase) == 4, f"bids.zip holds all 4 converted phase echoes (got {len(phase)})")


def test_supplementary_outputs_without_qsm(image, work, dicoms):
    print("\nno_qsm produces the supplementary maps only:")
    out, result = run_gear(image, work, dicoms / "mag.zip", dicoms / "phs.zip", {
        "no_qsm": True, "do_t2starmap": True, "do_r2starmap": True,
    })
    check(result.returncode == 0, f"gear exits 0 (got {result.returncode})")
    if not (out / "qsm.zip").is_file():
        check(False, "qsm.zip written")
        return
    tmp = work / "extract-nosqm"
    check(extract(out / "qsm.zip", "_T2starmap.nii", tmp) is not None, "T2* map produced")
    check(extract(out / "qsm.zip", "_R2starmap.nii", tmp) is not None, "R2* map produced")
    check(extract(out / "qsm.zip", "_Chimap.nii", tmp) is None, "no Chimap, as asked")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="qsmxt_flywheel:test")
    parser.add_argument("--network", default="none",
                        help="docker network for the gear container (default: none)")
    parser.add_argument("--keep", action="store_true", help="keep the working directory")
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="qsmxt-gear-test-"))
    print(f"Image:       {args.image}")
    print(f"Working dir: {work}")

    dicoms = work / "dicoms"
    subprocess.run([sys.executable, str(REPO / "tests" / "make_test_dicoms.py"), str(dicoms)],
                   check=True)

    print("\nConfiguration checks (inside the container):")
    config_test = subprocess.run([
        "docker", "run", "--rm", f"--network={args.network}",
        "-v", f"{REPO / 'tests'}:/tests:ro", args.image, "python3", "/tests/test_config.py",
    ], capture_output=True, text=True)
    print("  " + config_test.stdout.strip().splitlines()[-1] if config_test.stdout else "")
    if config_test.returncode != 0:
        print(config_test.stdout)
        failures.append("configuration checks")

    test_default_pipeline(args.image, work, dicoms)
    test_output_options(args.image, work, dicoms)
    test_supplementary_outputs_without_qsm(args.image, work, dicoms)

    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)

    return report()


if __name__ == "__main__":
    sys.exit(main())
