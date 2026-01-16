#!/bin/bash

set -e

# Check every 3 minutes in a loop
while true; do
    fuzzbench_containers=$(docker ps | grep fuzzbench || true)  # Get containers containing fuzzbench

    if [ -z "$fuzzbench_containers" ]; then
        echo "No fuzzbench containers are running, exiting loop"
        break
    else
        echo "Fuzzbench containers are still running, checking again in 3 minutes"
    fi

    sleep 180  # 3 minutes
done

sleep 3
