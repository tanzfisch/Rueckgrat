#!/bin/bash

read -p "Do you want to install and run caddy as a service? (y/n): " answer
if [[ $answer =~ ^[Yy]$ ]]; then
    echo "installing caddy as service..."
    cd caddy
    ./install.sh && ./run.sh
    cd ..
fi

read -p "Do you want to install and run llama.cpp as a service? (y/n): " answer
if [[ $answer =~ ^[Yy]$ ]]; then
    echo "installing llama.cpp as service..."
    cd llama.cpp
    ./install.sh
    cd ..
fi

read -p "Do you want to install and run ComfyUI as a service? (y/n): " answer
if [[ $answer =~ ^[Yy]$ ]]; then
    echo "installing ComfyUI as service..."
    cd ComfyUI
    ./install.sh
    cd ..
fi

read -p "Do you want to run a Rückgrat node on this machine? (y/n): " answer
if [[ $answer =~ ^[Yy]$ ]]; then
    echo "installing Rückgrat node as docker container..."
    cd node
    ./install.sh && ./run.sh
    cd ..
fi

read -p "Do you want to run a Rückgrat hub on this machine? (y/n): " answer
if [[ $answer =~ ^[Yy]$ ]]; then
    echo "installing Rückgrat hub as docker container..."
    cd hub
    ./install.sh && ./run.sh
    cd ..
fi