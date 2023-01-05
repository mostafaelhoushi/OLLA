#! /usr/bin/sh
# (c) Meta Platforms, Inc. and affiliates. Confidential and proprietary.

set -o xtrace
trap : SIGTERM SIGINT

BENCHMARKS=(
  "bert,train,1"
  "bert,train,32"
  "bert,train,64"
  "bert,train,128"
  "bert,train,256"
  "bert,train,512"
  "bert,train,1024"
  "bert,train,2048"
  "bert,train,4096"
)

first_time=1
for benchmark in "${BENCHMARKS[@]}"; do
  while IFS=',' read -r model mode batch_size; do
    append_log=$([ "${first_time}" == 1 ] && echo || echo "--append-log")

    python benchmarks.py -b "${batch_size}" --model "${model}" --mode "${mode}" ${append_log} $@ &

    # kill python run if user kills shell script, then terminate script
    FIND_PID=$!
    wait $FIND_PID
    if [[ $? -gt 128 ]]
    then
        kill $FIND_PID
        exit 1
    fi

    first_time=0
  done <<< "${benchmark}"
done
