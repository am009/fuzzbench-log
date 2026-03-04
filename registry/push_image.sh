#!/bin/bash

# push_image.sh - 支持 xargs 并行的镜像构建推送脚本
#
# 用法:
#   ./push_image.sh [-j N]                  # 主模式：并行构建推送所有 fuzzer×benchmark
#   ./push_image.sh <fuzzer> <benchmark>    # worker 模式：处理单个组合
#
# 示例:
#   ./push_image.sh                         # 默认 4 并行
#   ./push_image.sh -j 8                    # 8 并行
#   ./push_image.sh honggfuzz_latest bloaty_fuzz_target  # 单个组合
#
# 外部 xargs 调用:
#   export REGISTRY="example.com"
#   export IMAGES_FILE="/path/to/images.txt"
#   echo "aflplusplus_latest bloaty_fuzz_target" | xargs -n 2 -P 4 ./push_image.sh

hfuzz_core_fuzzers="honggfuzz_latest honggfuzz_log honggfuzz_no_bin honggfuzz_sched_no_short honggfuzz_sched_no_cov honggfuzz_sched_no_faster honggfuzz_no_mopt honggfuzz_mut_no_cmplog honggfuzz_mut_no_dyn_dict" # 9 fuzzers
aflpp_core_fuzzers="aflplusplus_latest aflplusplus_log aflplusplus_mopt aflplusplus_mut_no_cmplog aflplusplus_no_bin aflplusplus_sched_no_short aflplusplus_sched_no_cov aflplusplus_sched_no_faster" # 8 fuzzers
libafl_core_fuzzers="libafl_latest libafl_log libafl_no_bin libafl_sched_no_short libafl_sched_no_cov libafl_sched_no_faster libafl_no_mopt" # 7 fuzzers

hfuzz_mut_fuzzers="honggfuzz_mut_no_bitflip honggfuzz_mut_no_arith honggfuzz_mut_no_interesting honggfuzz_mut_no_dict_extra honggfuzz_mut_no_random_bytes honggfuzz_mut_no_structural_bytes honggfuzz_mut_no_ascii_num honggfuzz_mut_no_splice" # 8 fuzzers
aflpp_mut_fuzzers="aflplusplus_mut_no_bitflip aflplusplus_mut_no_arith aflplusplus_mut_no_interesting aflplusplus_mut_no_dict_extra aflplusplus_mut_no_random_bytes aflplusplus_mut_no_structural aflplusplus_mut_no_ascii_num aflplusplus_mut_no_splice" # 8 fuzzers
libafl_mut_fuzzers="libafl_mut_no_bitflip libafl_mut_no_arith libafl_mut_no_interesting libafl_mut_no_dict_extra libafl_mut_no_cmplog libafl_mut_no_random_bytes libafl_mut_no_structural_bytes libafl_mut_no_splice" # 8 fuzzers

hfuzz_fuzzers="$hfuzz_core_fuzzers $hfuzz_mut_fuzzers" # 17 fuzzer
aflpp_fuzzers="$aflpp_core_fuzzers $aflpp_mut_fuzzers" # 16 fuzzer
libafl_fuzzers="$libafl_core_fuzzers $libafl_mut_fuzzers" # 15 fuzzer

fuzzers="$hfuzz_core_fuzzers $aflpp_core_fuzzers $libafl_core_fuzzers $hfuzz_mut_fuzzers $aflpp_mut_fuzzers $libafl_mut_fuzzers"

benchmarks10="bloaty_fuzz_target openssl_x509 proj4_proj_crs_to_crs_fuzzer freetype2_ftfuzzer lcms_cms_transform_fuzzer curl_curl_fuzzer_http harfbuzz_hb-shape-fuzzer libjpeg-turbo_libjpeg_turbo_fuzzer libpcap_fuzz_both sqlite3_ossfuzz"
benchmarks20="libpng_libpng_read_fuzzer libxml2_xml libxslt_xpath mbedtls_fuzz_dtlsclient openthread_ot-ip6-send-fuzzer stb_stbi_read_fuzzer systemd_fuzz-link-parser vorbis_decode_fuzzer woff2_convert_woff2ttf_fuzzer zlib_zlib_uncompress_fuzzer"

benchmarks="$benchmarks10 $benchmarks20"

REGISTRY="${REGISTRY:-registry.example.com}"

SCRIPTPATH="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"

has_image() {
    if [ $# -eq 0 ]; then
        echo "错误: 请提供Docker镜像名称作为参数"
        echo "用法: has_image <镜像名>"
        return 1
    fi

    local original_image=$1
    local image_suffix="${original_image/gcr.io\//}"
    if grep "$image_suffix" "$IMAGES_FILE" > /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

docker_push() {
    if [ $# -eq 0 ]; then
        echo "错误: 请提供Docker镜像名称作为参数"
        echo "用法: docker_push <镜像名>"
        return 1
    fi

    local original_image="$1"
    local target_image=""

    if [[ ! "$original_image" =~ ^gcr\.io/ ]]; then
        echo "错误: 镜像名必须以 'gcr.io/' 开头"
        echo "当前镜像: $original_image"
        return 1
    fi

    target_image="${original_image/gcr.io\//$REGISTRY/}"

    echo docker tag "$original_image" "$target_image"
    if ! docker tag "$original_image" "$target_image"; then
        echo "错误: 重新tag镜像失败"
        return 1
    fi

    echo "推送镜像到 $REGISTRY..."
    if ! docker push "$target_image"; then
        echo "错误: 推送镜像失败"
        docker rmi "$target_image" 2>/dev/null || true
        return 1
    fi

    echo "删除本地新tag: $target_image"
    docker rmi "$target_image" 2>/dev/null || echo "警告: 删除新tag失败"

    echo "操作完成!"
    echo "原始镜像: $original_image 已推送到: $target_image"
}

# ============================================================
# Worker 模式：传入 2 个位置参数时，处理单个 fuzzer+benchmark
# ============================================================
if [ $# -ge 2 ] && [[ "$1" != -* ]]; then
    fuzzer="$1"
    benchmark="$2"
    prefix="[$fuzzer/$benchmark]"

    if ! has_image "gcr.io/fuzzbench/runners/$fuzzer/$benchmark"; then
        echo "$prefix 构建镜像..."
        if ! make ".$fuzzer-$benchmark-runner"; then
            echo "$prefix 第一次构建失败，重试..."
            if ! make ".$fuzzer-$benchmark-runner"; then
                echo "$prefix 构建失败，跳过"
                exit 1
            fi
        fi
        echo "$prefix 推送镜像..."
        if ! docker_push "gcr.io/fuzzbench/runners/$fuzzer/$benchmark"; then
            echo "$prefix 推送失败"
            exit 1
        fi
        echo "$prefix 完成"
    else
        echo "$prefix 镜像已存在，跳过"
    fi
    exit 0
fi

# ============================================================
# 主模式：生成所有 fuzzer×benchmark 组合，xargs 并行调度
# ============================================================

# 解析 -j N 参数
JOBS=4
while getopts "j:" opt; do
    case $opt in
        j) JOBS="$OPTARG" ;;
        *) echo "用法: $0 [-j N]"; exit 1 ;;
    esac
done

SCRIPT_ABS_PATH="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)/$(basename "$0")"
export IMAGES_FILE="${SCRIPTPATH}/images.txt"
export REGISTRY

echo "=== 主模式: 并行度=$JOBS ==="

# 获取远程 registry 中已有的镜像列表
echo "获取远程镜像列表..."
"${SCRIPTPATH}/list-images.sh" "https://registry.example.com" > "$IMAGES_FILE"

# 统计组合数
total=0
for fuzzer in $fuzzers; do
    for benchmark in $benchmarks; do
        total=$((total + 1))
    done
done
echo "共 $total 个 fuzzer×benchmark 组合"

# 生成所有组合并通过 xargs 并行执行
for fuzzer in $fuzzers; do
    for benchmark in $benchmarks; do
        echo "$fuzzer $benchmark"
    done
done | xargs -P "$JOBS" -n 2 "$SCRIPT_ABS_PATH"

echo "=== 全部完成 ==="
