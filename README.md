# qsmxt-flywheel

install flywheel CLI: https://docs.flywheel.io/hc/en-us/articles/360008162214
```bash
wget https://storage.googleapis.com/flywheel-dist/cli/16.11.0/fw-linux_amd64-16.11.0.zip
unzip fw-linux_amd64-16.11.0.zip 
export PATH=$PATH:$PWD/linux_amd64 
```

```bash
# specify some version information
QSMXT_VERSION=6.3.2
BUILD_DATE=20231101

fw login ${FLYWHEEL_INSTANCE}.flywheel.io:${FLYWHEEL_API}

# build the flywheel version of the docker container
docker build -t "${DOCKER_ID}/qsmxt_flywheel:${QSMXT_VERSION}_${BUILD_DATE}" . -f qsm.Dockerfile

# push to dockerhub (if you have permission..)
docker login -u "${DOCKER_USER}" -p "${DOCKER_TOKEN}"
docker push "${DOCKER_ID}/qsmxt_flywheel:${QSMXT_VERSION}_${BUILD_DATE}"

# test the flywheel gear locally
cd v0/
fw gear local --premade='gre' --magnitude=input/mag.zip --phase=input/phs.zip # the .zips should have DICOMs

# login and upload to flywheel
fw login "${FLYWHEEL_INSTANCE}.flywheel.io:${FLYWHEEL_API}"
fw gear upload
```
