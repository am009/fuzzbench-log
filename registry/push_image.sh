#!/bin/bash

fuzzers="honggfuzz_latest honggfuzz_log honggfuzz_no_bin honggfuzz_sched_no_short honggfuzz_sched_no_cov honggfuzz_sched_no_faster honggfuzz_no_mopt honggfuzz_mut_no_bitflip honggfuzz_mut_no_arith honggfuzz_mut_no_interesting
  honggfuzz_mut_no_dict_extra honggfuzz_mut_no_dyn_dict honggfuzz_mut_no_random_bytes honggfuzz_mut_no_structural_bytes honggfuzz_mut_no_ascii_num honggfuzz_mut_no_splice honggfuzz_mut_no_cmplog"
benchmarks="libpng_libpng_read_fuzzer libxml2_xml libxslt_xpath mbedtls_fuzz_dtlsclient openthread_ot-ip6-send-fuzzer stb_stbi_read_fuzzer systemd_fuzz-link-parser vorbis_decode_fuzzer woff2_convert_woff2ttf_fuzzer zlib_zlib_uncompress_fuzzer"
REGISTRY="registry.example.com"

docker_push() {
    # 检查是否提供了参数
    if [ $# -eq 0 ]; then
        echo "错误: 请提供Docker镜像名称作为参数"
        echo "用法: docker_push <镜像名>"
        return 1
    fi
    
    local original_image="$1"
    local target_image=""
    
    # 检查镜像是否以gcr.io/开头
    if [[ ! "$original_image" =~ ^gcr\.io/ ]]; then
        echo "错误: 镜像名必须以 'gcr.io/' 开头"
        echo "当前镜像: $original_image"
        return 1
    fi
    
    # 替换registry前缀
    target_image="${original_image/gcr.io\//$REGISTRY/}"
    
    echo docker tag "$original_image" "$target_image"
    if ! docker tag "$original_image" "$target_image"; then
        echo "错误: 重新tag镜像失败"
        return 1
    fi
    
    # 推送镜像到目标registry
    echo "推送镜像到 $REGISTRY..."
    if ! docker push "$target_image"; then
        echo "错误: 推送镜像失败"
        # 即使推送失败也尝试清理新tag
        docker rmi "$target_image" 2>/dev/null || true
        return 1
    fi
    
    # 删除新创建的tag
    echo "删除本地新tag: $target_image"
    docker rmi "$target_image" 2>/dev/null || echo "警告: 删除新tag失败"
    
    echo "操作完成!"
    echo "原始镜像: $original_image 已推送到: $target_image"
}

# # 1. build and push dispatcher image
# make dispatcher-image
# docker_push gcr.io/fuzzbench/dispatcher-image

# 2. Push measurer
for benchmark in $benchmarks; do
    make build-coverage-$benchmark || make build-coverage-$benchmark
    docker_push gcr.io/fuzzbench/builders/coverage/$benchmark
done

# # 3. push runner
for fuzzer in $fuzzers; do
    for benchmark in $benchmarks; do
        make .$fuzzer-$benchmark-runner || make .$fuzzer-$benchmark-runner
        docker_push gcr.io/fuzzbench/runners/$fuzzer/$benchmark
    done
done
