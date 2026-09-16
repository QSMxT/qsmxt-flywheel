# QSMxT v9 is a single self-contained binary, so the gear image no longer needs
# the toolbox stack (Julia, ANTs, FSL, miniconda) the 6.x/8.x containers carried.
FROM python:3.12-slim

# The QSMxT release to install. Must match the second half of the gear version
# in v0/manifest.json (<gear-semver>_<qsmxt-version>); the tests check this.
ARG QSMXT_VERSION=v9.20.0
ARG QSMXT_TARGET=x86_64-unknown-linux-gnu

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# qsmxt plus the dcm2niix bundled in the release archive, both on PATH so they
# are found regardless of which user the gear runs as.
RUN curl -fsSL \
      "https://github.com/QSMxT/QSMxT/releases/download/${QSMXT_VERSION}/qsmxt-${QSMXT_VERSION}-${QSMXT_TARGET}.tar.gz" \
      -o /tmp/qsmxt.tar.gz \
    && tar xzf /tmp/qsmxt.tar.gz -C /usr/local/bin \
    && rm /tmp/qsmxt.tar.gz \
    && chmod +x /usr/local/bin/qsmxt /usr/local/bin/dcm2niix \
    && qsmxt --version

RUN pip3 install --no-cache-dir flywheel-sdk

# Scratch space for the DICOM, BIDS and pipeline working directories.
ENV QSMXT_WORK_DIR=/work
RUN mkdir -p ${QSMXT_WORK_DIR}

ENV FLYWHEEL=/flywheel/v0
WORKDIR ${FLYWHEEL}
COPY v0/run.py ${FLYWHEEL}/run.py
COPY v0/manifest.json ${FLYWHEEL}/manifest.json
