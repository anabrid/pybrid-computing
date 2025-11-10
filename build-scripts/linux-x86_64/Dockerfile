# Dockerfile for building binary wheels of pybrid-computing (Linux x86_64)
#
# This container provides an isolated environment for building wheels
# without polluting the host system or source tree.
#
# Usage:
#   docker build -t pybrid-build-linux-x86_64 -f build-scripts/linux-x86_64/Dockerfile .
#   docker run -v $(pwd)/dist:/dist pybrid-build-linux-x86_64
#

FROM python:3.11-slim

# Install build essentials and Docker CLI
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    git \
    curl \
    ca-certificates \
    unzip \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /build

# Copy only build scripts and requirements first (for layer caching)
COPY build-scripts/requirements-build.txt /build/build-scripts/
RUN pip install --no-cache-dir -r /build/build-scripts/requirements-build.txt

# Copy the entire project
COPY . /build/

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV CYTHON_LANGUAGE_LEVEL=3
ENV CYTHON_NTHREADS=4

# Create output directory
RUN mkdir -p /dist

# Note: docker-build.sh script is already copied via COPY . /build/
# The script runs in two modes:
# - On host: builds image and runs itself in container
# - In container (IN_CONTAINER=true): performs the actual build
