/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

/*!
 * \file extract_fake_quantized_ops.cc
 * \brief Extract fake quantized operators from an IRModule
 */
#include <tvm/relay/expr.h>
#include <tvm/relay/expr_functor.h>

namespace tvm {
namespace relay {

using ExprSet = std::unordered_set<Expr, ObjectPtrHash, ObjectPtrEqual>;

class FakeQuantizedRegionExtractor : public ExprVisitor {
 public:
  const ExprSet GetRegion(const Expr& expr) {
    VisitExpr(expr);
    ExprSet region;
    for (auto kv : this->visit_counter_) {
      if (auto call_node = GetRef<ObjectRef>(kv.first).as<CallNode>()) {
        if (call_node->op != quantize_op_ && call_node->op != dequantize_op_) {
          region.insert(Downcast<Expr>(GetRef<ObjectRef>(kv.first)));
        }
      }
    }
    return region;
  }

 protected:
  void VisitExpr_(const CallNode* call_node) override {
    if (call_node->op == quantize_op_) {
      // only look at arg0 for quantize
      VisitExpr(call_node->args[0]);
    } else if (call_node->op != dequantize_op_) {
      // run normally on everything else.
      ExprVisitor::VisitExpr_(call_node);
    }
  }

  const Op quantize_op_ = Op::Get("qnn.quantize");
  const Op dequantize_op_ = Op::Get("qnn.dequantize");
};

class ExtractFakeQuantizedOpsWrapper : private MixedModeVisitor {
 public:
  explicit ExtractFakeQuantizedOpsWrapper(const IRModule& mod) : mod_(mod) {}

  Map<String, tvm::Integer> Extract() {
    VisitExpr(this->mod_->Lookup("main"));

    return fake_quantized_op_freqs_;
  }

 private:
  using MixedModeVisitor::VisitExpr_;

  const IRModule mod_;
  /*! \brief Dict of fake quantized op names to frequency counts */
  Map<String, tvm::Integer> fake_quantized_op_freqs_;

  void VisitExpr_(const CallNode* call_node) override {
    if (call_node->op == quantize_op_) {
      FakeQuantizedRegionExtractor extractor;
      ExprSet region = extractor.GetRegion(GetRef<Expr>(call_node));

      for (auto expr : region) {
        const Op op = Downcast<Op>(expr.as<CallNode>()->op);
        auto op_name = op->name;
        if (fake_quantized_op_freqs_.find(op_name) != fake_quantized_op_freqs_.end()) {
          fake_quantized_op_freqs_.Set(op_name, 1 + fake_quantized_op_freqs_.at(op_name));
        } else {
          fake_quantized_op_freqs_.Set(op_name, 1);
        }
      }
    }
  }

  const Op quantize_op_ = Op::Get("qnn.quantize");
  const Op dequantize_op_ = Op::Get("qnn.dequantize");
};

Map<String, tvm::Integer> ExtractFakeQuantizedOpsPacked(const IRModule& mod) {
  return ExtractFakeQuantizedOpsWrapper(mod).Extract();
}

TVM_REGISTER_GLOBAL("relay.analysis.ExtractFakeQuantizedOps")
    .set_body_typed(ExtractFakeQuantizedOpsPacked);

}  // namespace relay
}  // namespace tvm
