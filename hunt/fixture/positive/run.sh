#!/bin/sh
# Planted positive fixture for shellcheck: unquoted variables (SC2086) and rm -rf on a
# possibly-empty variable (SC2115).
dir=$1
rm -rf $dir/
echo $dir
