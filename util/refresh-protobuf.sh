#!/bin/bash

# Python
protoc --python_out=../packages/pybrid-computing/src/pybrid/base/proto/ --pyi_out=../packages/pybrid-computing/src/pybrid/base/proto/  --proto_path=../proto ../proto/main.proto

# C++
protoc --cpp_out=../packages/pybrid-computing-native/native/pybrid/proto/ --proto_path=../proto ../proto/main.proto
