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

# Uninstall old Rust & Install the latest one.
RUN if which rustup; then rustup self uninstall -y; fi && \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs > /rustup.sh && \
    sh /rustup.sh --default-toolchain 1.92.0 -y && \
    rm /rustup.sh

# Install dependencies.
RUN apt-get update && \
    apt-get install -y \
        build-essential \
        lsb-release wget software-properties-common gnupg && \
    apt-get install -y wget libstdc++5 libtool-bin automake flex bison \
        libglib2.0-dev libpixman-1-dev python3-setuptools unzip \
        apt-utils apt-transport-https ca-certificates joe curl

ENV FUZZERLOGLIB=/usr/local/lib/libfuzzerlog.so

RUN apt-get update && \
    apt-get install nano wget -y && \
    wget https://github.com/am009/fuzzbench-log/releases/download/20260302/libfuzzerlog.so -O /usr/local/lib/libfuzzerlog.so && \
    chmod 777 /usr/local/lib/libfuzzerlog.so

# Download libafl.
RUN git clone -b mopt2 https://github.com/am009/LibAFL /libafl && cd /libafl && git checkout 0b36a842813309438f6aaab44e4a76d77d62a8a2

# Compile libafl.
RUN cd /libafl && \
    unset CFLAGS CXXFLAGS && \
    export LIBAFL_EDGES_MAP_SIZE=2621440 && \
    cd ./fuzzers/inprocess/fuzzbench && \
    PATH="/root/.cargo/bin/:$PATH" cargo build --profile release-fuzzbench --features no_link_main

# Auxiliary weak references.
RUN cd /libafl/fuzzers/inprocess/fuzzbench && \
    clang -c stub_rt.c && \
    ar r /stub_rt.a stub_rt.o
