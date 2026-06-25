#!/bin/bash

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
source "$SCRIPT_DIR/registry_functions.sh"

case "$1" in
    --list)
        DEFAULT_LLM="cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L"
        DEFAULT_HOST="localhost:7346"
        declare -a MODEL_NAMES
        declare -i DEFAULT_IDX=-1
        VERBOSE=true
        FILTER=llm

        fetch_llm_models $DEFAULT_LLM $DEFAULT_HOST MODEL_NAMES DEFAULT_IDX $VERBOSE $FILTER
        ;;
    --install)
        if [ -n "$2" ]; then
            install_llm "$2"
        else
            echo "Usage: $0 --install <model>"
            exit 1
        fi
        ;;
    *)
        echo "Usage: $0 --list | --install <model>"
        exit 1
        ;;
esac
exit $?