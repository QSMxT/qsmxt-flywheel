#!/usr/bin/env python3
"""Run the gear on real scanner DICOMs and check the reconstruction is sane.

The data is the QSMxT test dataset on OSF (https://osf.io/ru43c/), which is
public and needs no credentials: a single-echo 1 mm isotropic Siemens GRE, as
separate magnitude and phase DICOM zips — exactly the two inputs this gear
takes.

    python3 tests/test_real_data.py [--image qsmxt_flywheel:test]

The synthetic phantom in test_gear.py has a known answer and runs anywhere;
this has neither, so the checks here are the ones you can make without ground
truth — that the pipeline produced a brain-shaped mask and susceptibility
values in a physiological range, rather than zeros, NaNs, or a collapsed mask.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import nibabel as nib

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gearlib import check, extract, report, run_gear  # noqa: E402

# https://osf.io/ru43c/ -> qmenta-test-files/
OSF_NODE = "https://osf.io/ru43c/"
DOWNLOADS = {
    "mag.zip": "https://osf.io/download/guje9/",
    "phs.zip": "https://osf.io/download/9zfgr/",
}
# The acquisition is 224x224x160 at 1 mm.
EXPECTED_SHAPE = (224, 224, 160)


def fetch(cache_dir):
    """Download the test data, reusing anything already cached."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    for name, url in DOWNLOADS.items():
        target = cache_dir / name
        if target.is_file() and target.stat().st_size > 0:
            print(f"  cached  {name} ({target.stat().st_size / 1e6:.1f} MB)")
            continue
        print(f"  fetching {name} from {url}")
        subprocess.run(["curl", "-fsSL", "--retry", "3", "--retry-delay", "5",
                        "-o", str(target), url], check=True)
        print(f"  got      {name} ({target.stat().st_size / 1e6:.1f} MB)")
    return cache_dir / "mag.zip", cache_dir / "phs.zip"


def test_real_acquisition(image, work, mag_zip, phs_zip):
    print(f"\nA default run on real DICOMs from {OSF_NODE}:")
    # Defaults throughout — this is what a user gets out of the box.
    out, result = run_gear(image, work, mag_zip, phs_zip)
    if not check(result.returncode == 0, f"gear exits 0 (got {result.returncode})"):
        return
    check((out / "qsm.zip").is_file(), "qsm.zip written")
    check((out / "qsmxt.log").is_file(), "qsmxt.log written")

    tmp = work / "extract"
    chimap_path = extract(out / "qsm.zip", "_Chimap.nii", tmp)
    mask_path = extract(out / "qsm.zip", "_mask.nii", tmp)
    check(extract(out / "qsm.zip", "methods.md", tmp) is not None,
          "methods.md written, citing what ran")
    if not check(chimap_path is not None and mask_path is not None,
                 "qsm.zip contains a Chimap and a mask"):
        return

    chimap = np.asarray(nib.load(chimap_path).dataobj)
    mask = np.asarray(nib.load(mask_path).dataobj).astype(bool)

    check(chimap.shape == EXPECTED_SHAPE,
          f"Chimap is on the acquired grid {EXPECTED_SHAPE} (got {chimap.shape})")
    check(np.isfinite(chimap).all(), "Chimap is all finite")

    # A mask that swallowed the whole FOV or collapsed to nothing means the
    # masking stage failed, whatever the susceptibility values look like.
    fraction = float(mask.mean())
    check(0.05 < fraction < 0.60,
          f"mask covers a plausible fraction of the FOV ({fraction:.1%})")

    inside = chimap[mask]
    check(inside.size > 0 and np.any(inside != 0), "Chimap is nonzero inside the mask")
    if inside.size == 0:
        return

    # Referencing is to the in-mask mean by default, so it should sit at zero.
    check(abs(float(inside.mean())) < 1e-3,
          f"susceptibility is referenced to the mask mean ({inside.mean():+.5f} ppm)")

    # Brain tissue spans roughly -0.1..+0.2 ppm; anything far outside that band
    # means the scaling or the inversion went wrong, not that the brain is odd.
    spread = float(inside.std())
    check(0.005 < spread < 0.1,
          f"in-mask spread is physiological ({spread:.4f} ppm std)")
    low, high = np.percentile(inside, [1, 99])
    check(-0.25 < low < 0 and 0 < high < 0.35,
          f"in-mask 1st-99th percentile is physiological "
          f"({low:+.3f} to {high:+.3f} ppm)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="qsmxt_flywheel:test")
    parser.add_argument("--cache-dir", default=None,
                        help="where to keep the downloaded DICOMs (default: a temp dir)")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="qsmxt-real-data-"))
    cache = Path(args.cache_dir) if args.cache_dir else work / "cache"
    print(f"Image:       {args.image}")
    print(f"Working dir: {work}")
    print(f"Test data:   {cache}")

    mag_zip, phs_zip = fetch(cache)
    test_real_acquisition(args.image, work, mag_zip, phs_zip)

    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    return report()


if __name__ == "__main__":
    sys.exit(main())
