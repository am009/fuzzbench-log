# Copyright 2020 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

ARG parent_image
FROM $parent_image

RUN apt-get update && \
    apt-get install -y \
        build-essential \
        python3-dev \
        python3-setuptools \
        automake \
        cmake \
        git \
        flex \
        bison \
        libglib2.0-dev \
        libpixman-1-dev \
        cargo \
        libgtk-3-dev \
        # for QEMU mode
        ninja-build \
        gcc-$(gcc --version|head -n1|sed 's/\..*//'|sed 's/.* //')-plugin-dev \
        lsb-release wget software-properties-common gpg \
        libstdc++-$(gcc --version|head -n1|sed 's/\..*//'|sed 's/.* //')-dev \
        && bash -c "$(wget -O - https://apt.llvm.org/llvm.sh)" bash 15 \
        && rm /usr/local/bin/clang && ln -s /usr/bin/clang-15 /usr/bin/clang \
        && rm /usr/local/bin/clang++ && ln -s /usr/bin/clang++-15 /usr/bin/clang++ \
        && rm /usr/local/bin/llvm-config && ln -s /usr/bin/llvm-config-15 /usr/bin/llvm-config \
        && rm /usr/local/bin/llvm-ranlib && ln -s /usr/bin/llvm-ranlib-15 /usr/bin/llvm-ranlib \
        && rm /usr/local/bin/llvm-ar && ln -s /usr/bin/llvm-ar-15 /usr/bin/llvm-ar \
        && rm /usr/local/bin/llvm-as && ln -s /usr/bin/llvm-as-15 /usr/bin/llvm-as \
        && rm /usr/local/bin/llvm-cov && ln -s /usr/bin/llvm-cov-15 /usr/bin/llvm-cov \
        && rm /usr/local/bin/llvm-nm && ln -s /usr/bin/llvm-nm-15 /usr/bin/llvm-nm \
        && rm /usr/local/bin/llvm* && rm /usr/local/bin/clang* \
        && rm -rf /usr/local/include/clang /usr/local/include/clang-c /usr/local/include/clang /usr/local/include/lld /usr/local/include/llvm /usr/local/include/llvm-c \
        && cd /usr/local/lib && rm -rf $(ls | grep -v python | grep -v pkgconfig | grep -v libear | grep -v libscanbuild | grep -v c++) \
        && rm -rf /usr/local/libexec && mkdir /usr/local/libexec \
        && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
# the clang-15 from the parent image is too old to load a lto new pass manager plugin, so we need to install a new one.

# Download afl++.
RUN git clone -b dominator https://github.com/am009/AFLplusplus-log /afl && \
    cd /afl && \
    git checkout bc0d1732f754cd2034d9f0f1953f0bc74a60dd42 || \
    true

# ENV DEBUG=1
# ENV AFL_DEBUG=1

# Build without Python support as we don't need it.
# Set AFL_NO_X86 to skip flaky tests.
RUN cd /afl && \
    unset CFLAGS CXXFLAGS && \
    export CC=clang AFL_NO_X86=1 && \
    PYTHON_INCLUDE=/ make source-only && \
    cp utils/aflpp_driver/libAFLDriver.a /
