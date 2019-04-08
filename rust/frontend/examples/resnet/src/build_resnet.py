#!/usr/bin/env python3
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import argparse
import csv
import logging
from os import path as osp
import sys

import numpy as np

import mxnet as mx
from mxnet.gluon.model_zoo.vision import get_model
from mxnet.gluon.utils import download

import tvm
from tvm.contrib import graph_runtime, cc
import nnvm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

parser = argparse.ArgumentParser(description='Resnet build example')
aa = parser.add_argument
aa('--batch-size', type=int, default=1, help='input image batch size')
aa('--opt-level', type=int, default=3,
   help='level of optimization. 0 is unoptimized and 3 is the highest level')
aa('--target', type=str, default='llvm', help='target context for compilation')
aa('--image-shape', type=str, default='3,224,224', help='input image dimensions')
aa('--image-name', type=str, default='cat.png', help='name of input image to download')
args = parser.parse_args()

target_dir = osp.dirname(osp.dirname(osp.realpath(__file__)))
batch_size = args.batch_size
opt_level = args.opt_level
target = tvm.target.create(args.target)
image_shape = tuple(map(int, args.image_shape.split(",")))
data_shape = (batch_size,) + image_shape

def build(target_dir):
    """ Compiles resnet18 with TVM"""
    deploy_lib = osp.join(target_dir, 'deploy_lib.o')
    if osp.exists(deploy_lib):
        return
    # download the pretrained resnet18 trained on imagenet1k dataset for
    # image classification task
    block = get_model('resnet18_v1', pretrained=True)

    sym, params = nnvm.frontend.from_mxnet(block)
    # add the softmax layer for prediction
    net = nnvm.sym.softmax(sym)
    # compile the model
    with nnvm.compiler.build_config(opt_level=opt_level):
        graph, lib, params = nnvm.compiler.build(
            net, target, shape={"data": data_shape}, params=params)
    # save the model artifacts
    lib.save(deploy_lib)
    cc.create_shared(osp.join(target_dir, "deploy_lib.so"),
                    [osp.join(target_dir, "deploy_lib.o")])

    with open(osp.join(target_dir, "deploy_graph.json"), "w") as fo:
        fo.write(graph.json())

    with open(osp.join(target_dir,"deploy_param.params"), "wb") as fo:
        fo.write(nnvm.compiler.save_param_dict(params))

def download_img_labels():
    """ Download an image and imagenet1k class labels for test"""
    img_name = 'cat.png'
    synset_url = ''.join(['https://gist.githubusercontent.com/zhreshold/',
                      '4d0b62f3d01426887599d4f7ede23ee5/raw/',
                      '596b27d23537e5a1b5751d2b0481ef172f58b539/',
                      'imagenet1000_clsid_to_human.txt'])
    synset_name = 'synset.txt'
    download('https://github.com/dmlc/mxnet.js/blob/master/data/cat.png?raw=true', img_name)
    download(synset_url, synset_name)

    with open(synset_name) as fin:
        synset = eval(fin.read())

    with open("synset.csv", "w") as fout:
        w = csv.writer(fout)
        w.writerows(synset.items())

def test_build(target_dir):
    """ Sanity check with random input"""
    graph = open(osp.join(target_dir, "deploy_graph.json")).read()
    lib = tvm.module.load(osp.join(target_dir, "deploy_lib.so"))
    params = bytearray(open(osp.join(target_dir,"deploy_param.params"), "rb").read())
    input_data = tvm.nd.array(np.random.uniform(size=data_shape).astype("float32"))
    ctx = tvm.cpu()
    module = graph_runtime.create(graph, lib, ctx)
    module.load_params(params)
    module.run(data=input_data)
    out = module.get_output(0).asnumpy()


if __name__ == '__main__':
    logger.info("building the model")
    build(target_dir)
    logger.info("build was successful")
    logger.info("test the build artifacts")
    test_build(target_dir)
    logger.info("test was successful")
    download_img_labels()
    logger.info("image and synset downloads are successful")
