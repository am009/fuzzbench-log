

docker kill $(docker ps  | grep fuzzbench | awk '{print $1}')