#!/bin/bash

# Purpose: build a simple project with cmake

realpath() {
    [[ $1 = /* ]] && echo "$1" || echo "$PWD/${1#./}"
}
CURDIR=$(realpath $(dirname "$0"))

# Cleanup before the test
rm -f ${CURDIR}/test_app

docker run --rm -it --workdir /github/workspace -v "${CURDIR}":/github/workspace \
    -e INPUT_CHECKS='install test' \
    -e INPUT_POSTBUILD_COMMAND='cp /tmp/build/test_app /github/workspace/' \
    lucteo/action-cxx-toolkit.main

# Check if the test succeeded
if [ -f ${CURDIR}/test_app ]; then
    rm -f ${CURDIR}/test_app
    echo
    echo "OK"
    echo
else
    echo
    echo "TEST FAILED"
    echo
    exit 1
fi
