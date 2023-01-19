# qsmxt-flywheel

```bash
# specify some version information
qsmxt_version=1.1.13
build_date=20220119
fw_instance=SPECIFY
fw_api_key=SPECIFY

# build the flywheel version of the docker container
docker build -t "astewartau/qsmxt_flywheel_${qsmxt_version}:${build_date}" . -f qsm.Dockerfile

# push to dockerhub (if you have permission..)
docker push "astewartau/qsmxt_flywheel_${qsmxt_version}:${build_date}"

# test the flywheel gear locally
cd v0/
fw gear local --qsm_iterations=1 --magnitude=input/mag.zip --phase=input/phs.zip # the .zips should have DICOMs

# login and upload to flywheel
fw login "${fw_instance}.flywheel.io:${fw_api_key}"
fw gear upload
```
