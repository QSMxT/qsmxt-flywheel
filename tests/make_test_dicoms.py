#!/usr/bin/env python3
"""Generate a tiny synthetic multi-echo GRE acquisition as DICOM, for testing
the gear end to end without shipping patient data.

Writes magnitude and phase series (one SeriesInstanceUID each, all echoes
inside, as Siemens exports them) and zips them the way the gear's inputs
arrive:

    python3 tests/make_test_dicoms.py <output_dir>
    -> <output_dir>/mag.zip, <output_dir>/phs.zip

The phantom is an ellipsoid with two susceptibility sources and a smooth
background field, so masking, unwrapping, background field removal and dipole
inversion all have something real to do. It is not anatomically meaningful and
the reconstructed values are not expected to be accurate - this exercises the
plumbing, not the physics.
"""

import sys
import zipfile
from pathlib import Path

import numpy as np
import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid

SHAPE = (64, 64, 48)          # voxels
VOXEL_MM = (1.5, 1.5, 1.5)
ECHO_TIMES_MS = (5.0, 10.0, 15.0, 20.0)
FIELD_STRENGTH_T = 3.0
GAMMA_HZ_PER_T = 42.577478e6
UINT12_MAX = 4095
PROTOCOL = "gre_qsm_test"


def dipole_kernel(shape, voxel_mm):
    """The dipole response in k-space, with B0 along +z."""
    ky, kx, kz = np.meshgrid(
        *[np.fft.fftfreq(n, d) for n, d in zip(shape, voxel_mm)], indexing="ij"
    )
    k2 = kx**2 + ky**2 + kz**2
    with np.errstate(invalid="ignore", divide="ignore"):
        kernel = 1.0 / 3.0 - (kz**2) / k2
    kernel[k2 == 0] = 0.0
    return kernel


def phantom():
    """Susceptibility map (ppm), tissue mask, and a smooth background field."""
    nx, ny, nz = SHAPE
    x, y, z = np.meshgrid(
        np.linspace(-1, 1, nx), np.linspace(-1, 1, ny), np.linspace(-1, 1, nz),
        indexing="ij",
    )

    tissue = (x**2 / 0.72**2 + y**2 / 0.62**2 + z**2 / 0.68**2) <= 1.0

    chi = np.zeros(SHAPE)
    chi[((x - 0.22) ** 2 + y**2 + z**2) < 0.14**2] = 0.06      # paramagnetic
    chi[((x + 0.24) ** 2 + (y - 0.1) ** 2 + z**2) < 0.12**2] = -0.04  # diamagnetic
    chi *= tissue

    # A smooth field of external origin for background removal to strip out.
    background_ppm = 0.55 * (z + 0.35 * x - 0.2 * y**2)

    return chi, tissue, background_ppm


def simulate():
    """Magnitude and wrapped phase for every echo."""
    chi, tissue, background_ppm = phantom()

    kernel = dipole_kernel(SHAPE, VOXEL_MM)
    local_ppm = np.real(np.fft.ifftn(np.fft.fftn(chi) * kernel))
    total_ppm = (local_ppm + background_ppm) * tissue

    rng = np.random.default_rng(0)
    texture = 1.0 + 0.12 * np.sin(6.0 * np.linspace(0, np.pi, SHAPE[0]))[:, None, None]
    proton_density = tissue * texture
    r2star_hz = 18.0 + 25.0 * (chi > 0)

    magnitudes, phases = [], []
    for te_ms in ECHO_TIMES_MS:
        te = te_ms / 1000.0
        mag = proton_density * np.exp(-r2star_hz * te)
        mag = mag + 0.01 * rng.standard_normal(SHAPE) * tissue
        magnitudes.append(np.clip(mag, 0, None))

        # ppm -> Hz -> radians, then wrapped as the scanner would store it.
        field_hz = total_ppm * 1e-6 * GAMMA_HZ_PER_T * FIELD_STRENGTH_T
        phase = 2.0 * np.pi * field_hz * te
        phases.append(np.angle(np.exp(1j * phase)) * tissue)

    return magnitudes, phases


def to_uint16(volume, lo, hi):
    scaled = (volume - lo) / (hi - lo) * UINT12_MAX
    return np.clip(np.rint(scaled), 0, UINT12_MAX).astype(np.uint16)


def write_series(out_dir, volumes, image_type_marker, study_uid, series_number):
    """One SeriesInstanceUID holding every echo, one file per slice per echo."""
    out_dir.mkdir(parents=True, exist_ok=True)
    series_uid = generate_uid()
    frame_of_reference_uid = generate_uid()
    nx, ny, nz = SHAPE
    instance = 0

    for echo_index, (te_ms, volume) in enumerate(zip(ECHO_TIMES_MS, volumes), start=1):
        if image_type_marker == "P":
            pixels = to_uint16(volume, -np.pi, np.pi)
        else:
            pixels = to_uint16(volume, 0.0, max(float(volume.max()), 1e-6))

        for slice_index in range(nz):
            instance += 1
            ds = Dataset()
            ds.file_meta = FileMetaDataset()
            ds.file_meta.MediaStorageSOPClassUID = MRImageStorage
            ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
            ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
            ds.file_meta.ImplementationClassUID = generate_uid()

            ds.SOPClassUID = MRImageStorage
            ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
            ds.StudyInstanceUID = study_uid
            ds.SeriesInstanceUID = series_uid
            ds.FrameOfReferenceUID = frame_of_reference_uid

            ds.PatientName = "Test^Phantom"
            ds.PatientID = "QSMXT_TEST"
            ds.PatientBirthDate = ""
            ds.PatientSex = "O"
            ds.StudyDate = "20260101"
            ds.StudyTime = "120000"
            ds.SeriesDate = ds.StudyDate
            ds.SeriesTime = ds.StudyTime
            ds.AcquisitionDate = ds.StudyDate
            ds.AcquisitionTime = ds.StudyTime
            ds.StudyID = "1"
            ds.AccessionNumber = ""
            ds.Modality = "MR"
            ds.Manufacturer = "SIEMENS"
            ds.ManufacturerModelName = "Synthetic"

            ds.SeriesDescription = PROTOCOL
            ds.ProtocolName = PROTOCOL
            ds.SeriesNumber = series_number
            ds.InstanceNumber = instance
            ds.ImageType = ["ORIGINAL", "PRIMARY", image_type_marker, "ND"]

            ds.MagneticFieldStrength = FIELD_STRENGTH_T
            ds.EchoTime = te_ms
            ds.EchoNumbers = echo_index
            ds.RepetitionTime = 30.0
            ds.FlipAngle = 15.0
            ds.ScanningSequence = "GR"
            ds.SequenceVariant = "SP"
            ds.MRAcquisitionType = "3D"

            ds.Rows = ny
            ds.Columns = nx
            ds.PixelSpacing = [VOXEL_MM[1], VOXEL_MM[0]]
            ds.SliceThickness = VOXEL_MM[2]
            ds.SpacingBetweenSlices = VOXEL_MM[2]
            ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            ds.ImagePositionPatient = [
                -0.5 * nx * VOXEL_MM[0],
                -0.5 * ny * VOXEL_MM[1],
                (slice_index - 0.5 * nz) * VOXEL_MM[2],
            ]
            ds.SliceLocation = ds.ImagePositionPatient[2]

            ds.SamplesPerPixel = 1
            ds.PhotometricInterpretation = "MONOCHROME2"
            ds.BitsAllocated = 16
            ds.BitsStored = 12
            ds.HighBit = 11
            ds.PixelRepresentation = 0
            if image_type_marker == "P":
                # Siemens phase convention: 0..4095 spans -pi..pi.
                ds.RescaleIntercept = -np.pi
                ds.RescaleSlope = 2 * np.pi / UINT12_MAX
                ds.RescaleType = "rad"
            ds.PixelData = pixels[:, :, slice_index].T.tobytes()

            name = f"{image_type_marker}_e{echo_index}_s{slice_index:03d}.dcm"
            pydicom.dcmwrite(out_dir / name, ds, write_like_original=False)

    return instance


def zip_dir(src_dir, out_zip):
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zip_obj:
        for path in sorted(src_dir.rglob("*")):
            if path.is_file():
                zip_obj.write(path, path.relative_to(src_dir))


def main():
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "test-data")
    out_dir.mkdir(parents=True, exist_ok=True)

    magnitudes, phases = simulate()
    study_uid = generate_uid()

    for marker, volumes, series_number, stem in (
        ("M", magnitudes, 1, "mag"),
        ("P", phases, 2, "phs"),
    ):
        series_dir = out_dir / stem
        count = write_series(series_dir, volumes, marker, study_uid, series_number)
        zip_dir(series_dir, out_dir / f"{stem}.zip")
        size_mb = (out_dir / f"{stem}.zip").stat().st_size / 1e6
        print(f"{stem}.zip: {count} files, {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
