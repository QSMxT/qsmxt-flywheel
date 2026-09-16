#!/usr/bin/env python3
"""Check the gear's configuration handling. Runs inside the gear container, so
that every command it builds is validated against the real qsmxt binary.

    docker run --rm -v "$PWD/tests:/tests" <image> python3 /tests/test_config.py
"""

import json
import re
import subprocess
import sys
import tempfile
import types
from pathlib import Path

GEAR = Path("/flywheel/v0")

sys.modules.setdefault("flywheel", types.ModuleType("flywheel"))
sys.path.insert(0, str(GEAR))
import run as gear  # noqa: E402

MANIFEST = json.loads((GEAR / "manifest.json").read_text())
DEFAULTS = {key: spec["default"] for key, spec in MANIFEST["config"].items()}

failures = []


def check(condition, message):
    if condition:
        print(f"  ok   {message}")
    else:
        print(f"  FAIL {message}")
        failures.append(message)


def build(**overrides):
    config = dict(DEFAULTS)
    config.update(overrides)
    return gear.build_qsmxt_args(config)


def qsmxt_accepts(args):
    """Does the real qsmxt accept this argument list?"""
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            ["qsmxt", "run", tmp, f"{tmp}/out", "--dry"] + args,
            capture_output=True, text=True,
        )
    rejected = ("unexpected", "invalid value", "not provided", "cannot be used",
                "requires a value")
    if "error:" in result.stderr and any(r in result.stderr for r in rejected):
        return result.stderr.strip().splitlines()[0]
    return None


def test_every_enum_value_is_accepted():
    print("\nEvery manifest enum value produces a command qsmxt accepts:")
    for key, spec in MANIFEST["config"].items():
        for value in spec.get("enum", []):
            if value == "auto":
                continue
            extra = {"do_chisep": True} if key == "chisep_algorithm" else {}
            error = qsmxt_accepts(build(**{key: value}, **extra))
            check(error is None, f"{key}={value}" + (f" -> {error}" if error else ""))


def test_option_combinations_are_accepted():
    print("\nOption combinations produce commands qsmxt accepts:")
    combinations = {
        "all stages set": {
            "mask_preset": "bet", "masking_input": "magnitude-first",
            "unwrapping_algorithm": "laplacian", "b0_estimation": "linear-fit",
            "bf_algorithm": "pdf", "qsm_algorithm": "medi", "qsm_reference": "none",
        },
        "supplementary outputs": {
            "do_swi": True, "do_t2starmap": True, "do_r2starmap": True,
            "do_chisep": True, "chisep_algorithm": "decompose", "export_dicom": True,
        },
        "run selection": {
            "include_pattern": "*acq-QSM* sub-01*", "exclude_pattern": "*acq-SWI*",
            "num_echoes": 4, "obliquity_threshold": 10,
        },
        "toggles inverted": {
            "phase_offset_removal": False, "inhomogeneity_correction": False,
            "bipolar_correction": True, "clean_intermediates": True, "no_qsm": True,
        },
        "extra args": {"qsmxt_cmd_args": "--vsharp-max-radius 20 --tkd-threshold 0.15"},
    }
    for name, overrides in combinations.items():
        error = qsmxt_accepts(build(**overrides))
        check(error is None, name + (f" -> {error}" if error else ""))


def test_self_bfr_inversions_drop_the_bfr_setting():
    """The inversions that do their own background removal must not also be
    handed a --bf-algorithm, which qsmxt would ignore."""
    print("\nInversions that include background field removal:")
    for inversion in ("tgv", "qsmart"):
        args = build(qsm_algorithm=inversion, bf_algorithm="pdf")
        check("--bf-algorithm" not in args, f"{inversion} + bf_algorithm -> bf dropped")

    args = build(qsm_algorithm="medi", medi_smv=True, bf_algorithm="vsharp")
    check("--bf-algorithm" not in args and "--medi-smv" in args,
          "medi + medi_smv + bf_algorithm -> bf dropped, --medi-smv kept")

    args = build(qsm_algorithm="medi", bf_algorithm="vsharp")
    check("--bf-algorithm" in args and "--medi-smv" not in args,
          "medi without medi_smv -> bf kept")

    args = build(qsm_algorithm="rts", medi_smv=True)
    check("--medi-smv" not in args, "medi_smv on a non-MEDI inversion -> dropped")


def test_phase_to_chi_methods_drop_field_mapping():
    """iQSM/iQSM+ and iQFM start from wrapped phase, so unwrapping settings
    must not be passed alongside them."""
    print("\nMethods that reconstruct from wrapped phase:")
    for extra in ("--qsm-algorithm iqsm", "--qsm-algorithm iqsm-plus", "--bf-algorithm iqfm"):
        args = build(unwrapping_algorithm="romeo", b0_estimation="linear-fit",
                     qsmxt_cmd_args=extra)
        dropped = "--unwrapping-algorithm" not in args and "--b0-estimation" not in args
        check(dropped, f"{extra} -> field-mapping settings dropped")


def test_extra_args_win():
    print("\nqsmxt_cmd_args overrides the dropdowns:")
    args = build(qsm_algorithm="rts", qsmxt_cmd_args="--qsm-algorithm tkd")
    check(args.count("--qsm-algorithm") == 1 and "tkd" in args and "rts" not in args,
          "--qsm-algorithm given twice -> only the extra-args value survives")


def test_auto_passes_no_flag():
    print("\n'auto' leaves the choice to qsmxt:")
    args = build()
    for _, flag in gear.ALGORITHM_FLAGS:
        check(flag not in args, f"all-auto config passes no {flag}")


def test_manifest_and_run_py_agree():
    print("\nManifest and run.py agree:")
    manifest_keys = set(MANIFEST["config"])
    source = (GEAR / "run.py").read_text()
    read_keys = set(re.findall(r'config\.get\("([a-z0-9_]+)"', source))
    read_keys |= set(re.findall(r'\("([a-z0-9_]+)", "--[a-z0-9-]+"\)', source))
    read_keys |= {"chisep_algorithm"}
    check(not manifest_keys - read_keys,
          f"every manifest option is read by run.py (unread: {sorted(manifest_keys - read_keys)})")
    check(not read_keys - manifest_keys,
          f"every option run.py reads is in the manifest (missing: {sorted(read_keys - manifest_keys)})")

    # Gear versions are <gear-semver>_<qsmxt-version>, as the accepted gears in
    # the Flywheel Gear Exchange use (e.g. bids-mriqc 2.1.4_24.0.2).
    version = MANIFEST["version"]
    match = re.fullmatch(r"(\d+\.\d+\.\d+)_(.+)", version)
    check(match is not None,
          f"version is <gear-semver>_<qsmxt-version> (got {version!r})")
    if match:
        installed = subprocess.run(["qsmxt", "--version"], capture_output=True, text=True)
        check(installed.stdout.startswith(f"qsmxt {match.group(2)}"),
              f"manifest names QSMxT {match.group(2)}, and that is what the image has "
              f"({installed.stdout.splitlines()[0]})")

    image = MANIFEST["custom"]["gear-builder"]["image"]
    check(image.endswith(":" + version),
          f"gear-builder image tag matches the manifest version ({image})")


# The Gear Exchange requires these on top of what a gear needs to merely run.
# Sources: the gear spec's manifest.schema.json and the Exchange CONTRIBUTING.md.
SCHEMA_REQUIRED = ["author", "config", "description", "inputs", "label", "license",
                   "name", "source", "url", "version"]
LICENSE_ENUM = ["AGPL-3.0", "GPL-2.0", "GPL-3.0", "LGPL-2.1", "LGPL-3.0", "LGPL-2.0", "NGPL"]
CLASSIFICATION_KEYS = ["function", "modality", "organ", "species", "therapeutic_area"]
FUNCTION_ENUM = [
    "Conversion", "Curation", "Quality Assurance", "Utility", "Export", "Report",
    "Image Processing - Cardiac", "Image Processing - Diffusion",
    "Image Processing - Digital Pathology", "Image Processing - Functional",
    "Image Processing - Musculoskeletal", "Image Processing - Other",
    "Image Processing - Perfusion", "Image Processing - Segmentation",
    "Image Processing - Spectroscopy", "Image Processing - Structural", "Other",
]


def test_manifest_is_exchange_ready():
    print("\nManifest meets the Gear Exchange requirements:")
    missing = [key for key in SCHEMA_REQUIRED if key not in MANIFEST]
    check(not missing, f"every schema-required field is present (missing: {missing})")
    check(MANIFEST["license"] in LICENSE_ENUM,
          f"license is one the schema allows ({MANIFEST['license']})")
    check(re.fullmatch(r".+ <[^@]+@[^>]+>", MANIFEST.get("maintainer", "")) is not None,
          f"maintainer is 'Name <email>' ({MANIFEST.get('maintainer')!r})")

    classification = MANIFEST["custom"]["flywheel"].get("classification", {})
    for key in CLASSIFICATION_KEYS:
        values = classification.get(key)
        check(isinstance(values, list) and values and all(isinstance(v, str) for v in values),
              f"classification.{key} is a non-empty list of strings ({values!r})")
    check(all(f in FUNCTION_ENUM for f in classification.get("function", [])),
          f"classification.function uses values the spec defines "
          f"({classification.get('function')})")
    check(bool(MANIFEST["custom"]["flywheel"].get("suite")), "a suite is set")


def main():
    for test in (
        test_auto_passes_no_flag,
        test_every_enum_value_is_accepted,
        test_option_combinations_are_accepted,
        test_self_bfr_inversions_drop_the_bfr_setting,
        test_phase_to_chi_methods_drop_field_mapping,
        test_extra_args_win,
        test_manifest_and_run_py_agree,
        test_manifest_is_exchange_ready,
    ):
        test()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("All configuration checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
