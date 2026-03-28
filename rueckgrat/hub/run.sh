#!/usr/bin/env bash

CONTAINER_NAME="rueckgrat_hub"
DOCKER_IMAGE="rueckgrat_hub"
RUN_IN_BACKGROUND="true"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  key="$1"
  case $key in
    -d|--debug)
      RUN_IN_BACKGROUND="false"
      shift
      ;;
    *)
      # Unknown option
      shift
      ;;
  esac
done

if [ "$(docker ps -aq -f name=^${CONTAINER_NAME}$)" ]; then
  docker stop "$CONTAINER_NAME" > /dev/null
  docker rm "$CONTAINER_NAME" > /dev/null
fi

if [ "$RUN_IN_BACKGROUND" = "true" ]; then
    RUN_OPTIONS="-d"
else
    RUN_OPTIONS="-it"
fi

docker run $RUN_OPTIONS \
    --name $CONTAINER_NAME\
    --network rueckgrat-net-local \
    -v ../data:/data \
    -p 14223:14223 \
    $DOCKER_IMAGE \

echo $CONTAINER_NAME launched ...
echo "See logs like this:"
echo "  docker logs -f $CONTAINER_NAME"
