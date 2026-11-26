# syntax=docker/dockerfile:1.7
# The AWS Emulator image for KAMANU's R6c spike, after the published "Getting started with
# Docker" Dockerfile. The download URL is "latest" (the server ignores a ?versionId= query),
# so the package is pinned by checksum: release 1.0.338-1 (commit 32b3cf39). When upstream
# moves on, the build fails here instead of silently building another release; update
# REV/VERSION in launch.py, this checksum and evidence/ladder/r6c/spike.json together.
# Telemetry is turned off in the image as well as by the launcher's flag, variable and config.
FROM public.ecr.aws/amazonlinux/amazonlinux:2023-minimal
ADD --checksum=sha256:80773cc031cdd48f1c225e2f2794f2fb703d93e8d7b81915dbd730ecbdc00cb8 https://downloads.aws.com/aws-emulator/packages/aws-emulator/LTS/latest/aws-emulator-x86_64.rpm /tmp/aws-emulator.rpm
RUN rpm -i /tmp/aws-emulator.rpm && rm /tmp/aws-emulator.rpm \
    && mkdir -p /home/emulator && chown 1000 /home/emulator
USER 1000
ENV HOME=/home/emulator
ENV EMULATOR_TELEMETRY=off
EXPOSE 9297
ENTRYPOINT ["aws-emulator", "-b", "0.0.0.0"]
