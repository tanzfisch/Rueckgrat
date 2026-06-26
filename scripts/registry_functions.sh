fetch_llm_models() {
    local DEFAULT_LLM="${1:-cognitivecomputations_Dolphin-Mistral-24B-Venice-Edition-Q6_K_L}"
    local HOST="${2:-localhost:7346}"

    local -n MODEL_NAMES_REF="${3}"
    local -n DEFAULT_IDX_REF="${4}"

    local VERBOSE="${5}"
    local FILTER="${6:-llm}"

    echo "🔍 fetching models from registry..."
    sleep 3
    RESPONSE=$(curl -s "http://${HOST}/models?type_filter=${FILTER}")

    MODELS=$(echo "$RESPONSE" | jq -c '.models[]' 2>/dev/null)
    i=1
    while IFS= read -r m; do
        name=$(echo "$m" | jq -r '.name')
        inst=$(echo "$m" | jq -r '.installed')
        [ "$inst" = true ] && status="✅ installed" || status="not installed"
        [ "$name" = "$DEFAULT_LLM" ] && { star="⭐ "; DEFAULT_IDX_REF=$i; } || star="  "
        if $VERBOSE; then
            printf "%2d) %-80s%s%s\n" "$i" "$name" "$star" "$status"
        fi
        MODEL_NAMES_REF+=("$name")
        ((i++))
    done <<< "$MODELS"

    if [ ${#MODEL_NAMES_REF[@]} -eq 0 ]; then
        echo "❌ No LLM models found"
        exit 1
    fi

    if [ $DEFAULT_IDX_REF -eq -1 ]; then
        echo "❌ Default model $DEFAULT_LLM not found"
        exit 1
    fi
}

install_llm() {
    local LLM_MODEL="$1"

    echo "🧠 installing $LLM_MODEL..."
    echo "This can take a while. Please wait!"

    RESPONSE=$(curl -s -X POST "http://localhost:7346/models/install" \
        -H "Content-Type: application/json" \
        -d "{\"name\": \"$LLM_MODEL\", \"force\": false}")

    INSTALLED_NAME=$(echo "$RESPONSE" | jq -r '.name' 2>/dev/null)
    
    if [ "$INSTALLED_NAME" = "$LLM_MODEL" ]; then
        echo "✅ installation finished for $LLM_MODEL"
        return 0
    else
        echo "❌ installation failed"
        return 1
    fi
}