#!/bin/bash

# 根据启动命令过滤删除容器
docker ps -a | grep '"/bin/sh -c'| awk '{print $1}' | xargs -I {} docker rm {}

# 根据正则过滤强制删除镜像
docker images -a -q "gcr.io/fuzzbench/*/*/*" | xargs -I {} docker rmi -f {};
# 删除没有名字的镜像
docker images -q -f dangling=true | xargs -I {} docker rmi -f {};

docker buildx prune