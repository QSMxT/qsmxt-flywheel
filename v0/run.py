#!/usr/bin/env python3

import shutil
import subprocess
import glob
import os

import zipfile as zf
import flywheel

def flywheel_run():

    # load inputs and configuration from FlyWheel context
    with flywheel.GearContext() as context:
        config = context.config
        mag_dicom_zip = context.get_input_path('magnitude')
        phs_dicom_zip = context.get_input_path('phase')
        out_dir = context.output_dir

    # extract DICOMs
    with zf.ZipFile(mag_dicom_zip, 'r') as zipObj:
        zipObj.extractall('/0_dicoms/magnitude')

    with zf.ZipFile(phs_dicom_zip, 'r') as zipObj:
        zipObj.extractall('/0_dicoms/phase')

    # sort DICOMs
    complete_process = subprocess.run([
        "python3",
        "/opt/QSMxT/run_0_dicomSort.py",
        "/0_dicoms",
        "/1_dicoms-sorted"
    ])

    # convert to BIDS
    complete_process = subprocess.run([
        "python3",
        "/opt/QSMxT/run_1_dicomConvert.py",
        "/1_dicoms-sorted/",
        "/2_bids",
        "--auto_yes"
    ])

    # do QSM
    complete_process = subprocess.run([
        "python3",
        "/opt/QSMxT/run_2_qsm.py",
        "/2_bids",
        "/3_qsm",
        "--premade", str(config['premade']),
        "--non_interactive"
    ])

    # collect workflow in zip and delete folder
    shutil.make_archive(os.path.join(out_dir, 'workflow'), 'zip', '/3_qsm/workflow_qsm')
    shutil.rmtree(os.path.join(out_dir, '/3_qsm/workflow_qsm'))

    # collect remaining QSMxT outputs
    shutil.make_archive(os.path.join(out_dir, 'qsm'), 'zip', '/3_qsm/')
    
    # collect crash outputs
    crash_files = glob.glob("/flywheel/v0/crash*.pklz")
    if crash_files:
        with zf.ZipFile(os.path.join(out_dir, 'crashes.zip'), 'w') as zipObj:
            for crash in crash_files:
                zipObj.write(crash, os.path.basename(crash))
        print("CRASHES OCCURRED! Inspect workflow.zip and crashes.zip...")
        exit(1)

    exit(0)


if __name__ == "__main__":
    flywheel_run()

