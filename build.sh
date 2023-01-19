#!/usr/bin/env bash
qsmxt_version=1.1.13
build_date=20230119

echo "Building docker container astewartau/qsmxt_flywheel_${qsmxt_version}:${build_date}..."
docker build -t "astewartau/qsmxt_flywheel_${qsmxt_version}:${build_date}" . -f qsm.Dockerfile

echo "Pushing to DockerHub..."
docker push "astewartau/qsmxt_flywheel_${qsmxt_version}:${build_date}"

