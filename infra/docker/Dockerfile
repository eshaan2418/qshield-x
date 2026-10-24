# Pinned toolchain image for QShield-X CI and reproduction (linux/amd64).
FROM ubuntu:24.04
ARG OSS_CAD_DATE=2026-10-24
ARG OSS_CAD_FILE=oss-cad-suite-linux-x64-20261024.tgz
ARG EMSDK_VERSION=6.0.13
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential clang git curl ca-certificates python3 python3-venv python3-dev \
      openjdk-21-jre-headless xz-utils make && rm -rf /var/lib/apt/lists/*
WORKDIR /opt
RUN curl -sL -o oss.tgz https://github.com/YosysHQ/oss-cad-suite-build/releases/download/${OSS_CAD_DATE}/${OSS_CAD_FILE} \
 && tar xzf oss.tgz && rm oss.tgz
RUN git clone --depth 1 https://github.com/emscripten-core/emsdk.git && cd emsdk \
 && ./emsdk install ${EMSDK_VERSION} && ./emsdk activate ${EMSDK_VERSION}
RUN curl -sL -o /opt/tla2tools.jar https://github.com/tlaplus/tlaplus/releases/download/v1.8.0/tla2tools.jar
COPY requirements.txt /opt/requirements.txt
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r /opt/requirements.txt
ENV PATH=/opt/venv/bin:/opt/oss-cad-suite/bin:$PATH TLA2TOOLS=/opt/tla2tools.jar
WORKDIR /work
