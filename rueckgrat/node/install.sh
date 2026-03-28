#!/bin/bash

DEFAULT_CONFIG_SRC="../config"

read -p "Enter source folder path [${DEFAULT_CONFIG_SRC}]: " USER_SRC
SRC_PATH="${USER_SRC:-$DEFAULT_CONFIG_SRC}"

mkdir -p config
cp -r "$SRC_PATH"/* config/

docker build -t rueckgrat_node .