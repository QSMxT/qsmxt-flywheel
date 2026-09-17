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
gh release create 2.0.0_9.20.0 --generate-notes
```

The gear version is `<gear-semver>_<qsmxt-version>` — `2.0.0_9.20.0` is gear
2.0.0 wrapping QSMxT 9.20.0. This is the convention the accepted gears in the
Flywheel Gear Exchange use (`bids-mriqc` is `2.1.4_24.0.2`), and it lets the
gear be re-released — a `run.py` fix, a manifest correction — without pretending
QSMxT changed. Bump the left half for gear changes and the right half to track a
QSMxT release.

The gear half starts at 2.0.0 because the
[Gear Exchange](#publishing-to-the-flywheel-gear-exchange) already carries
`1.3.2_20230220` from 2023. A version has to move forward from what is published
there, and a major bump is the honest one for a rewrite that removed `premade`
and `qsm_protocol_pattern`.

That triggers [`.github/workflows/release.yml`](.github/workflows/release.yml),
which:

1. runs the full CI suite on the release commit — synthetic phantom, manifest
   validation, and real scanner DICOMs — and publishes nothing if any of them
   fails;
2. derives the image tags from the release tag, and **refuses the release if the
   tag does not match `v0/manifest.json`** (`flyw gear upload` pulls whatever
   `custom.gear-builder.image` names before copying it to the site, so a
   mismatch would make the upload fail or ship the wrong image);
3. builds once and pushes to both registries:

   | | |
   | --- | --- |
   | Docker Hub | `astewartau/qsmxt_flywheel:<version>` — what the manifest names, so this is the one Flywheel pulls |
   | GHCR | `ghcr.io/qsmxt/qsmxt-flywheel:<version>` |

   Both also get `:latest`, unless the release is marked as a prerelease;
4. checks each published tag is readable by an **anonymous** user, since the
   runner is logged in to both registries and would happily verify an image
   nobody else can reach — which is exactly what happened on the first release;
5. pulls the published image back and re-runs the configuration checks against
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
~/.fw/flyw --version
```

The installer puts `flyw` in `~/.fw` and adds that to your `PATH` **through your
shell profile**, so a plain `flyw` will not be found until you start a new shell.
Call it by full path (`~/.fw/flyw`) until then — that is all the `~/.fw/` prefix
below means.

If your site pins a particular CLI version, point the installer at it and it
installs the compatible one:

```bash
FW_SITE_URL=https://${FLYWHEEL_INSTANCE}.flywheel.io \
  curl -s https://storage.googleapis.com/flywheel-dist/fw-cli/stable/install.sh | sh
```

Pinning a version directly also works — e.g. `.../fw-cli/0.36.1/install.sh`.

:warning: **Not the legacy `fw` CLI.** `fw` 16.x bundles a Docker API 1.39
client, and Docker Engine 25 and newer refuse anything below 1.44, so
`fw gear upload` fails before it does anything useful:

```
Creating container from astewartau/qsmxt_flywheel:2.0.0_9.20.0 ...
Error response from daemon: client version 1.39 is too old.
Minimum supported API version is 1.44, please upgrade your client to a newer version
```

That is the old CLI talking to a modern Docker daemon — nothing to do with this
gear or its image. Install `flyw` above instead. (`flyw` also speaks Podman:
`flyw --container-client podman ...`.)

### 2. Log in

Generate an API key in the Flywheel web UI on your Profile page, then:

```bash
~/.fw/flyw login            # prompts for the key, stores it in ~/.fw/config.yml
~/.fw/flyw login --status   # confirm
```

(`flyw auth login` is the same command spelled out in full.)

The key is a secret — let the prompt take it rather than putting it on the
command line, where it lands in your shell history.

### 3. Upload the gear

```bash
git checkout 2.0.0_9.20.0                            # the release to upload
docker pull astewartau/qsmxt_flywheel:2.0.0_9.20.0   # the tag in v0/manifest.json
cd v0/
~/.fw/flyw gear --validate manifest.json             # optional, catches mistakes early
~/.fw/flyw gear upload
```

The upload re-tags the image into the site's own registry and pushes it there:

```
Tagging image locally as <site>.flywheel.io/qsmxt:2.0.0_9.20.0
Getting permission to push image...
Uploading to Docker registry...
Registering gear on server...
Uploaded gear with id 6aab8686838126f0379a0cca
```

So the site holds its own copy — jobs do not pull from Docker Hub at run time,
and the gear keeps working there regardless of what happens upstream.

It then appears in the instance's gear list under **Installed Gears**. A gear's
name and version combination is reserved once uploaded, so re-uploading a fixed
gear needs a new version — bump the gear half of `version` in the manifest and
cut a new release.

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
~/.fw/flyw gear run
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
tests/test_manifest_cli.sh       # manifest, against Flywheel's own CLI
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

`tests/test_manifest_cli.sh` validates `v0/manifest.json` with **Flywheel's own
CLI** (`flyw gear --validate`), installing it if needed. Everything else here
drives the container directly, which is how out-of-date CLI instructions went
unnoticed until someone tried to follow them. It checks the manifest against
Flywheel's schema rather than our reading of it, and catches things we would not
think to write — it objects if the manifest version disagrees with its docker
image tag, for one. It also feeds the validator a deliberately broken manifest
and fails if that is accepted.

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

Both suites that run the gear do so with `--network=none`, so anything that
quietly depended on a download — deep-learning weights, say — fails the test
rather than only failing at a customer site.

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs three jobs on
every push and pull request — **Synthetic phantom**, **Manifest (Flywheel CLI)**
and **Real scanner DICOMs** — and the release workflow calls that same workflow
as its gate, so a release runs exactly the checks a pull request does rather than
a parallel copy of them. Nothing is published unless the gear has just
reconstructed real scanner data. See [Releasing](#releasing).

## Publishing to the Flywheel Gear Exchange

QSMxT **is already on the** [Gear Exchange](https://flywheel.io/gear-exchange/#library),
as a community-contributed gear. The entry is
[`gears/flywheel/qsmtx.json`](https://gitlab.com/flywheel-io/scientific-solutions/gears/gear-exchange/-/blob/master/gears/flywheel/qsmtx.json)
— note the transposed filename, which is why searching the repository for
"qsmxt" finds nothing. It still carries `1.3.2_20230220` from February 2023,
whose only config option is the long-gone `premade`.

So this is a **gear update**, not a new submission:

1. Fork <https://gitlab.com/flywheel-io/scientific-solutions/gears/gear-exchange>
   and branch.
2. Replace the contents of `gears/flywheel/qsmtx.json` with `v0/manifest.json`
   from the release being submitted. Keep the existing path — renaming it is a
   separate conversation with Flywheel, not something to slip into an update.
3. Make sure the image tag it names is publicly pullable — the release workflow
   checks this, and `tests/check_public_image.sh` does it on demand.
4. Open a merge request using the **Gear Update Submission** template, saying
   what changed and including a link to a successful job run on a real instance.
5. Flywheel's Solutions Engineering team reviews it.

Two things to settle before opening it:

- The published entry uses `custom.flywheel.suite: "Community-contributed"`,
  which is what renders the *Community-contributed* badge in the gear info
  panel. This repository currently sets `"Image Processing"`.
- `CONTRIBUTING.md` tells you to fork `flywheel-io/public/gear-exchange`, which
  does not resolve. Confirm the right fork target first. The old
  `github.com/flywheel-io/exchange` repository is archived.

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
