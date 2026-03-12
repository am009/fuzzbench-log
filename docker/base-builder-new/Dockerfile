# Copyright 2026
#
# Derived from the local setup documented in README.md.

FROM gcr.io/oss-fuzz-base/base-builder@sha256:cf46c8fff9b892152539bf6dc1d7301dcc0b766baa5cdf4ca357f9e0eafb3d04

RUN sed -i "s/archive.ubuntu.com/mirrors.hust.edu.cn/g" /etc/apt/sources.list && \
    sed -i "s/security.ubuntu.com/mirrors.hust.edu.cn/g" /etc/apt/sources.list
