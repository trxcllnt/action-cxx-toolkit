#!/bin/bash

# Purpose: good code passes clang-tidy check

realpath() {
    [[ $1 = /* ]] && echo "$1" || echo "$PWD/${1#./}"
}
CURDIR=$(realpath $(dirname "$0"))

docker run --rm -it --workdir /github/workspace -v "${CURDIR}":/github/workspace \
    -e INPUT_CHECKS='clang-tidy' \
    -e INPUT_CC='clang' \
    ${ACTION_CXX_TOOLKIT_REPO:-lucteo/action-cxx-toolkit.}main-ubuntu22.04
status=$?

# Check if the test succeeded
if [ $status -eq 0 ]; then
    echo
    echo "OK"
    echo
else
    echo
    echo "TEST FAILED"
    echo
    exit 1
fi
