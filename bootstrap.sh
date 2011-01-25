#!/bin/bash

BASE=$(readlink -f $(dirname $0))
VERBOSITY=-vv
PYTHON=/usr/bin/python2.5

if [ ! -d "$BASE/python/bin" ]; then
    echo ================================
    echo Creating buildout for python
    echo ================================

    if [ ! -d "$BASE/python" ]; then
        mkdir "$BASE/python"
        ln -s "$BASE/configs/buildout/buildout_python.cfg" "$BASE/python/buildout.cfg"
    fi
    $PYTHON "$BASE/bootstrap.py" --distribute -c "$BASE/python/buildout.cfg"

    if [ ! -d "$BASE/python/bin" ]; then
        echo "Unable to create buildout for python."
        exit 1
    fi
fi

echo ================================
echo Updating python buildout
echo ================================
"$BASE/python/bin/buildout" $VERBOSITY -c "$BASE/python/buildout.cfg"


if [ ! -d "$BASE/env/bin" ]; then
    echo ================================
    echo Creating buildout for bot
    echo ================================

    if [ ! -d "$BASE/env" ]; then
        mkdir "$BASE/env"
        ln -s "$BASE/configs/buildout/buildout.cfg" "$BASE/env/buildout.cfg"
    fi
    "$BASE/python/bin/python" "$BASE/bootstrap.py" --distribute -c "$BASE/env/buildout.cfg"

    if [ ! -d "$BASE/python/bin" ]; then
        echo "Unable to create buildout for bot."
        exit 1
    fi
fi

echo ================================
echo Updating bot buildout
echo ================================
"$BASE/env/bin/buildout" $VERBOSITY -c "$BASE/env/buildout.cfg"

