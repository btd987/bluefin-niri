ARG BASE_IMAGE="ghcr.io/ublue-os/bluefin-dx"
ARG TAG="stable"

FROM ${BASE_IMAGE}:${TAG}

# Copy build script and system files
COPY build.sh /tmp/build.sh
COPY system_files /

# Run niri installation
RUN chmod +x /tmp/build.sh && /tmp/build.sh && rm /tmp/build.sh

# Validate
RUN bootc container lint
