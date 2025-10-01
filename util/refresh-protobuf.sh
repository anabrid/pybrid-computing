#!/bin/bash

protoc --python_out=../pybrid/base/proto/ --pyi_out=../pybrid/base/proto/  --proto_path=../proto ../proto/main.proto