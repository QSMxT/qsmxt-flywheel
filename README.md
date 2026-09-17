# qsmxt-flywheel

A [Flywheel](https://flywheel.io) gear wrapping [QSMxT](https://qsmxt.github.io/QSMxT/).
It takes magnitude and phase DICOMs, converts them to BIDS, and reconstructs a
quantitative susceptibility map for every gradient-echo acquisition it finds.

Built on QSMxT **v9.20.0**.

## What the gear does

1. Extracts the magnitude and phase `.zip` inputs into one DICOM tree.
2. `qsmxt dicom-convert` — classifies the series automatically and writes BIDS.
3. `qsmxt validate` — reports what the pipeline will do with the dataset.
4. `qsmxt run` — masking → field mapping → background field removal → dipole
   inversion → referencing, with the algorithms chosen in the gear config.

Outputs:

| File | Contents |
| --- | --- |
| `qsm.zip` | `derivatives/qsmxt/` — the susceptibility maps, `references.txt` citing the exact methods used, and `qsmxt.log` |
| `workflow.zip` | Cached intermediates from each stage (omit with `clean_intermediates`) |
| `bids.zip` | The converted BIDS dataset (only with `save_bids`) |
| `qsmxt.log` | The pipeline log on its own, for reading without unpacking anything |

## Configuration

Every algorithm option defaults to `auto`, which passes no flag at all and
leaves the choice to QSMxT's own default for that stage. That way a QSMxT
upgrade that changes a default reaches the gear, instead of being pinned to
whatever the default was when the manifest was written.

### Per-stage algorithms

| Stage | Option | Choices |
| --- | --- | --- |
| Masking | `mask_preset` | `robust-threshold`, `bet`, `bet-and-phase` |
| | `masking_input` | `magnitude-first`, `magnitude`, `magnitude-last`, `phase-quality` |
| | `inhomogeneity_correction` | on/off |
| Field mapping | `unwrapping_algorithm` | `romeo`, `laplacian` |
| | `b0_estimation` | `weighted-avg`, `linear-fit` |
| | `phase_offset_removal`, `bipolar_correction` | on/off |
| Background field removal | `bf_algorithm` | `vsharp`, `pdf`, `lbv`, `ismv`, `sharp`, `resharp`, `harperella`, `iharperella` |
| Dipole inversion | `qsm_algorithm` | `rts`, `tv`, `tkd`, `tsvd`, `tgv`, `tikhonov`, `nltv`, `medi`, `tfi`, `ilsqr`, `qsmart`, `ndi`, `fansi`, `fansi-tgv`, `l1qsm`, `whqsm`, `hdqsm`, `amp-pe` |
| | `medi_smv`, `qsm_reference` | |

See the [algorithm reference](https://qsmxt.github.io/QSMxT/reference/algorithms/)
for what each one does.

### Inversions that include background field removal

Some reconstructions do their own background field removal, so QSMxT skips the
standalone stage. The gear knows which, and drops a conflicting `bf_algorithm`
with a warning in the log rather than letting the setting silently do nothing:

| Choice | Effect |
| --- | --- |
| `tgv` | Reconstructs from the total field; `bf_algorithm` does not apply |
| `qsmart` | Two-stage, with its own SDF background filtering; `bf_algorithm` does not apply |
| `medi` + `medi_smv` | MEDI's SMV deconvolution replaces the background removal stage |

The same holds for the deep-learning methods reachable through
`qsmxt_cmd_args`: `autoqsm` and `nextqsm` remove the background field themselves,
`iqsm` and `iqsm-plus` reconstruct end-to-end from wrapped phase (so field
mapping is skipped as well), and `--bf-algorithm iqfm` replaces phase unwrapping.

### Deep learning is not in the dropdowns

QSMxT v9 ships deep-learning masking (HD-BET), background field removal (BFRnet,
iQFM), dipole inversion (xQSM, QSMnet, NeXtQSM, iQSM, …) and source separation
(SUSEP-Net, χ-sepnet). None are offered as gear options, because their model
weights are downloaded from Hugging Face on first use: a gear running without
outbound network access would fail partway through, and the HD-BET weights are
CC-BY-NC-4.0, which does not suit a gear distributed for general use.

They still work where a site allows the egress — select one through
`qsmxt_cmd_args` (e.g. `--qsm-algorithm xqsm --tile-size 128`). The gear logs a
warning naming the method and the network requirement.

### Selecting acquisitions

`qsm_protocol_pattern` is gone; v9 filters on the BIDS key instead. A key looks
like `sub-01_ses-pre_acq-PROTOCOL_run-1_MEGRE`, so the scanner protocol name
appears as the `acq-` entity:

- `include_pattern`: `*acq-QSM*` — process only these
- `exclude_pattern`: `*acq-SWI*` — skip these

Both take space-separated globs. Leave them empty to process everything.

### Anything else

`qsmxt_cmd_args` is passed to `qsmxt run` after everything above and overrides
it — use it for per-algorithm parameters (`--vsharp-max-radius 20`,
`--tgv-iterations 1000`, …). Run `qsmxt run --help` or use `qsmxt tui`, which
prints the equivalent command as you configure it.

## Releasing

Cutting a GitHub release builds the image, tests it, and pushes it to **both**
Docker Hub and GHCR:

```bash
# 1. bump the version in two places and commit
#    - QSMXT_VERSION in qsm.Dockerfile
#    - version and custom.gear-builder.image in v0/manifest.json

# 2. tag the release with exactly the manifest version
gh release create 1.0.0_9.20.0 --generate-notes
```

The gear version is `<gear-semver>_<qsmxt-version>` — `1.0.0_9.20.0` is gear
1.0.0 wrapping QSMxT 9.20.0. This is the convention the accepted gears in the
Flywheel Gear Exchange use (`bids-mriqc` is `2.1.4_24.0.2`), and it lets the
gear be re-released — a `run.py` fix, a manifest correction — without pretending
QSMxT changed. Bump the left half for gear changes and the right half to track a
QSMxT release.

That triggers [`.github/workflows/release.yml`](.github/workflows/release.yml),
which:

1. runs the full CI suite on the release commit — synthetic phantom *and* real
   scanner DICOMs — and publishes nothing if either fails;
2. derives the image tags from the release tag, and **refuses the release if the
   tag does not match `v0/manifest.json`** (Flywheel pulls whatever
   `custom.gear-builder.image` names, so a mismatch would upload a gear pointing
   at an image that does not exist);
3. builds once and pushes to both registries:

   | | |
   | --- | --- |
   | Docker Hub | `astewartau/qsmxt_flywheel:<version>` — what the manifest names, so this is the one Flywheel pulls |
   | GHCR | `ghcr.io/qsmxt/qsmxt-flywheel:<version>` |

   Both also get `:latest`, unless the release is marked as a prerelease;
4. pulls the published image back and re-runs the configuration checks against
   it, so a broken push cannot go unnoticed.

A `workflow_dispatch` run does the same thing, tagging from the manifest version
instead of a release tag — useful for re-pushing without cutting a release.

Publishing needs `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repository secrets.
GHCR uses the built-in `GITHUB_TOKEN`.

## Running it on a Flywheel instance

Uploading the gear to a site is still manual, and is the last step after a
release.

### 1. Install the Flywheel CLI

Use the current CLI, `flyw`:

```bash
curl https://storage.googleapis.com/flywheel-dist/fw-cli/stable/install.sh | sh
flyw --help
```

:warning: **Not the legacy `fw` CLI.** `fw` 16.x bundles a Docker API 1.39
client, and Docker Engine 25 and newer refuse anything below 1.44, so
`fw gear upload` fails before it does anything useful:

```
Creating container from astewartau/qsmxt_flywheel:1.0.0_9.20.0 ...
Error response from daemon: client version 1.39 is too old.
Minimum supported API version is 1.44, please upgrade your client to a newer version
```

That is the old CLI talking to a modern Docker daemon — nothing to do with this
gear or its image. Install `flyw` above instead. (`flyw` also speaks Podman:
`flyw --container-client podman ...`.)

### 2. Log in

Generate an API key in the Flywheel web UI on your Profile page, then:

```bash
flyw auth login     # prompts for the key, stores it in ~/.fw/config.yml
flyw auth status    # confirm
```

The key is a secret — let the prompt take it rather than putting it on the
command line, where it lands in your shell history.

### 3. Upload the gear

```bash
git checkout 1.0.0_9.20.0                            # the release to upload
docker pull astewartau/qsmxt_flywheel:1.0.0_9.20.0   # the tag in v0/manifest.json
cd v0/
flyw gear upload
```

The gear then appears in the instance's gear list, under the **Image Processing**
suite. A gear's name and version combination is reserved once uploaded, so
re-uploading a fixed gear needs a new version — bump the gear half of
`version` in the manifest and cut a new release.

### 4. Run it

The gear takes **two DICOM inputs**: a magnitude `.zip` and a phase `.zip`, both
containing DICOMs from the same gradient-echo acquisition. In the web UI, open a
session that has them, choose **Run Gear → Analysis Gear → QSMxT**, and pick the
two files.

Leaving every option alone runs QSMxT's defaults, which is the right starting
point for human-brain GRE data. Two settings are worth a look first:

- **If your zips contain series other than the QSM acquisition**, set
  `include_pattern` (e.g. `*acq-QSM*`). By default every gradient-echo
  acquisition found is reconstructed. This replaces `qsm_protocol_pattern` from
  earlier versions, and matches on the BIDS key rather than the protocol name —
  see [Selecting acquisitions](#selecting-acquisitions).
- **`save_bids`** is useful on a first run: it returns the converted BIDS
  dataset so you can confirm the DICOMs were classified as you expect.

### 5. Check the output

| File | What to look at |
| --- | --- |
| `qsmxt.log` | Read this first — it names every algorithm that ran |
| `qsm.zip` | `sub-*/anat/*_Chimap.nii` is the susceptibility map, alongside the mask and `methods.md` citing the methods used on your data |
| `workflow.zip` | Per-stage intermediates, if a result looks wrong |
| `bids.zip` | Only with `save_bids` — check the echoes and mag/phase split are right |

A sensible smoke test is one session first: confirm the Chimap looks like a
brain, then run the rest.

### Trying it without an instance

`flyw gear run` runs the gear on your own machine, which is quicker than a round
trip through a site. It expects the gear directory layout — `manifest.json`,
`config.json`, `input/`, `output/` — which is what `v0/` is:

```bash
cd v0/
flyw gear run
```

Public test DICOMs, if you need a pair to try:
[https://osf.io/ru43c/](https://osf.io/ru43c/) → `qmenta-test-files/`. Drop them
in as `input/magnitude/mag.zip` and `input/phase/phs.zip`.

`tests/test_gear.py` and `tests/test_real_data.py` do the same thing without the
CLI at all — they build that layout and invoke the container directly. See
[Testing](#testing).

### Building the image by hand

```bash
docker build -t qsmxt_flywheel:test -f qsm.Dockerfile .
```

## Testing

```bash
docker build -t qsmxt_flywheel:test -f qsm.Dockerfile .
pip install numpy pydicom nibabel

python3 tests/test_gear.py       # synthetic phantom, no download
python3 tests/test_real_data.py  # real scanner DICOMs, 27 MB from OSF
```

`tests/make_test_dicoms.py` builds a small synthetic multi-echo GRE acquisition
as DICOM — an ellipsoid with a paramagnetic and a diamagnetic source and a
smooth background field, so masking, unwrapping, background field removal and
dipole inversion all have something to do. `tests/test_gear.py` runs the gear on
it exactly as Flywheel does and checks the outputs, including that the two
sources come back near the susceptibilities they were simulated with.

`tests/test_config.py` runs inside the container and checks the configuration
layer: every manifest enum value produces a command the real `qsmxt` accepts,
the self-BFR inversions drop a conflicting `bf_algorithm`, `auto` passes no
flag, `qsmxt_cmd_args` wins, and the manifest agrees with `run.py` and with the
QSMxT version actually installed in the image.

`tests/check_public_image.sh` checks an image reference is readable by an
anonymous user. The release workflow is logged in to both registries, so a plain
`docker pull` there proves nothing about what anyone else can reach — on the
first release GHCR made the new package private and the authenticated check
passed regardless. This asks each registry for an anonymous pull token instead,
which is what a stranger's `docker pull` does first.

`tests/test_real_data.py` runs the same gear on the QSMxT test dataset from
[OSF](https://osf.io/ru43c/) — a single-echo 1 mm isotropic Siemens GRE, as the
magnitude and phase DICOM zips this gear takes. It is public and needs no
credentials, and the download is cached. There is no ground truth here, so it
checks what you can check without one: the reconstruction lands on the acquired
grid, is finite, the mask covers a plausible fraction of the field of view, and
the in-mask susceptibility is referenced to zero with a physiological spread. It
catches the failures a phantom cannot — real vendor DICOMs, a single echo,
an obliquely acquired volume — in about 20 seconds.

Pass `--cache-dir` to keep the download between runs.

The gear container is run with `--network=none` in both, so anything that
quietly depended on a download — deep-learning weights, say — fails the test
rather than only failing at a customer site.

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs both suites on
every push and pull request, and the release workflow calls that same workflow as
its gate — so a release runs exactly the checks a pull request does, not a
parallel copy of them, and nothing is published unless the gear has just
reconstructed real scanner data. See [Releasing](#releasing).

## Publishing to the Flywheel Gear Exchange

The gear is not on the [Gear Exchange](https://flywheel.io/gear-exchange/#library)
yet — today it is distributed by building the image and running `flyw gear upload`
into your own instance. The manifest now carries what a submission needs
(`maintainer`, `custom.flywheel.classification`, a semver gear version), and
`tests/test_config.py` checks those stay valid.

Submitting is a reviewed merge request, not something CI can do:

1. Fork the Gear Exchange repository on GitLab and branch.
2. Add the manifest as `gears/<org>/<gear-name>.json`.
3. Make sure the image tag it names is public (the release workflow does this).
4. Open a merge request using the **New Gear Submission** template, including a
   link to a successful job run on your own Flywheel instance.
5. Flywheel's Solutions Engineering team reviews it; updates later go through the
   **Gear Update Submission** template.

The live repository is
<https://gitlab.com/flywheel-io/scientific-solutions/gears/gear-exchange>. Note
that its `CONTRIBUTING.md` tells you to fork `flywheel-io/public/gear-exchange`,
which does not resolve — worth confirming the right fork target before starting.
The old `github.com/flywheel-io/exchange` repository is archived.

## Upgrading a QSMxT version

1. Bump `QSMXT_VERSION` in `qsm.Dockerfile`.
2. Bump `version` and `custom.gear-builder.image` in `v0/manifest.json` — the
   QSMxT half of the version, and reset the gear half if you like. The release
   tag must match `version` exactly.
3. Check `qsmxt run --help` for algorithm choices added or removed, and update
   the enums in `v0/manifest.json` — and, if a new method does its own
   background field removal or starts from wrapped phase, the sets at the top of
   `v0/run.py`.
4. Run the tests. `test_config.py` will fail if the QSMxT named in the manifest
   version is not the one in the image, or if a manifest enum names an algorithm
   this QSMxT does not have.
