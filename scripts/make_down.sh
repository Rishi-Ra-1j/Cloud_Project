#!/usr/bin/env bash
# make down: delete the whole cluster (and everything in it).
set -euo pipefail
k3d cluster delete cs3081
echo "cluster cs3081 deleted."
