ARG BASE_IMAGE="ghcr.io/ublue-os/bluefin-dx"
ARG TAG="stable"
ARG VARIANT=""

FROM ${BASE_IMAGE}:${TAG}

ARG VARIANT

# Copy build script and stage system files for variant-specific installation
COPY build.sh /tmp/build.sh
COPY system_files /tmp/system_files

# Run niri installation
RUN chmod +x /tmp/build.sh && VARIANT="${VARIANT}" /tmp/build.sh && rm -rf /tmp/build.sh /tmp/system_files

# Validate
RUN bootc container lint
