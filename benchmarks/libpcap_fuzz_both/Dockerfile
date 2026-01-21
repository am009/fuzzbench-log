# Copyright 2018 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
################################################################################

FROM gcr.io/oss-fuzz-base/base-builder
RUN apt-get update && \
    apt-get install -y make cmake flex bison libbsd-dev

RUN git clone https://github.com/the-tcpdump-group/libpcap.git libpcap && \
    git -C libpcap checkout 17ff63e88ea99112a905eefc6f862dac20de09e1 && \
    echo ZGlmZiAtLWdpdCBhL3BvcnRhYmlsaXR5LmggYi9wb3J0YWJpbGl0eS5oCmluZGV4IDg0ZDA3NzhhLi41NDQ5NTE2OSAxMDA2NDQKLS0tIGEvcG9ydGFiaWxpdHkuaAorKysgYi9wb3J0YWJpbGl0eS5oCkBAIC02NSw2ICs2NSw3IEBAIGV4dGVybiAiQyIgewogI2VuZGlmCiAKICNpZmRlZiBIQVZFX1NUUkxDUFkKKyAgI2luY2x1ZGUgPGJzZC9zdHJpbmcuaD4KICAgI2RlZmluZSBwY2FwX3N0cmxjcHkJc3RybGNweQogI2Vsc2UKICAgI2lmIGRlZmluZWQoX01TQ19WRVIpIHx8IGRlZmluZWQoX19NSU5HVzMyX18pCg== | base64 -d | patch libpcap/portability.h

# For corpus as wireshark.
RUN git clone https://github.com/the-tcpdump-group/tcpdump.git tcpdump && \
    git -C tcpdump checkout 032e4923e5202ea4d5a6d1cead83ed1927135874

WORKDIR $SRC
COPY build.sh $SRC/

