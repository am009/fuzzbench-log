#!/bin/bash

set -e

# 每3分钟循环检测
while true; do
    fuzzbench_containers=$(docker ps | grep fuzzbench || true)  # 获取包含fuzzbench的容器

    if [ -z "$fuzzbench_containers" ]; then
        echo "没有fuzzbench容器在运行，跳出循环"
        break
    else
        echo "仍有fuzzbench容器在运行，3分钟后再次检查"
    fi

    sleep 180  # 3分钟
done

sleep 3
