#!/bin/bash

REGISTRY="${1:-http://localhost:5000}"
last=""
while :; do
  if [ -z "$last" ]; then
    url="${REGISTRY}/v2/_catalog?n=1000"
  else
    url="${REGISTRY}/v2/_catalog?n=1000&last=${last}"
  fi
  
  images=$(curl -s "$url" | grep -o '"repositories":\[[^]]*\]' | \
           sed 's/"repositories":\[//;s/\]//;s/"//g;s/,/\n/g')
  
  [ -z "$images" ] && break
  echo "$images"
  
  count=$(echo "$images" | wc -l)
  [ "$count" -lt 1000 ] && break
  
  last=$(echo "$images" | tail -1)
done