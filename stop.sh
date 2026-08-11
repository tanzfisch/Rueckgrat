#!/bin/bash
echo "🛑 Stopping all Rückgrat containers..."
docker ps -q --filter "name=rueckgrat_" | xargs -r docker stop