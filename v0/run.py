#!/usr/bin/env python3
"""Flywheel gear wrapper around QSMxT v9.

Extracts the magnitude/phase DICOM inputs, converts them to BIDS, runs the QSM
pipeline, and packages the results back into the gear output directory.
"""

import os
import shlex
import shutil
import subprocess
import sys
import zipfile as zf
from pathlib import Path

import flywheel

WORK = Path(os.environ.get("QSMXT_WORK_DIR", "/work"))
DICOM_DIR = WORK / "0_dicoms"
BIDS_DIR = WORK / "1_bids"
QSM_DIR = WORK / "2_qsm"
DERIVATIVES = QSM_DIR / "derivatives" / "qsmxt"

# ── What each algorithm choice implies ────────────────────────────────────────
#
# Some dipole inversions do their own background field removal, so QSMxT skips
# the standalone BFR stage entirely and feeds them the total (unwrapped) field.
# Passing --bf-algorithm alongside one of these has no effect, so the gear drops
# it and says so rather than letting the setting silently do nothing.
SELF_BFR_INVERSIONS = {
    "tgv",       # TGV-QSM reconstructs from the total field
    "qsmart",    # two-stage, with its own SDF background filtering
    "autoqsm",   # deep learning, single-step from the total field
    "nextqsm",   # deep learning, single-step from the total field
    "iqsm",      # deep learning, end-to-end from wrapped phase
    "iqsm-plus", # deep learning, end-to-end from wrapped phase
}

# These reconstruct susceptibility straight from wrapped phase, so field mapping
# (unwrapping and echo combination) is skipped as well as background removal.
PHASE_TO_CHI_INVERSIONS = {"iqsm", "iqsm-plus"}

# MEDI becomes self-BFR only when its SMV deconvolution is enabled.
MEDI_SMV_IS_SELF_BFR = "medi"

# Background field removers that also replace phase unwrapping.
SELF_UNWRAP_BF = {"iqfm"}

# Methods whose model weights are downloaded from Hugging Face on first use.
# None of these are offered in the manifest enums; they are reachable only via
# qsmxt_cmd_args, and only work where the gear has outbound network access.
DEEP_LEARNING_METHODS = {
    "xqsm", "qsmnet", "qsmnet-plus", "autoqsm", "qsmgan", "ir2qsm", "lpcnn",
    "modl-qsm", "nextqsm", "iqsm", "iqsm-plus",          # dipole inversion
    "bfrnet", "iqfm",                                    # background removal
    "hd-bet",                                            # masking
    "susep-net", "chi-sepnet",                           # chi-separation
}

# Gear config key -> qsmxt run flag. "auto" means "leave it to QSMxT's own
# default" — the gear passes no flag at all rather than pinning a value that
# would then survive a QSMxT upgrade that changed the default.
ALGORITHM_FLAGS = [
    ("mask_preset", "--mask-preset"),
    ("masking_input", "--masking-input"),
    ("unwrapping_algorithm", "--unwrapping-algorithm"),
    ("b0_estimation", "--b0-estimation"),
    ("bf_algorithm", "--bf-algorithm"),
    ("qsm_algorithm", "--qsm-algorithm"),
    ("qsm_reference", "--qsm-reference"),
]


def log(msg):
    print(f"[qsmxt-gear] {msg}", flush=True)


def warn(msg):
    print(f"[qsmxt-gear] WARNING: {msg}", file=sys.stderr, flush=True)


def run_cmd(cmd, check=True):
    """Run a command, echoing it first, and abort the gear if it fails."""
    log("$ " + " ".join(shlex.quote(str(c)) for c in cmd))
    result = subprocess.run([str(c) for c in cmd])
    if result.returncode != 0 and check:
        raise SystemExit(result.returncode)
    return result.returncode


def resolve(config, key):
    """An option's value, or None when it is left on "auto"."""
    value = str(config.get(key, "auto")).strip()
    return value if value and value != "auto" else None


def extra_arg_value(extra_args, flag):
    """Read a flag's value out of the free-form qsmxt_cmd_args, if it's there."""
    for i, token in enumerate(extra_args):
        if token == flag and i + 1 < len(extra_args):
            return extra_args[i + 1]
        if token.startswith(flag + "="):
            return token.split("=", 1)[1]
    return None


def build_qsmxt_args(config):
    """Turn the gear configuration into a `qsmxt run` argument list."""
    extra_args = shlex.split(str(config.get("qsmxt_cmd_args", "")))
    settings = {key: resolve(config, key) for key, _ in ALGORITHM_FLAGS}

    # qsmxt_cmd_args is applied last and wins, so validate against what will
    # actually run rather than against what the dropdowns say.
    for key, flag in ALGORITHM_FLAGS:
        override = extra_arg_value(extra_args, flag)
        if override is not None:
            settings[key] = override

    inversion = settings.get("qsm_algorithm") or "rts"  # QSMxT's default
    bf_algorithm = settings.get("bf_algorithm")
    medi_smv = bool(config.get("medi_smv", False))

    # Background removal: drop the setting when the inversion handles it itself.
    self_bfr = inversion in SELF_BFR_INVERSIONS or (
        inversion == MEDI_SMV_IS_SELF_BFR and medi_smv
    )
    if self_bfr and settings.get("bf_algorithm"):
        reason = (
            "MEDI with SMV deconvolution"
            if inversion == MEDI_SMV_IS_SELF_BFR
            else inversion
        )
        warn(
            f"{reason} performs its own background field removal, so the "
            f"background field removal step is skipped — ignoring "
            f"bf_algorithm='{settings['bf_algorithm']}'."
        )
        settings["bf_algorithm"] = None

    # Field mapping: end-to-end inversions and iQFM start from wrapped phase.
    starts_from_phase = None
    if inversion in PHASE_TO_CHI_INVERSIONS:
        starts_from_phase = inversion
    elif bf_algorithm in SELF_UNWRAP_BF and not self_bfr:
        starts_from_phase = bf_algorithm
    if starts_from_phase:
        for key in ("unwrapping_algorithm", "b0_estimation"):
            if settings.get(key):
                warn(
                    f"{starts_from_phase} produces its field directly from "
                    f"wrapped phase, so field mapping is skipped — ignoring "
                    f"{key}='{settings[key]}'."
                )
                settings[key] = None

    # Deep learning: usable, but only where the gear can reach Hugging Face.
    dl_in_use = sorted(
        {v for v in settings.values() if v in DEEP_LEARNING_METHODS}
    )
    if dl_in_use:
        warn(
            "Deep-learning method(s) selected (" + ", ".join(dl_in_use) + "). "
            "Model weights are downloaded from Hugging Face on first use, so "
            "this run needs outbound network access and will fail without it."
        )

    args = []
    for key, flag in ALGORITHM_FLAGS:
        # Values that came from qsmxt_cmd_args are already in extra_args.
        if settings.get(key) and extra_arg_value(extra_args, flag) is None:
            args += [flag, settings[key]]

    if medi_smv and inversion == MEDI_SMV_IS_SELF_BFR:
        args.append("--medi-smv")
    elif medi_smv:
        warn(f"medi_smv only applies to the MEDI inversion; ignoring it for '{inversion}'.")

    args += ["--phase-offset-removal",
             "true" if config.get("phase_offset_removal", True) else "false"]
    if config.get("bipolar_correction", False):
        args.append("--bipolar-correction")
    args.append("--inhomogeneity-correction" if config.get("inhomogeneity_correction", True)
                else "--no-inhomogeneity-correction")

    num_echoes = int(config.get("num_echoes", 0) or 0)
    if num_echoes > 0:
        args += ["--num-echoes", str(num_echoes)]

    obliquity = float(config.get("obliquity_threshold", -1))
    if obliquity >= 0:
        args += ["--obliquity-threshold", str(obliquity)]

    for key, flag in (("include_pattern", "--include"), ("exclude_pattern", "--exclude")):
        pattern = str(config.get(key, "")).strip()
        if pattern:
            args += [flag] + shlex.split(pattern)

    if config.get("no_qsm", False):
        args.append("--no-qsm")
    for key, flag in (
        ("do_swi", "--do-swi"),
        ("do_t2starmap", "--do-t2starmap"),
        ("do_r2starmap", "--do-r2starmap"),
    ):
        if config.get(key, False):
            args.append(flag)

    if config.get("do_chisep", False):
        args.append("--do-chisep")
        chisep = resolve(config, "chisep_algorithm")
        if chisep:
            args += ["--chisep", chisep]

    if config.get("export_dicom", False):
        args.append("--export-dicom")
        args += ["--source-dicom", str(DICOM_DIR)]

    if config.get("clean_intermediates", False):
        args.append("--clean-intermediates")

    return args + extra_args


def archive(src_dir, out_zip, skip_top_level=()):
    """Zip a directory, optionally leaving out some top-level entries."""
    src_dir = Path(src_dir)
    if not src_dir.is_dir():
        return False
    wrote_anything = False
    with zf.ZipFile(out_zip, "w", zf.ZIP_DEFLATED) as zip_obj:
        for path in sorted(src_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(src_dir)
            if relative.parts[0] in skip_top_level:
                continue
            zip_obj.write(path, relative)
            wrote_anything = True
    if not wrote_anything:
        Path(out_zip).unlink(missing_ok=True)
    return wrote_anything


def flywheel_run():
    with flywheel.GearContext() as context:
        config = context.config
        mag_dicom_zip = context.get_input_path("magnitude")
        phs_dicom_zip = context.get_input_path("phase")
        out_dir = Path(context.output_dir)

    log(subprocess.run(["qsmxt", "--version"], capture_output=True, text=True).stdout.strip())

    # Resolve the configuration before doing any work, so a bad setting fails
    # immediately rather than after the DICOM conversion.
    qsm_args = build_qsmxt_args(config)

    # Extract the DICOMs. QSMxT's converter classifies series automatically, so
    # magnitude and phase go into one tree and it sorts them out.
    for zip_path, name in ((mag_dicom_zip, "magnitude"), (phs_dicom_zip, "phase")):
        with zf.ZipFile(zip_path, "r") as zip_obj:
            zip_obj.extractall(DICOM_DIR / name)

    run_cmd(["qsmxt", "dicom-convert", DICOM_DIR, BIDS_DIR])
    # A report on what the pipeline will do with this dataset; not a gate.
    run_cmd(["qsmxt", "validate", BIDS_DIR], check=False)
    # Collect the outputs either way: a failed run still leaves a log and the
    # intermediates of whatever stages did complete, which is what you need to
    # work out why it failed.
    returncode = run_cmd(["qsmxt", "run", BIDS_DIR, QSM_DIR] + qsm_args, check=False)

    # Package the results. The workflow directory holds the cached intermediates;
    # it goes into its own archive so the main one stays small.
    if not archive(DERIVATIVES, out_dir / "qsm.zip", skip_top_level=("workflow",)):
        warn(f"No QSM outputs found under {DERIVATIVES}")
    # Also surface the pipeline log on its own, so it can be read without
    # downloading and unpacking an archive.
    if (DERIVATIVES / "qsmxt.log").is_file():
        shutil.copy2(DERIVATIVES / "qsmxt.log", out_dir / "qsmxt.log")
    archive(DERIVATIVES / "workflow", out_dir / "workflow.zip")
    if config.get("save_bids", False):
        archive(BIDS_DIR, out_dir / "bids.zip")

    if returncode != 0:
        warn(f"qsmxt run failed (exit {returncode}); inspect qsmxt.log and workflow.zip.")
        raise SystemExit(returncode)
    log("Done.")


if __name__ == "__main__":
    flywheel_run()
