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

# honggfuzz requires libfd and libunwid.
RUN apt-get update -y && \
    apt-get install -y \
    libbfd-dev \
    libunwind-dev \
    libblocksruntime-dev \
    liblzma-dev \
    libasan5

# Download honggfuz version 2.3.1 + 0b4cd5b1c4cf26b7e022dc1deb931d9318c054cb
# Set CFLAGS use honggfuzz's defaults except for -mnative which can build CPU
# dependent code that may not work on the machines we actually fuzz on.
# Create an empty object file which will become the FUZZER_LIB lib (since
# honggfuzz doesn't need this when hfuzz-clang(++) is used).
RUN cd / && git clone -b master https://github.com/ThePatrickStar/honggfuzz-test.git /honggfuzz-good && \
    cd /honggfuzz-good && \
    git checkout 1f5e29948d207e41a03e501bf6d1b5d0b0183d36 && \
    DEBUG=1 make && cd / && \
    git clone -b debug https://github.com/ThePatrickStar/honggfuzz-test.git /honggfuzz && \
    cd /honggfuzz && \
    git checkout 2684fea370bd0841aa6fc345ba7fbc0a13a4b9f3 && \
    DEBUG=1 make && \
    touch empty_lib.c && \
    cc -c -o empty_lib.o empty_lib.c
