#!/usr/bin/env bash

CONTAINER_NAME="rueckgrat_caddy"
DOCKER_IMAGE="rueckgrat_caddy"

if [ "$(docker ps -aq -f name=^${CONTAINER_NAME}$)" ]; then
  docker stop "$CONTAINER_NAME" > /dev/null
  docker rm "$CONTAINER_NAME" > /dev/null
fi

mkdir -p caddy_data
mkdir -p caddy_config

docker run -d \
    -p 80:80 \
    -p 443:443 \
    -p 2019:2019 \
    --name $CONTAINER_NAME \
    --network rueckgrat-net-local \
    $DOCKER_IMAGE 

echo $CONTAINER_NAME launched ...
echo "See logs like this:"
echo "  docker logs -f $CONTAINER_NAME"
