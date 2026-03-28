#!/bin/bash

CONTAINER_NAME="rueckgrat_node"
DOCKER_IMAGE="rueckgrat_node"
RUN_IN_BACKGROUND="true"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  key="$1"
  case $key in
    -it|--interactive)
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
    CMD_ARGS="--port 7346 --host 0.0.0.0"
else
    RUN_OPTIONS="-it --entrypoint /bin/bash"
    CMD_ARGS=""
fi

docker run $RUN_OPTIONS \
    --name $CONTAINER_NAME \
    --network rueckgrat-net-local \
    --add-host=host.docker.internal:host-gateway \
    -v ../data:/data \
    -p 7346:7346 \
    $DOCKER_IMAGE \
    $CMD_ARGS

if [ "$RUN_IN_BACKGROUND" = "true" ]; then
  echo $CONTAINER_NAME launched ...
  echo "See logs like this:"
  echo "  docker logs -f $CONTAINER_NAME"
fi