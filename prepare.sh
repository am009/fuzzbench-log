#!/bin/bash

# install: https://google.github.io/fuzzbench/getting-started/prerequisites/
make install-dependencies
source .venv/bin/activate
make presubmit
