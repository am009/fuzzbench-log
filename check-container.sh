#!/bin/bash

docker commit $1 mysnapshot
docker run --rm --name mysnapshot --entrypoint /bin/bash -t -i mysnapshot
docker image rm mysnapshot
