# aflplusplus

TODO:
- make main direct exec test case?

test:
```
make debug-builder-aflplusplus_blockdom-curl_curl_fuzzer_http
make debug-builder-aflplusplus_blockdom-proj4_proj_crs_to_crs_fuzzer

# in container
mkdir /blockdom
export FUZZERLOG_DOMTREE_DIR=/blockdom/
fuzzer_build

# in another terminal
docker cp 9ddb0e411f81:/blockdom .
```
