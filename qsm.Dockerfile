# start with qsmxt container
FROM vnmd/qsmxt_1.2.0:20221208

WORKDIR /root

# install necessary software
RUN pip3 install flywheel-sdk

# flywheel setup
COPY v0/run.py /root/
ENV FLYWHEEL=/flywheel/v0
RUN mkdir -p ${FLYWHEEL}
COPY v0/run.py ${FLYWHEEL}/run.py

