# qsmxt-flywheel

install flywheel CLI: https://docs.flywheel.io/hc/en-us/articles/360008162214
```bash
wget https://storage.googleapis.com/flywheel-dist/cli/16.11.0/fw-linux_amd64-16.11.0.zip
unzip fw-linux_amd64-16.11.0.zip 
export PATH=$PATH:$PWD/linux_amd64 
```

```bash
# specify some version information
qsmxt_version=1.3.2
build_date=20230204
fw_instance=SPECIFY
fw_api_key=SPECIFY
docker_id=astewartau

fw login ${fw_instance}.flywheel.io:${fw_api_key}

# build the flywheel version of the docker container
docker build -t "${docker_id}/qsmxt_flywheel_${qsmxt_version}:${build_date}" . -f qsm.Dockerfile

# push to dockerhub (if you have permission..)
docker push "${docker_id}/qsmxt_flywheel_${qsmxt_version}:${build_date}"

# test the flywheel gear locally
cd v0/
fw gear local --premade='gre' --magnitude=input/mag.zip --phase=input/phs.zip # the .zips should have DICOMs

# login and upload to flywheel
fw login "${fw_instance}.flywheel.io:${fw_api_key}"
fw gear upload
```
