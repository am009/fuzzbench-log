# FuzzBench fork that provides customized analysis

This fork provides a special fuzzer called aflplusplus_blockdom, which extract block domination info and call graph and LTO module with debug info.

## Initialize

1. build base-image and dispatcher-image locally first.
```
make base-image
make dispatcher-image
make worker

# Update mirror for base-builder
docker build -t gcr.io/oss-fuzz-base/base-builder-new - << 'EOF'
FROM gcr.io/oss-fuzz-base/base-builder
RUN sed -i "s/archive.ubuntu.com/mirrors.hust.edu.cn/g" /etc/apt/sources.list && \
    sed -i "s/security.ubuntu.com/mirrors.hust.edu.cn/g" /etc/apt/sources.list
EOF

docker rmi gcr.io/oss-fuzz-base/base-builder 2>/dev/null || true
docker tag gcr.io/oss-fuzz-base/base-builder-new gcr.io/oss-fuzz-base/base-builder
docker rmi gcr.io/oss-fuzz-base/base-builder-new
```


### Useful commands

```
# To debug fuzzer build
# make debug-builder-$FUZZER_NAME-$BENCHMARK_NAME
# fuzzer_build

# To debug fuzzer run
# make debug-$FUZZER_NAME-$BENCHMARK_NAME
# $ROOT_DIR/docker/benchmark-runner/startup-runner.sh

# To test fuzzer run
make test-run-honggfuzz_latest-sqlite3_ossfuzz
```