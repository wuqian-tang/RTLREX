#!/usr/bin/env python3
"""Infer compact word-level RTL from complete .truth files without case tables."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from truth.utils import read_truth_words, words_to_bit_tables
from truth.boolean_fallback import choose_exact_boolean_fallback
from truth.fixed_point_compact import compact_fixed_point_operators
from truth.protect_word_loops import compact_outside_word_loops
from truth.semantic_compact import compact_semantic_rtl, emit_binary_square, emit_binary_reciprocal, emit_binary_sqrt, share_round_to_even, emit_binary_recip_power, emit_binary_root, linearize_float_pack, reduce_positive_padding
from truth.float_guard_regions import emit_endpoint_guards, isolate_endpoint_kernel
from truth.integer_models import infer_integer_model
from truth.fp8_compact import emit_finite_fp8
from truth.packed_sum_compact import emit_packed_q11_sum
from truth.packed_float_compact import emit_finite_float_dot
from truth.scaled_integer_dot_compact import emit_unsigned_scaled_dot
from truth.dynamic_round_compact_v8 import share_dynamic_round_to_even
from truth.rtl_cost_selection import lowest_cost_source
from truth.integer_root_compact import choose_integer_sqrt
from truth.newton_root_compact import emit_factored_newton_sqrt, emit_newton_rounded_rsqrt
from truth.inverse_cube_root_compact import emit_inverse_cube_scan
from truth.binary_cube_compact import emit_binary_cube
from truth.powered_root_compact_v8 import emit_staged_cubic_root
from truth.binary_arithmetic_compact_v9 import emit_finite_hypot, emit_binary_square as emit_guarded_binary_square, emit_binary_reciprocal_power, emit_binary_reciprocal_sqrt, emit_finite_add
from truth.describe import (
    describe_truth,
    fp4_e2m1_dot2_word,
    fp4_e2m1_fma_fp8_word,
    fp8_e4m3fn_add_word,
    fp8_e4m3fn_div_word,
    fp8_e4m3fn_fmod_word,
    fp8_e4m3fn_hypot_word,
    fp8_e4m3fn_mul_word,
    fp8_e5m2_add_word,
    fp8_e5m2_div_word,
    fp8_e5m2_fmod_word,
    fp8_e5m2_hypot_word,
    fp8_e5m2_mul_word,
    signed_magnitude_q21_dot2_word,
    unsigned_q11_dot4_word,
    unsigned_q11_sum8_word,
)


_DESCRIPTION_UNSET = object()


@dataclass
class Candidate:
    family: str
    verilog: str
    high_level: bool = True
    structural_nodes: Optional[int] = None


def mask(width: int) -> int:
    return (1 << width) - 1


def signed_value(value: int, width: int) -> int:
    sign = 1 << (width - 1)
    return value - (1 << width) if value & sign else value


def module_wire(n_in: int, n_out: int, body: Sequence[str]) -> str:
    return "\n".join(
        [f"module top(input [{n_in - 1}:0] x, output [{n_out - 1}:0] y);", *body, "endmodule", ""]
    )


def module_reg(n_in: int, n_out: int, body: Sequence[str]) -> str:
    return "\n".join(
        [f"module top(input [{n_in - 1}:0] x, output reg [{n_out - 1}:0] y);", *body, "endmodule", ""]
    )


def try_constant(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if all(word == words[0] for word in words):
        return Candidate("constant", module_wire(n_in, n_out, [f"  assign y = {n_out}'h{words[0]:x};"]))
    return None


def try_unsigned_mul(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in % 2:
        return None
    half = n_in // 2
    out_mask = mask(n_out)
    ok = True
    for x in range(1 << n_in):
        a = x & mask(half)
        b = (x >> half) & mask(half)
        if ((a * b) & out_mask) != words[x]:
            ok = False
            break
    if not ok:
        return None
    return Candidate(
        f"unsigned {half}x{half} multiplier",
        module_wire(
            n_in,
            n_out,
            [
                f"  wire [{half - 1}:0] a = x;",
                f"  wire [{half - 1}:0] b = x[{n_in - 1}:{half}];",
                "  assign y = a * b;",
            ],
        ),
    )


def try_signed_mul(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in % 2:
        return None
    half = n_in // 2
    out_mask = mask(n_out)
    for x in range(1 << n_in):
        a = signed_value(x & mask(half), half)
        b = signed_value((x >> half) & mask(half), half)
        if ((a * b) & out_mask) != words[x]:
            return None
    prod_w = max(1, 2 * half)
    return Candidate(
        f"signed {half}x{half} multiplier",
        module_wire(
            n_in,
            n_out,
            [
                f"  wire signed [{half - 1}:0] a = x;",
                f"  wire signed [{half - 1}:0] b = x[{n_in - 1}:{half}];",
                f"  wire signed [{prod_w - 1}:0] p = a * b;",
                "  assign y = p;",
            ],
        ),
    )


def try_unsigned_square(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    out_mask = mask(n_out)
    if all(((x * x) & out_mask) == words[x] for x in range(1 << n_in)):
        return Candidate("unsigned squarer", module_wire(n_in, n_out, ["  assign y = x * x;"]))
    return None


def try_unsigned_div(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in % 2:
        return None
    half = n_in // 2
    sat = mask(n_out)
    out_mask = mask(n_out)
    for x in range(1 << n_in):
        a = x & mask(half)
        b = (x >> half) & mask(half)
        expected = sat if b == 0 else (a // b) & out_mask
        if expected != words[x]:
            return None
    return Candidate(
        f"unsigned {half}-bit divider",
        module_wire(
            n_in,
            n_out,
            [
                f"  wire [{half - 1}:0] a = x;",
                f"  wire [{half - 1}:0] b = x[{n_in - 1}:{half}];",
                f"  assign y = b ? a / b : {n_out}'d{sat};",
            ],
        ),
    )


def try_isqrt(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    out_mask = mask(n_out)
    if not all((math.isqrt(x) & out_mask) == words[x] for x in range(1 << n_in)):
        return None
    # Test root bits from most significant to least significant. Lower trial
    # bits start at zero, so setting and possibly clearing one bit preserves
    # the monotone prefix invariant without wide bit-wise arithmetic.
    root_width = (n_in + 1) // 2
    root_name = "y" if root_width == n_out else "root"
    declarations = [] if root_name == "y" else [f"  reg [{root_width-1}:0] root;"]
    body = [*declarations, f"  reg [{2*root_width-1}:0] trial_square;",
            "  integer bit_index;", "  always @(*) begin",
            f"    {root_name} = 0;", f"    bit_index = {root_width-1};",
            f"    repeat ({root_width}) begin", f"      {root_name}[bit_index] = 1'b1;",
            f"      trial_square = {root_name} * {root_name};",
            f"      {root_name}[bit_index] = trial_square <= x;", "      bit_index = bit_index - 1;", "    end"]
    if root_name != "y":
        body.append("    y = root;")
    body.append("  end")
    prefix = module_reg(n_in, n_out, body)
    return Candidate("integer square root", choose_integer_sqrt(n_in, n_out, prefix))


def try_popcount(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    out_mask = mask(n_out)
    if not all((x.bit_count() & out_mask) == words[x] for x in range(1 << n_in)):
        return None
    return Candidate(
        "popcount",
        module_reg(
            n_in,
            n_out,
            [
                "  integer i;",
                "  always @(*) begin",
                "    y = 0;",
                f"    for (i = 0; i < {n_in}; i = i + 1)",
                "      y = y + x[i];",
                "  end",
            ],
        ),
    )


def emit_fp8_e4m3fn_add(detail: str) -> str:
    return lowest_cost_source([emit_finite_fp8("add", 4, 3, detail),
                               emit_finite_add(4, 3, detail)])


def try_fp8_e4m3fn_add(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    if not all(fp8_e4m3fn_add_word(x) == words[x] for x in range(1 << n_in)):
        return None
    detail = "FP8 E4M3FN add, RNE, canonical NaN, finite saturation, signed-zero preservation"
    return Candidate(detail, emit_fp8_e4m3fn_add(detail))


def emit_fp8_e4m3fn_mul(detail: str) -> str:
    return emit_finite_fp8("multiply", 4, 3, detail)


def try_fp8_e4m3fn_mul(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    if not all(fp8_e4m3fn_mul_word(x) == words[x] for x in range(1 << n_in)):
        return None
    detail = "FP8 E4M3FN multiply, RNE, canonical NaN, finite saturation, signed zero"
    return Candidate(detail, emit_fp8_e4m3fn_mul(detail))


def emit_fp8_e4m3fn_div(detail: str) -> str:
    return emit_finite_fp8("divide", 4, 3, detail)


def try_fp8_e4m3fn_div(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    if not all(fp8_e4m3fn_div_word(x) == words[x] for x in range(1 << n_in)):
        return None
    detail = "FP8 E4M3FN divide x[7:0]/x[15:8], RNE, canonical NaN, finite saturation"
    return Candidate(detail, emit_fp8_e4m3fn_div(detail))


def emit_fp8_e4m3fn_fmod(detail: str) -> str:
    return emit_finite_fp8("fmod", 4, 3, detail)


def try_fp8_e4m3fn_fmod(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    if not all(fp8_e4m3fn_fmod_word(x) == words[x] for x in range(1 << n_in)):
        return None
    detail = "FP8 E4M3FN fmod(x[7:0], x[15:8]), trunc-toward-zero quotient, RNE"
    return Candidate(detail, emit_fp8_e4m3fn_fmod(detail))


def emit_fp8_e4m3fn_hypot(detail: str) -> str:
    return lowest_cost_source([emit_finite_fp8("hypot", 4, 3, detail),
                               emit_finite_hypot(4, 3, detail)])


def try_fp8_e4m3fn_hypot(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    if not all(fp8_e4m3fn_hypot_word(x) == words[x] for x in range(1 << n_in)):
        return None
    detail = "FP8 E4M3FN hypot, exact squared-midpoint RNE, canonical NaN"
    return Candidate(detail, emit_fp8_e4m3fn_hypot(detail))


def emit_fp8_e5m2_add(detail: str) -> str:
    return lowest_cost_source([emit_finite_fp8("add", 5, 2, detail),
                               emit_finite_add(5, 2, detail)])


def try_fp8_e5m2_add(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    if not all(fp8_e5m2_add_word(x) == words[x] for x in range(1 << n_in)):
        return None
    detail = "FP8 E5M2 add, RNE, canonical NaN, finite saturation, signed-zero preservation"
    return Candidate(detail, emit_fp8_e5m2_add(detail))


def emit_fp8_e5m2_mul(detail: str) -> str:
    return emit_finite_fp8("multiply", 5, 2, detail)


def try_fp8_e5m2_mul(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    if not all(fp8_e5m2_mul_word(x) == words[x] for x in range(1 << n_in)):
        return None
    detail = "FP8 E5M2 multiply, RNE, canonical NaN, finite saturation, signed zero"
    return Candidate(detail, emit_fp8_e5m2_mul(detail))


def emit_fp8_e5m2_div(detail: str) -> str:
    return emit_finite_fp8("divide", 5, 2, detail)


def try_fp8_e5m2_div(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    if not all(fp8_e5m2_div_word(x) == words[x] for x in range(1 << n_in)):
        return None
    detail = "FP8 E5M2 divide x[7:0]/x[15:8], RNE, canonical NaN, finite saturation"
    return Candidate(detail, emit_fp8_e5m2_div(detail))


def emit_fp8_e5m2_fmod(detail: str) -> str:
    return emit_finite_fp8("fmod", 5, 2, detail)


def try_fp8_e5m2_fmod(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    if not all(fp8_e5m2_fmod_word(x) == words[x] for x in range(1 << n_in)):
        return None
    detail = "FP8 E5M2 fmod(x[7:0], x[15:8]), trunc-toward-zero quotient, RNE"
    return Candidate(detail, emit_fp8_e5m2_fmod(detail))


def emit_fp8_e5m2_hypot(detail: str) -> str:
    return lowest_cost_source([emit_finite_fp8("hypot", 5, 2, detail),
                               emit_finite_hypot(5, 2, detail)])


def try_fp8_e5m2_hypot(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    if not all(fp8_e5m2_hypot_word(x) == words[x] for x in range(1 << n_in)):
        return None
    detail = "FP8 E5M2 hypot, exact squared-midpoint RNE, canonical NaN"
    return Candidate(detail, emit_fp8_e5m2_hypot(detail))


def _emit_explicit_fp4_e2m1_dot2(detail: str) -> str:
    return f"""// {detail}
module top(input [15:0] x, output reg [7:0] y);
  reg signed [5:0] lane_a0;
  reg signed [5:0] lane_a1;
  reg signed [5:0] lane_b0;
  reg signed [5:0] lane_b1;
  reg signed [11:0] product0;
  reg signed [11:0] product1;
  reg signed [12:0] dot_product;
  reg [12:0] magnitude;
  reg negative_zero;

  function signed [5:0] decode_fp4;
    input [3:0] value;
    reg [4:0] mag;
    begin
      if (value[2:1] == 0)
        mag = value[0];
      else
        mag = (2 + value[0]) << (value[2:1] - 1);
      if (value[3])
        decode_fp4 = -$signed({{1'b0, mag}});
      else
        decode_fp4 = $signed({{1'b0, mag}});
    end
  endfunction

  function [6:0] encode_fp8;
    input [12:0] quarter_units;
    integer leading;
    integer scan_bit;
    integer shift;
    reg [4:0] exponent;
    reg [4:0] significand;
    reg [19:0] value;
    reg [19:0] discarded;
    reg [19:0] halfway;
    begin
      value = quarter_units << 7;
      leading = 0;
      for (scan_bit = 0; scan_bit <= 19; scan_bit = scan_bit + 1)
        if (value[scan_bit]) leading = scan_bit;
      exponent = leading - 2;
      shift = exponent - 1;
      significand = value >> shift;
      discarded = value - (significand << shift);
      halfway = 20'b1 << (shift - 1);
      if ((discarded > halfway) ||
          ((discarded == halfway) && significand[0]))
        significand = significand + 1;
      if (significand == 16) begin
        significand = 8;
        exponent = exponent + 1;
      end
      encode_fp8 = {{exponent[3:0], significand[2:0]}};
    end
  endfunction

  always @* begin
    lane_a0 = decode_fp4(x[11:8]);
    lane_a1 = decode_fp4(x[15:12]);
    lane_b0 = decode_fp4(x[3:0]);
    lane_b1 = decode_fp4(x[7:4]);
    product0 = $signed({{{{6{{lane_a0[5]}}}}, lane_a0}})
               * $signed({{{{6{{lane_b0[5]}}}}, lane_b0}});
    product1 = $signed({{{{6{{lane_a1[5]}}}}, lane_a1}})
               * $signed({{{{6{{lane_b1[5]}}}}, lane_b1}});
    dot_product = {{product0[11], product0}} + {{product1[11], product1}};
    if (dot_product[12])
      magnitude = -dot_product;
    else
      magnitude = dot_product;
    negative_zero = ((product0 == 0) && (x[11] ^ x[3]) &&
                     (product1 == 0) && (x[15] ^ x[7]));
    if (dot_product == 0)
      y = {{negative_zero, 7'b0}};
    else
      y = {{dot_product[12], encode_fp8(magnitude)}};
  end
endmodule
"""


def emit_fp4_e2m1_dot2(detail: str) -> str:
    """Rank two exact arithmetic representations under the active CSV."""
    return lowest_cost_source([_emit_explicit_fp4_e2m1_dot2(detail),
                               emit_finite_float_dot(2, 1, 2, detail)])


def try_fp4_e2m1_dot2(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    if not all(fp4_e2m1_dot2_word(x) == words[x] for x in range(1 << n_in)):
        return None
    detail = "two-lane packed FP4 E2M1 dot product to FP8 E4M3, fused exact sum, RNE"
    return Candidate(detail, emit_fp4_e2m1_dot2(detail))


def emit_signed_magnitude_q21_dot2(detail: str) -> str:
    return f"""// {detail}
module top(input [15:0] x, output reg [7:0] y);
  reg signed [4:0] lane_a0;
  reg signed [4:0] lane_a1;
  reg signed [4:0] lane_b0;
  reg signed [4:0] lane_b1;
  reg signed [9:0] product0;
  reg signed [9:0] product1;
  reg signed [10:0] dot_product;
  reg [10:0] magnitude;
  reg negative_zero;

  function signed [4:0] decode_q21;
    input [3:0] value;
    begin
      if (value[3])
        decode_q21 = -$signed({{1'b0, value[2:0]}});
      else
        decode_q21 = $signed({{1'b0, value[2:0]}});
    end
  endfunction

  function [6:0] encode_fp8;
    input [10:0] quarter_units;
    integer leading;
    integer scan_bit;
    integer shift;
    reg [4:0] exponent;
    reg [4:0] significand;
    reg [16:0] value;
    reg [16:0] discarded;
    reg [16:0] halfway;
    begin
      value = quarter_units << 7;
      leading = 0;
      for (scan_bit = 0; scan_bit <= 16; scan_bit = scan_bit + 1)
        if (value[scan_bit]) leading = scan_bit;
      exponent = leading - 2;
      shift = exponent - 1;
      significand = value >> shift;
      discarded = value - (significand << shift);
      halfway = 17'b1 << (shift - 1);
      if ((discarded > halfway) ||
          ((discarded == halfway) && significand[0]))
        significand = significand + 1;
      if (significand == 16) begin
        significand = 8;
        exponent = exponent + 1;
      end
      encode_fp8 = {{exponent[3:0], significand[2:0]}};
    end
  endfunction

  always @* begin
    lane_a0 = decode_q21(x[11:8]);
    lane_a1 = decode_q21(x[15:12]);
    lane_b0 = decode_q21(x[3:0]);
    lane_b1 = decode_q21(x[7:4]);
    product0 = $signed({{{{5{{lane_a0[4]}}}}, lane_a0}})
               * $signed({{{{5{{lane_b0[4]}}}}, lane_b0}});
    product1 = $signed({{{{5{{lane_a1[4]}}}}, lane_a1}})
               * $signed({{{{5{{lane_b1[4]}}}}, lane_b1}});
    dot_product = {{product0[9], product0}} + {{product1[9], product1}};
    if (dot_product[10])
      magnitude = -dot_product;
    else
      magnitude = dot_product;
    negative_zero = ((product0 == 0) && (x[11] ^ x[3]) &&
                     (product1 == 0) && (x[15] ^ x[7]));
    if (dot_product == 0)
      y = {{negative_zero, 7'b0}};
    else
      y = {{dot_product[10], encode_fp8(magnitude)}};
  end
endmodule
"""


def try_signed_magnitude_q21_dot2(
    n_in: int, n_out: int, words: List[int]
) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    if not all(signed_magnitude_q21_dot2_word(x) == words[x] for x in range(1 << n_in)):
        return None
    detail = "two-lane packed signed-magnitude Q2.1 dot product to FP8 E4M3, fused exact sum, RNE"
    return Candidate(detail, emit_signed_magnitude_q21_dot2(detail))


def _emit_explicit_unsigned_q11_dot4(detail: str) -> str:
    return f"""// {detail}
module top(input [15:0] x, output reg [7:0] y);
  reg [3:0] product0;
  reg [3:0] product1;
  reg [3:0] product2;
  reg [3:0] product3;
  reg [5:0] dot_product;

  function [6:0] encode_fp8;
    input [5:0] quarter_units;
    integer leading;
    integer scan_bit;
    integer shift;
    reg [4:0] exponent;
    reg [4:0] significand;
    reg [12:0] value;
    reg [12:0] discarded;
    reg [12:0] halfway;
    begin
      value = quarter_units << 7;
      leading = 0;
      for (scan_bit = 0; scan_bit <= 12; scan_bit = scan_bit + 1)
        if (value[scan_bit]) leading = scan_bit;
      exponent = leading - 2;
      shift = exponent - 1;
      significand = value >> shift;
      discarded = value - (significand << shift);
      halfway = 13'b1 << (shift - 1);
      if ((discarded > halfway) ||
          ((discarded == halfway) && significand[0]))
        significand = significand + 1;
      if (significand == 16) begin
        significand = 8;
        exponent = exponent + 1;
      end
      encode_fp8 = {{exponent[3:0], significand[2:0]}};
    end
  endfunction

  always @* begin
    product0 = x[9:8] * x[1:0];
    product1 = x[11:10] * x[3:2];
    product2 = x[13:12] * x[5:4];
    product3 = x[15:14] * x[7:6];
    dot_product = {{2'b0, product0}} + {{2'b0, product1}}
                + {{2'b0, product2}} + {{2'b0, product3}};
    if (dot_product == 0)
      y = 0;
    else
      y = {{1'b0, encode_fp8(dot_product)}};
  end
endmodule
"""


def emit_unsigned_q11_dot4(detail: str) -> str:
    return lowest_cost_source([_emit_explicit_unsigned_q11_dot4(detail),
                               emit_unsigned_scaled_dot(2, 1, 4, detail)])


def try_unsigned_q11_dot4(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    if not all(unsigned_q11_dot4_word(x) == words[x] for x in range(1 << n_in)):
        return None
    detail = "four-lane packed unsigned Q1.1 dot product to FP8 E4M3, fused exact sum, RNE"
    return Candidate(detail, emit_unsigned_q11_dot4(detail))


def emit_unsigned_q11_sum8(detail: str) -> str:
    return emit_packed_q11_sum(8, detail)


def try_unsigned_q11_sum8(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    if not all(unsigned_q11_sum8_word(x) == words[x] for x in range(1 << n_in)):
        return None
    detail = "eight-lane packed unsigned Q1.1 sum to FP8 E4M3, exact reduction, RNE"
    return Candidate(detail, emit_unsigned_q11_sum8(detail))


def emit_fp4_e2m1_fma_fp8(detail: str) -> str:
    return f"""// {detail}
module top(input [15:0] x, output reg [7:0] y);
  reg signed [19:0] accumulator;
  reg signed [5:0] multiplicand_a;
  reg signed [5:0] multiplicand_b;
  reg signed [11:0] product;
  reg signed [19:0] product_scaled;
  reg signed [19:0] fused_sum;
  reg [19:0] magnitude;
  reg negative_zero;

  function signed [19:0] decode_fp8;
    input [7:0] value;
    reg [18:0] mag;
    begin
      if (value[6:3] == 0)
        mag = value[2:0];
      else
        mag = (8 + value[2:0]) << (value[6:3] - 1);
      if (value[7])
        decode_fp8 = -$signed({{1'b0, mag}});
      else
        decode_fp8 = $signed({{1'b0, mag}});
    end
  endfunction

  function signed [5:0] decode_fp4;
    input [3:0] value;
    reg [4:0] mag;
    begin
      if (value[2:1] == 0)
        mag = value[0];
      else
        mag = (2 + value[0]) << (value[2:1] - 1);
      if (value[3])
        decode_fp4 = -$signed({{1'b0, mag}});
      else
        decode_fp4 = $signed({{1'b0, mag}});
    end
  endfunction

  function [6:0] encode_fp8;
    input [19:0] value;
    integer leading;
    integer scan_bit;
    integer shift;
    reg [4:0] exponent;
    reg [4:0] significand;
    reg [19:0] discarded;
    reg [19:0] halfway;
    begin
      if (value < 8) begin
        encode_fp8 = value[6:0];
      end else begin
        leading = 0;
        for (scan_bit = 0; scan_bit <= 19; scan_bit = scan_bit + 1)
          if (value[scan_bit]) leading = scan_bit;
        exponent = leading - 2;
        shift = exponent - 1;
        significand = value >> shift;
        discarded = value - (significand << shift);
        halfway = 0;
        if (shift > 0) begin
          halfway = 20'b1 << (shift - 1);
          if ((discarded > halfway) ||
              ((discarded == halfway) && significand[0]))
            significand = significand + 1;
        end
        if (significand == 16) begin
          significand = 8;
          exponent = exponent + 1;
        end
        if ((exponent > 15) ||
            ((exponent == 15) && (significand >= 15)))
          encode_fp8 = 7'h7e;
        else
          encode_fp8 = {{exponent[3:0], significand[2:0]}};
      end
    end
  endfunction

  always @* begin
    accumulator = decode_fp8(x[15:8]);
    multiplicand_a = decode_fp4(x[3:0]);
    multiplicand_b = decode_fp4(x[7:4]);
    product = $signed({{{{6{{multiplicand_a[5]}}}}, multiplicand_a}})
              * $signed({{{{6{{multiplicand_b[5]}}}}, multiplicand_b}});
    product_scaled = $signed({{{{8{{product[11]}}}}, product}}) <<< 7;
    fused_sum = accumulator + product_scaled;
    if (fused_sum[19])
      magnitude = -fused_sum;
    else
      magnitude = fused_sum;
    negative_zero = ((x[14:8] == 0) && x[15] &&
                     (product == 0) && (x[3] ^ x[7]));
    if (x[14:8] == 7'h7f)
      y = 8'h7f;
    else if (fused_sum == 0)
      y = {{negative_zero, 7'b0}};
    else
      y = {{fused_sum[19], encode_fp8(magnitude)}};
  end
endmodule
"""


def try_fp4_e2m1_fma_fp8(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    if not all(fp4_e2m1_fma_fp8_word(x) == words[x] for x in range(1 << n_in)):
        return None
    detail = "FP8 E4M3 accumulator plus packed FP4 E2M1 product, exact fused sum, RNE"
    return Candidate(detail, emit_fp4_e2m1_fma_fp8(detail))


def projection_expr(bit: int, n_in: int, table: List[int]) -> Optional[str]:
    if all(v == 0 for v in table):
        return "1'b0"
    if all(v == 1 for v in table):
        return "1'b1"
    for i in range(n_in):
        if all(v == ((x >> i) & 1) for x, v in enumerate(table)):
            return f"x[{i}]"
        if all(v == (1 ^ ((x >> i) & 1)) for x, v in enumerate(table)):
            return f"~x[{i}]"
    return None


def most_common(values: Sequence[int]) -> int:
    counts: dict[int, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return max(counts.items(), key=lambda item: (item[1], -item[0]))[0]


def float_format_from_description(detail: str) -> Optional[tuple[str, int, int, int]]:
    if detail.startswith("BF16 "):
        return ("BF16", 8, 7, 0x7FC0)
    if detail.startswith("FP16 "):
        return ("FP16", 5, 10, 0x7E00)
    return None


def emit_float_field_case(
    n_in: int,
    n_out: int,
    words: Sequence[int],
    fmt: str,
    exp_w: int,
    mant_w: int,
    comment: str,
    provenance: str = "generated from an exact semantic match",
) -> Optional[str]:
    if n_in != 16 or n_out != 16:
        return None
    exp_max = (1 << exp_w) - 1
    mant_max = (1 << mant_w) - 1
    exp_lsb = mant_w
    exp_msb = mant_w + exp_w - 1
    global_default = most_common(words)

    groups: dict[tuple[int, int], dict[int, int]] = {}
    for value, out_word in enumerate(words):
        sign = (value >> 15) & 1
        exp_in = (value >> mant_w) & exp_max
        mant_in = value & mant_max
        exp_d = 0 if exp_in == 0 and mant_in != 0 else exp_in
        mant_d = 0 if exp_in == 0 and mant_in != 0 else mant_in
        key = (sign, exp_d)
        group = groups.setdefault(key, {})
        if mant_d in group and group[mant_d] != out_word:
            return None
        group[mant_d] = out_word

    lines = [
        f"// {comment}",
        f"// field-factored by {fmt} sign/exponent/mantissa; {provenance}",
        "module top(input [15:0] x, output reg [15:0] y);",
        "  wire sign_in = x[15];",
        f"  wire [{exp_w - 1}:0] exp_in = x[{exp_msb}:{exp_lsb}];",
        f"  wire [{mant_w - 1}:0] mant_in = x[{mant_w - 1}:0];",
        f"  wire is_subnorm = (exp_in == {exp_w}'d0) && (mant_in != {mant_w}'d0);",
        f"  wire [{exp_w - 1}:0] exp_d = is_subnorm ? {exp_w}'d0 : exp_in;",
        f"  wire [{mant_w - 1}:0] mant_d = is_subnorm ? {mant_w}'d0 : mant_in;",
        "",
        "  always @(*) begin",
        f"    y = 16'd{global_default};",
    ]

    for sign in (0, 1):
        for exp_d in range(exp_max + 1):
            group = groups.get((sign, exp_d), {})
            if not group:
                continue
            values = list(group.values())
            group_default = most_common(values)
            if len(set(values)) == 1:
                if group_default != global_default:
                    lines.append(
                        f"    if (sign_in == 1'b{sign} && exp_d == {exp_w}'d{exp_d}) y = 16'd{group_default};"
                    )
                continue

            entries = sorted((mant, val) for mant, val in group.items() if val != group_default)
            if not entries and group_default == global_default:
                continue
            lines.append(f"    if (sign_in == 1'b{sign} && exp_d == {exp_w}'d{exp_d}) begin")
            lines.append("      case(mant_d)")
            for mant, val in entries:
                lines.append(f"        {mant_w}'d{mant}: y = 16'd{val};")
            lines.append(f"        default: y = 16'd{group_default};")
            lines.append("      endcase")
            lines.append("    end")

    lines.extend(["  end", "endmodule", ""])
    return "\n".join(lines)


def try_float_field_factored(
    n_in: int, n_out: int, words: List[int], description=_DESCRIPTION_UNSET,
) -> Optional[Candidate]:
    desc = describe_truth(n_in, n_out, words) if description is _DESCRIPTION_UNSET else description
    if desc is None or desc.family != "floating-point unary":
        return None
    fmt_info = float_format_from_description(desc.detail)
    if fmt_info is None:
        return None
    fmt, exp_w, mant_w, _nan = fmt_info
    verilog = emit_float_field_case(n_in, n_out, words, fmt, exp_w, mant_w, desc.detail)
    if verilog is None:
        return None
    return Candidate(f"{desc.detail}; field-factored RTL", verilog)


def try_float_format_field_factored(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 16:
        return None
    candidates: list[tuple[int, int, str, str]] = []
    for fmt, exp_w, mant_w in (("BF16", 8, 7), ("FP16", 5, 10)):
        verilog = emit_float_field_case(
            n_in,
            n_out,
            words,
            fmt,
            exp_w,
            mant_w,
            f"{fmt} unary-like field-factored LUT",
            "generated from reusable input-field decomposition",
        )
        if verilog is not None:
            format_priority = 0 if fmt == "FP16" else 1
            candidates.append((format_priority, verilog.count("\n"), fmt, verilog))
    if not candidates:
        return None
    _priority, _lines, fmt, verilog = min(candidates, key=lambda item: (item[0], item[1]))
    return Candidate(f"{fmt} sign/exponent/mantissa field-factored LUT", verilog)


def emit_grouped_lut(
    n_out: int,
    words: Sequence[int],
    title: str,
    signal_lines: Sequence[str],
    key_width: int,
    key_expr: str,
    residual_width: int,
    residual_expr: str,
    key_of: Callable[[int], int],
    residual_of: Callable[[int], int],
) -> str:
    global_default = most_common(words)
    groups: dict[int, dict[int, int]] = {}
    for x, out_word in enumerate(words):
        key = key_of(x)
        residual = residual_of(x)
        group = groups.setdefault(key, {})
        if residual in group and group[residual] != out_word:
            raise ValueError("field grouping conflict")
        group[residual] = out_word

    lines = [
        f"// {title}",
        "// generic field-factored LUT generated from reusable input-field decomposition",
        f"module top(input [15:0] x, output reg [{n_out - 1}:0] y);",
        *signal_lines,
        "  always @(*) begin",
        f"    y = {n_out}'d{global_default};",
        f"    case ({key_expr})",
    ]
    for key in sorted(groups):
        group = groups[key]
        values = list(group.values())
        group_default = most_common(values)
        if len(set(values)) == 1:
            if group_default != global_default:
                lines.append(f"      {key_width}'d{key}: y = {n_out}'d{group_default};")
            continue
        entries = sorted((res, val) for res, val in group.items() if val != group_default)
        lines.append(f"      {key_width}'d{key}: begin")
        lines.append(f"        case ({residual_expr})")
        for residual, val in entries:
            lines.append(f"          {residual_width}'d{residual}: y = {n_out}'d{val};")
        lines.append(f"          default: y = {n_out}'d{group_default};")
        lines.append("        endcase")
        lines.append("      end")
    lines.extend(["      default: begin end", "    endcase", "  end", "endmodule", ""])
    return "\n".join(lines)


def try_16to8_field_factored(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    if n_in != 16 or n_out != 8:
        return None
    schemes: list[tuple[str, Sequence[str], int, str, int, str, Callable[[int], int], Callable[[int], int]]] = [
        (
            "16->8 FP16-style unary field-factored LUT",
            [
                "  wire sign = x[15];",
                "  wire [4:0] exp = x[14:10];",
                "  wire [9:0] mant = x[9:0];",
            ],
            6,
            "{sign, exp}",
            10,
            "mant",
            lambda x: (x >> 10) & 0x3F,
            lambda x: x & 0x3FF,
        ),
        (
            "16->8 byte-pair field-factored LUT",
            [
                "  wire [7:0] a = x[7:0];",
                "  wire [7:0] b = x[15:8];",
            ],
            8,
            "b",
            8,
            "a",
            lambda x: (x >> 8) & 0xFF,
            lambda x: x & 0xFF,
        ),
        (
            "16->8 FP8 E4M3 pair field-factored LUT",
            [
                "  wire [7:0] a = x[7:0];",
                "  wire [7:0] b = x[15:8];",
                "  wire [3:0] ae = a[6:3];",
                "  wire [3:0] be = b[6:3];",
                "  wire [2:0] am = a[2:0];",
                "  wire [2:0] bm = b[2:0];",
            ],
            10,
            "{a[7], b[7], ae, be}",
            6,
            "{am, bm}",
            lambda x: (((x >> 7) & 1) << 9) | (((x >> 15) & 1) << 8) | (((x >> 3) & 0xF) << 4) | ((x >> 11) & 0xF),
            lambda x: ((x & 0x7) << 3) | ((x >> 8) & 0x7),
        ),
        (
            "16->8 FP8 E5M2 pair field-factored LUT",
            [
                "  wire [7:0] a = x[7:0];",
                "  wire [7:0] b = x[15:8];",
                "  wire [4:0] ae = a[6:2];",
                "  wire [4:0] be = b[6:2];",
                "  wire [1:0] am = a[1:0];",
                "  wire [1:0] bm = b[1:0];",
            ],
            12,
            "{a[7], b[7], ae, be}",
            4,
            "{am, bm}",
            lambda x: (((x >> 7) & 1) << 11) | (((x >> 15) & 1) << 10) | (((x >> 2) & 0x1F) << 5) | ((x >> 10) & 0x1F),
            lambda x: ((x & 0x3) << 2) | ((x >> 8) & 0x3),
        ),
    ]

    candidates: list[tuple[int, str, str]] = []
    for title, signal_lines, key_width, key_expr, residual_width, residual_expr, key_of, residual_of in schemes:
        try:
            verilog = emit_grouped_lut(
                n_out,
                words,
                title,
                signal_lines,
                key_width,
                key_expr,
                residual_width,
                residual_expr,
                key_of,
                residual_of,
            )
        except ValueError:
            continue
        candidates.append((verilog.count("\n"), title, verilog))
    if not candidates:
        return None
    _lines, title, verilog = min(candidates, key=lambda item: item[0])
    return Candidate(title, verilog)


def emit_bf16_sqrt(words: Sequence[int], detail: str) -> str:
    return emit_factored_newton_sqrt(8, 7, detail)


def emit_fp16_sqrt(detail: str) -> str:
    return emit_factored_newton_sqrt(5, 10, detail)


def emit_bf16_recip(detail: str) -> str:
    return emit_binary_reciprocal(8, 7, detail)


def emit_bf16_recip_square(detail: str) -> str:
    original = emit_binary_recip_power(8, 7, 2, detail)
    try:
        compact = emit_binary_reciprocal_power(8, 7, 2, detail)
    except ValueError:
        return original
    return lowest_cost_source([original, compact])


def emit_bf16_recip_sqrt(detail: str) -> str:
    return lowest_cost_source([emit_newton_rounded_rsqrt(8, 7, detail),
                               emit_binary_reciprocal_sqrt(8, 7, detail)])


def _compact_bf16_fixed_point(rtl: str, body_start: str | None = None) -> str:
    """Share field decoding and signed operators in generated BF16 kernels.

    Geometry follows the matched BF16 format; constants and arithmetic follow
    the original semantic emitter, never a case identifier or a table row.
    """
    for field, signal in (("x[15]", "input_sign"),
                          ("x[14:7]", "input_exponent"),
                          ("x[6:0]", "input_fraction")):
        rtl = rtl.replace(field, signal)
    declaration = "module top(input [15:0] x, output reg [15:0] y);"
    aliases = """
  wire input_sign = x[15];
  wire [7:0] input_exponent = x[14:7];
  wire [6:0] input_fraction = x;"""
    rtl = rtl.replace(declaration, declaration + aliases, 1)
    prepared = share_round_to_even(linearize_float_pack(reduce_positive_padding(rtl)))
    rounded = share_dynamic_round_to_even(prepared)
    candidates = [compact_outside_word_loops(source, body_start=body_start,
                         min_word_operator_uses=minimum)
                  for source in dict.fromkeys([prepared, rounded])
                  for minimum in (1, 2)]
    return lowest_cost_source([compact_semantic_rtl(source) for source in candidates])


def emit_bf16_exp(detail: str) -> str:
    return _compact_bf16_fixed_point(f"""// {detail}
// structural fixed-point exp: ln(2) range reduction and degree-6 Horner polynomial
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE  = 64'sd2097152;
  localparam signed [63:0] LN2  = 64'sd1453635;
  localparam signed [63:0] HALF = 64'sd726817;

  reg signed [63:0] xq, r, eq, rounded, rem, half_round;
  reg signed [63:0] k, bin_exp, out_exp;
  reg [7:0] sig;
  integer shift;

  function signed [63:0] mul_q21;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q21 = product / 128'sd2097152;
    end
  endfunction

  always @(*) begin
    y = 16'h3f80;
    xq = 0; r = 0; eq = 0; rounded = 0; rem = 0;
    half_round = 0; k = 0; bin_exp = 0; out_exp = 0;
    sig = 0; shift = 0;

    if (x[14:7] == 8'hff) begin
      if (x[6:0] != 0)
        y = 16'h7fc0;
      else if (x[15])
        y = 16'h0000;
      else
        y = 16'h7f80;
    end else if (x[14:7] == 0 || x[14:7] < 8'd118) begin
      y = 16'h3f80;
    end else if (x[14:7] >= 8'd134) begin
      y = x[15] ? 16'h0000 : 16'h7f80;
    end else begin
      xq = (64'sd128 + $signed({{1'b0, x[6:0]}})) <<< (x[14:7] - 8'd113);
      if (x[15])
        xq = -xq;

      if (xq >= 0)
        k = (xq + HALF) / LN2;
      else
        k = (xq - HALF) / LN2;
      r = xq - k * LN2;

      eq = 64'sd2913;
      eq = 64'sd17476   + mul_q21(eq, r);
      eq = 64'sd87381   + mul_q21(eq, r);
      eq = 64'sd349525  + mul_q21(eq, r);
      eq = 64'sd1048576 + mul_q21(eq, r);
      eq = 64'sd2097152 + mul_q21(eq, r);
      eq = 64'sd2097152 + mul_q21(eq, r);

      if (eq >= ONE) begin
        bin_exp = k;
        shift = 14;
      end else begin
        bin_exp = k - 1;
        shift = 13;
      end

      rounded = eq >>> shift;
      rem = eq - (rounded <<< shift);
      half_round = 64'sd1 <<< (shift - 1);
      if ((rem > half_round) || ((rem == half_round) && rounded[0]))
        rounded = rounded + 1;
      if (rounded >= 256) begin
        rounded = 128;
        bin_exp = bin_exp + 1;
      end

      out_exp = bin_exp + 127;
      sig = rounded[7:0];
      if (out_exp <= 0)
        y = 16'h0000;
      else if (out_exp >= 255)
        y = 16'h7f80;
      else
        y = {{out_exp[7:0], sig[6:0]}};
    end
  end
endmodule
""")


def emit_bf16_pow2(detail: str) -> str:
    return _compact_bf16_fixed_point(f"""// {detail}
// structural fixed-point 2^x: integer/fraction range reduction and exp(r*ln(2))
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE  = 64'sd2097152;
  localparam signed [63:0] LN2  = 64'sd1453635;
  localparam signed [63:0] HALF = 64'sd1048576;

  reg signed [63:0] xq, rq, r, eq, rounded, rem, half_round;
  reg signed [63:0] k, bin_exp, out_exp;
  reg [7:0] sig;
  integer shift;

  function signed [63:0] mul_q21;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q21 = product / 128'sd2097152;
    end
  endfunction

  always @(*) begin
    y = 16'h3f80;
    xq = 0; rq = 0; r = 0; eq = 0; rounded = 0; rem = 0;
    half_round = 0; k = 0; bin_exp = 0; out_exp = 0;
    sig = 0; shift = 0;

    if (x[14:7] == 8'hff) begin
      if (x[6:0] != 0)
        y = 16'h7fc0;
      else if (x[15])
        y = 16'h0000;
      else
        y = 16'h7f80;
    end else if (x[14:7] == 0 || x[14:7] < 8'd118) begin
      y = 16'h3f80;
    end else if (x[14:7] >= 8'd134) begin
      y = x[15] ? 16'h0000 : 16'h7f80;
    end else begin
      xq = (64'sd128 + $signed({{1'b0, x[6:0]}})) <<< (x[14:7] - 8'd113);
      if (x[15])
        xq = -xq;

      if (xq >= 0)
        k = (xq + HALF) / ONE;
      else
        k = (xq - HALF) / ONE;
      rq = xq - k * ONE;
      r = mul_q21(rq, LN2);

      eq = 64'sd2913;
      eq = 64'sd17476   + mul_q21(eq, r);
      eq = 64'sd87381   + mul_q21(eq, r);
      eq = 64'sd349525  + mul_q21(eq, r);
      eq = 64'sd1048576 + mul_q21(eq, r);
      eq = 64'sd2097152 + mul_q21(eq, r);
      eq = 64'sd2097152 + mul_q21(eq, r);

      if (eq >= ONE) begin
        bin_exp = k;
        shift = 14;
      end else begin
        bin_exp = k - 1;
        shift = 13;
      end

      rounded = eq >>> shift;
      rem = eq - (rounded <<< shift);
      half_round = 64'sd1 <<< (shift - 1);
      if ((rem > half_round) || ((rem == half_round) && rounded[0]))
        rounded = rounded + 1;
      if (rounded >= 256) begin
        rounded = 128;
        bin_exp = bin_exp + 1;
      end

      out_exp = bin_exp + 127;
      sig = rounded[7:0];
      if (out_exp <= 0)
        y = 16'h0000;
      else if (out_exp >= 255)
        y = 16'h7f80;
      else
        y = {{out_exp[7:0], sig[6:0]}};
    end
  end
endmodule
""")


def emit_bf16_pow10(detail: str) -> str:
    return _compact_bf16_fixed_point(f"""// {detail}
// structural fixed-point 10^x: Q40 x*ln(10), ln(2) reduction, degree-5 exp
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE  = 64'sd1099511627776;
  localparam signed [63:0] LN2  = 64'sd762123384786;
  localparam signed [63:0] HALF = 64'sd381061692393;
  localparam signed [63:0] LN10 = 64'sd2531719083691;

  reg signed [63:0] xq, z, r, eq, normq, rounded32, rounded, rem;
  reg signed [63:0] k, bin_exp, out_exp;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  always @(*) begin
    y = 16'h3f80;
    xq = 0; z = 0; r = 0; eq = 0; normq = 0;
    rounded32 = 0; rounded = 0; rem = 0;
    k = 0; bin_exp = 0; out_exp = 0;

    if (x[14:7] == 8'hff) begin
      if (x[6:0] != 0)
        y = 16'h7fc0;
      else if (x[15])
        y = 16'h0000;
      else
        y = 16'h7f80;
    end else if (x[14:7] == 0 || x[14:7] < 8'd116) begin
      y = 16'h3f80;
    end else if (x[14:7] >= 8'd133) begin
      y = x[15] ? 16'h0000 : 16'h7f80;
    end else begin
      xq = (64'sd128 + $signed({{1'b0, x[6:0]}}))
            <<< ({{1'b0, x[14:7]}} - 9'd94);
      if (x[15])
        xq = -xq;
      z = mul_q40(xq, LN10);

      if (z >= 0)
        k = (z + HALF) / LN2;
      else
        k = (z - HALF) / LN2;
      r = z - k * LN2;

      eq = 64'sd9162596898;
      eq = 64'sd45812984491   + mul_q40(eq, r);
      eq = 64'sd183251937963  + mul_q40(eq, r);
      eq = 64'sd549755813888  + mul_q40(eq, r);
      eq = 64'sd1099511627776 + mul_q40(eq, r);
      eq = 64'sd1099511627776 + mul_q40(eq, r);

      if (eq >= ONE) begin
        normq = eq;
        bin_exp = k;
      end else begin
        normq = eq <<< 1;
        bin_exp = k - 1;
      end

      rounded32 = normq >>> 17;
      rem = normq - (rounded32 <<< 17);
      if ((rem > 64'sd65536) ||
          ((rem == 64'sd65536) && rounded32[0]))
        rounded32 = rounded32 + 1;
      if (rounded32 >= 16777216) begin
        rounded32 = 8388608;
        bin_exp = bin_exp + 1;
      end

      out_exp = bin_exp + 127;
      if (out_exp < 0)
        y = 16'h0000;
      else if (out_exp == 0) begin
        rounded = rounded32 >>> 17;
        rem = rounded32 - (rounded <<< 17);
        if ((rem > 64'sd65536) ||
            ((rem == 64'sd65536) && rounded[0]))
          rounded = rounded + 1;
        y = (rounded >= 128) ? 16'h0080 : 16'h0000;
      end else begin
        rounded = rounded32 >>> 16;
        rem = rounded32 - (rounded <<< 16);
        if ((rem > 64'sd32768) ||
            ((rem == 64'sd32768) && rounded[0]))
          rounded = rounded + 1;
        if (rounded >= 256) begin
          rounded = 128;
          out_exp = out_exp + 1;
        end
        if (out_exp >= 255)
          y = 16'h7f80;
        else
          y = {{out_exp[7:0], rounded[6:0]}};
      end
    end
  end
endmodule
""")


def emit_bf16_log(detail: str) -> str:
    return _compact_bf16_fixed_point(f"""// {detail}
// structural ln: exponent decomposition and Q40 atanh series through z^5
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE = 64'sd1099511627776;
  localparam signed [63:0] LN2 = 64'sd762123384786;

  reg signed [63:0] m, z, z2, p, logm, valueq, absq, normq;
  reg signed [63:0] e, bin_exp, out_exp, rounded32, rounded, rem;
  integer i;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  function signed [63:0] div_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] numerator;
    begin
      numerator = a * 64'sd1099511627776;
      div_q40 = numerator / b;
    end
  endfunction

  always @(*) begin
    y = 16'h0000;
    m = 0; z = 0; z2 = 0; p = 0; logm = 0; valueq = 0;
    absq = 0; normq = 0; e = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; rem = 0;

    if (x[14:7] == 8'hff) begin
      if (x[6:0] != 0)
        y = 16'h7fc0;
      else if (x[15])
        y = 16'h7fc0;
      else
        y = 16'h7f80;
    end else if (x[14:7] == 0) begin
      y = 16'hff80;
    end else if (x[15]) begin
      y = 16'h7fc0;
    end else begin
      m = (64'sd128 + $signed({{1'b0, x[6:0]}})) <<< 33;
      e = $signed({{1'b0, x[14:7]}}) - 64'sd127;
      if ({{1'b1, x[6:0]}} >= 8'd182) begin
        m = m >>> 1;
        e = e + 1;
      end

      z = div_q40(m - ONE, m + ONE);
      z2 = mul_q40(z, z);
      p = 64'sd219902325555;
      p = 64'sd366503875925 + mul_q40(z2, p);
      logm = mul_q40(z, ONE + mul_q40(z2, p)) <<< 1;
      valueq = e * LN2 + logm;

      if (valueq == 0) begin
        y = 16'h0000;
      end else begin
        absq = valueq[63] ? -valueq : valueq;
        normq = absq;
        bin_exp = 0;
        repeat (7)
          if (normq >= 64'sd2199023255552) begin
            normq = normq >>> 1;
            bin_exp = bin_exp + 1;
          end
        repeat (40)
          if (normq < ONE) begin
            normq = normq <<< 1;
            bin_exp = bin_exp - 1;
          end

        rounded32 = normq >>> 17;
        rem = normq - (rounded32 <<< 17);
        if ((rem > 64'sd65536) ||
            ((rem == 64'sd65536) && rounded32[0]))
          rounded32 = rounded32 + 1;
        if (rounded32 >= 16777216) begin
          rounded32 = 8388608;
          bin_exp = bin_exp + 1;
        end

        rounded = rounded32 >>> 16;
        rem = rounded32 - (rounded <<< 16);
        if ((rem > 64'sd32768) ||
            ((rem == 64'sd32768) && rounded[0]))
          rounded = rounded + 1;
        if (rounded >= 256) begin
          rounded = 128;
          bin_exp = bin_exp + 1;
        end
        out_exp = bin_exp + 127;
        y = {{valueq[63], out_exp[7:0], rounded[6:0]}};
      end
    end
  end
endmodule
""")


def emit_bf16_log2(detail: str) -> str:
    return _compact_bf16_fixed_point(f"""// {detail}
// structural log2: exponent decomposition and centered Q40 atanh series through z^5
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE = 64'sd1099511627776;
  localparam signed [63:0] INV_LN2 = 64'sd1586259972792;

  reg signed [63:0] m, z, z2, p, logm, valueq, absq, normq;
  reg signed [63:0] e, bin_exp, out_exp, rounded32, rounded, rem;
  integer i;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  function signed [63:0] div_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] numerator;
    begin
      numerator = a * 64'sd1099511627776;
      div_q40 = numerator / b;
    end
  endfunction

  always @(*) begin
    y = 16'h0000;
    m = 0; z = 0; z2 = 0; p = 0; logm = 0; valueq = 0;
    absq = 0; normq = 0; e = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; rem = 0;

    if (x[14:7] == 8'hff) begin
      if (x[6:0] != 0)
        y = 16'h7fc0;
      else if (x[15])
        y = 16'h7fc0;
      else
        y = 16'h7f80;
    end else if (x[14:7] == 0) begin
      y = 16'hff80;
    end else if (x[15]) begin
      y = 16'h7fc0;
    end else begin
      m = (64'sd128 + $signed({{1'b0, x[6:0]}})) <<< 33;
      e = $signed({{1'b0, x[14:7]}}) - 64'sd127;
      if ({{1'b1, x[6:0]}} >= 8'd182) begin
        m = m >>> 1;
        e = e + 1;
      end

      z = div_q40(m - ONE, m + ONE);
      z2 = mul_q40(z, z);
      p = 64'sd219902325555;
      p = 64'sd366503875925 + mul_q40(z2, p);
      logm = mul_q40(z, ONE + mul_q40(z2, p)) <<< 1;
      valueq = e * ONE + mul_q40(logm, INV_LN2);

      if (valueq == 0) begin
        y = 16'h0000;
      end else begin
        absq = valueq[63] ? -valueq : valueq;
        normq = absq;
        bin_exp = 0;
        repeat (7)
          if (normq >= 64'sd2199023255552) begin
            normq = normq >>> 1;
            bin_exp = bin_exp + 1;
          end
        repeat (40)
          if (normq < ONE) begin
            normq = normq <<< 1;
            bin_exp = bin_exp - 1;
          end

        rounded32 = normq >>> 17;
        rem = normq - (rounded32 <<< 17);
        if ((rem > 64'sd65536) ||
            ((rem == 64'sd65536) && rounded32[0]))
          rounded32 = rounded32 + 1;
        if (rounded32 >= 16777216) begin
          rounded32 = 8388608;
          bin_exp = bin_exp + 1;
        end

        rounded = rounded32 >>> 16;
        rem = rounded32 - (rounded <<< 16);
        if ((rem > 64'sd32768) ||
            ((rem == 64'sd32768) && rounded[0]))
          rounded = rounded + 1;
        if (rounded >= 256) begin
          rounded = 128;
          bin_exp = bin_exp + 1;
        end
        out_exp = bin_exp + 127;
        y = {{valueq[63], out_exp[7:0], rounded[6:0]}};
      end
    end
  end
endmodule
""")


def emit_bf16_log10(detail: str) -> str:
    return _compact_bf16_fixed_point(f"""// {detail}
// structural log10: exponent decomposition and centered Q40 atanh series through z^5
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE = 64'sd1099511627776;
  localparam signed [63:0] LOG10_2 = 64'sd330985980542;
  localparam signed [63:0] INV_LN10 = 64'sd477511832732;

  reg signed [63:0] m, z, z2, p, logm, valueq, absq, normq;
  reg signed [63:0] e, bin_exp, out_exp, rounded32, rounded, rem;
  integer i;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  function signed [63:0] div_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] numerator;
    begin
      numerator = a * 64'sd1099511627776;
      div_q40 = numerator / b;
    end
  endfunction

  always @(*) begin
    y = 16'h0000;
    m = 0; z = 0; z2 = 0; p = 0; logm = 0; valueq = 0;
    absq = 0; normq = 0; e = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; rem = 0;

    if (x[14:7] == 8'hff) begin
      if (x[6:0] != 0)
        y = 16'h7fc0;
      else if (x[15])
        y = 16'h7fc0;
      else
        y = 16'h7f80;
    end else if (x[14:7] == 0) begin
      y = 16'hff80;
    end else if (x[15]) begin
      y = 16'h7fc0;
    end else begin
      m = (64'sd128 + $signed({{1'b0, x[6:0]}})) <<< 33;
      e = $signed({{1'b0, x[14:7]}}) - 64'sd127;
      if ({{1'b1, x[6:0]}} >= 8'd182) begin
        m = m >>> 1;
        e = e + 1;
      end

      z = div_q40(m - ONE, m + ONE);
      z2 = mul_q40(z, z);
      p = 64'sd219902325555;
      p = 64'sd366503875925 + mul_q40(z2, p);
      logm = mul_q40(z, ONE + mul_q40(z2, p)) <<< 1;
      valueq = e * LOG10_2 + mul_q40(logm, INV_LN10);

      if (valueq == 0) begin
        y = 16'h0000;
      end else begin
        absq = valueq[63] ? -valueq : valueq;
        normq = absq;
        bin_exp = 0;
        repeat (7)
          if (normq >= 64'sd2199023255552) begin
            normq = normq >>> 1;
            bin_exp = bin_exp + 1;
          end
        repeat (40)
          if (normq < ONE) begin
            normq = normq <<< 1;
            bin_exp = bin_exp - 1;
          end

        rounded32 = normq >>> 17;
        rem = normq - (rounded32 <<< 17);
        if ((rem > 64'sd65536) ||
            ((rem == 64'sd65536) && rounded32[0]))
          rounded32 = rounded32 + 1;
        if (rounded32 >= 16777216) begin
          rounded32 = 8388608;
          bin_exp = bin_exp + 1;
        end

        rounded = rounded32 >>> 16;
        rem = rounded32 - (rounded <<< 16);
        if ((rem > 64'sd32768) ||
            ((rem == 64'sd32768) && rounded[0]))
          rounded = rounded + 1;
        if (rounded >= 256) begin
          rounded = 128;
          bin_exp = bin_exp + 1;
        end
        out_exp = bin_exp + 127;
        y = {{valueq[63], out_exp[7:0], rounded[6:0]}};
      end
    end
  end
endmodule
""")


def emit_bf16_sin(detail: str) -> str:
    return _compact_bf16_fixed_point(f"""// {detail}
// 256-bit Payne-Hanek reduction; Q56 degree-9 sine and degree-10 cosine
module top(input [15:0] x, output reg [15:0] y);
  localparam [255:0] TWO_OVER_PI =
    256'ha2f9836e4e441529fc2757d1f534ddc0db6295993c439041fe5163abdebbc561;
  localparam signed [63:0] ONE = 64'sd72057594037927936;
  localparam signed [63:0] PI_OVER_2 = 64'sd113187804032455044;

  reg [263:0] prod, ipart, remainder, halfv, frac_wide;
  reg [1:0] quadrant;
  reg round_up;
  reg signed [63:0] fracq, r, t, sp, cp, sinv, cosv, valueq;
  reg signed [63:0] absq, normq, bin_exp, out_exp;
  reg signed [63:0] rounded32, rounded, rem;
  integer shift_amt;
  integer i;

  function signed [63:0] mul_q56;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product128;
    begin
      product128 = a * b;
      mul_q56 = product128 / 128'sd72057594037927936;
    end
  endfunction

  always @(*) begin
    y = 16'h0000;
    prod = 0; ipart = 0; remainder = 0; halfv = 0; frac_wide = 0;
    quadrant = 0; round_up = 0; fracq = 0; r = 0; t = 0;
    sp = 0; cp = 0; sinv = 0; cosv = 0; valueq = 0;
    absq = 0; normq = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; rem = 0; shift_amt = 0;

    if (x[14:7] == 8'hff) begin
      y = 16'h7fc0;
    end else if (x[14:7] == 0) begin
      y = {{x[15], 15'd0}};
    end else if (x[14:7] <= 8'd122) begin
      y = x;
    end else begin
      prod = {{{{256{{1'b0}}}}, 1'b1, x[6:0]}} * {{8'd0, TWO_OVER_PI}};
      shift_amt = 390 - x[14:7];
      ipart = prod >> shift_amt;
      remainder = prod - (ipart << shift_amt);
      if (shift_amt <= 264) begin
        halfv = 264'd1 << (shift_amt - 1);
        round_up = (remainder > halfv) ||
                   ((remainder == halfv) && ipart[0]);
      end
      quadrant = ipart[1:0] + round_up;
      frac_wide = remainder >> (shift_amt - 56);
      if (round_up)
        fracq = $signed(frac_wide[63:0]) - ONE;
      else
        fracq = $signed(frac_wide[63:0]);
      r = mul_q56(fracq, PI_OVER_2);
      t = mul_q56(r, r);

      sp = 64'sd198571412142;
      sp = -64'sd14297141674192 + mul_q56(t, sp);
      sp = 64'sd600479950316066 + mul_q56(t, sp);
      sp = -64'sd12009599006321323 + mul_q56(t, sp);
      sinv = mul_q56(r, ONE + mul_q56(t, sp));

      cp = -64'sd19857141214;
      cp = 64'sd1787142709274 + mul_q56(t, cp);
      cp = -64'sd100079991719344 + mul_q56(t, cp);
      cp = 64'sd3002399751580331 + mul_q56(t, cp);
      cp = -64'sd36028797018963968 + mul_q56(t, cp);
      cosv = ONE + mul_q56(t, cp);

      if (quadrant == 0)
        valueq = sinv;
      else if (quadrant == 1)
        valueq = cosv;
      else if (quadrant == 2)
        valueq = -sinv;
      else
        valueq = -cosv;
      if (x[15])
        valueq = -valueq;

      if (valueq == 0) begin
        y = {{x[15], 15'd0}};
      end else begin
        absq = valueq[63] ? -valueq : valueq;
        normq = absq;
        bin_exp = 0;
        for (i = 0; i < 60; i = i + 1)
          if (normq < ONE) begin
            normq = normq <<< 1;
            bin_exp = bin_exp - 1;
          end

        rounded32 = normq >>> 33;
        rem = normq - (rounded32 <<< 33);
        if ((rem > 64'sd4294967296) ||
            ((rem == 64'sd4294967296) && rounded32[0]))
          rounded32 = rounded32 + 1;
        if (rounded32 >= 16777216) begin
          rounded32 = 8388608;
          bin_exp = bin_exp + 1;
        end

        rounded = rounded32 >>> 16;
        rem = rounded32 - (rounded <<< 16);
        if ((rem > 64'sd32768) ||
            ((rem == 64'sd32768) && rounded[0]))
          rounded = rounded + 1;
        if (rounded >= 256) begin
          rounded = 128;
          bin_exp = bin_exp + 1;
        end
        out_exp = bin_exp + 127;
        y = {{valueq[63], out_exp[7:0], rounded[6:0]}};
      end
    end
  end
endmodule
""", body_start="      r = mul_q56(fracq, PI_OVER_2);")


def emit_bf16_tan(detail: str) -> str:
    return f"""// {detail}
// Payne-Hanek reduction, Q56 degree-7/8 kernels, normalized tan/cot ratio
module top(input [15:0] x, output reg [15:0] y);
  localparam [255:0] TWO_OVER_PI =
    256'ha2f9836e4e441529fc2757d1f534ddc0db6295993c439041fe5163abdebbc561;
  localparam signed [63:0] ONE = 64'sd72057594037927936;
  localparam signed [63:0] PI_OVER_2 = 64'sd113187804032455044;

  reg [263:0] prod, ipart, remainder, halfv, frac_wide;
  reg [1:0] quadrant;
  reg round_up, result_sign;
  reg signed [63:0] fracq, r, t, sp, cp, sinv, cosv;
  reg signed [63:0] num, den, norm_num, norm_den, normq;
  reg signed [63:0] bin_exp, out_exp, rounded32, rounded, rem;
  integer shift_amt;
  integer i;

  function signed [63:0] mul_q56;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product128;
    begin
      product128 = a * b;
      mul_q56 = product128 / 128'sd72057594037927936;
    end
  endfunction

  function signed [63:0] div_q56;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] numerator128;
    begin
      numerator128 = a * 64'sd72057594037927936;
      div_q56 = numerator128 / b;
    end
  endfunction

  always @(*) begin
    y = 16'h0000;
    prod = 0; ipart = 0; remainder = 0; halfv = 0; frac_wide = 0;
    quadrant = 0; round_up = 0; result_sign = 0;
    fracq = 0; r = 0; t = 0; sp = 0; cp = 0; sinv = 0; cosv = 0;
    num = 0; den = 0; norm_num = 0; norm_den = 0; normq = 0;
    bin_exp = 0; out_exp = 0; rounded32 = 0; rounded = 0; rem = 0;
    shift_amt = 0;

    if (x[14:7] == 8'hff) begin
      y = 16'h7fc0;
    end else if (x[14:7] == 0) begin
      y = {{x[15], 15'd0}};
    end else if (x[14:7] <= 8'd122) begin
      y = x;
    end else begin
      prod = {{{{256{{1'b0}}}}, 1'b1, x[6:0]}} * {{8'd0, TWO_OVER_PI}};
      shift_amt = 390 - x[14:7];
      ipart = prod >> shift_amt;
      remainder = prod - (ipart << shift_amt);
      if (shift_amt <= 264) begin
        halfv = 264'd1 << (shift_amt - 1);
        round_up = (remainder > halfv) ||
                   ((remainder == halfv) && ipart[0]);
      end
      quadrant = ipart[1:0] + round_up;
      frac_wide = remainder >> (shift_amt - 56);
      if (round_up)
        fracq = $signed(frac_wide[63:0]) - ONE;
      else
        fracq = $signed(frac_wide[63:0]);
      r = mul_q56(fracq, PI_OVER_2);
      t = mul_q56(r, r);

      sp = -64'sd14297141674192;
      sp = 64'sd600479950316066 + mul_q56(t, sp);
      sp = -64'sd12009599006321323 + mul_q56(t, sp);
      sinv = mul_q56(r, ONE + mul_q56(t, sp));

      cp = 64'sd1787142709274;
      cp = -64'sd100079991719344 + mul_q56(t, cp);
      cp = 64'sd3002399751580331 + mul_q56(t, cp);
      cp = -64'sd36028797018963968 + mul_q56(t, cp);
      cosv = ONE + mul_q56(t, cp);

      if (!quadrant[0]) begin
        num = sinv[63] ? -sinv : sinv;
        den = cosv;
        result_sign = sinv[63] ^ x[15];
      end else begin
        num = cosv;
        den = sinv[63] ? -sinv : sinv;
        result_sign = !sinv[63] ^ x[15];
      end

      if (num == 0) begin
        y = {{result_sign, 15'd0}};
      end else begin
        norm_num = num;
        norm_den = den;
        bin_exp = 0;
        if (num >= den) begin
          for (i = 0; i < 60; i = i + 1)
            if (norm_num >= (norm_den <<< 1)) begin
              norm_den = norm_den <<< 1;
              bin_exp = bin_exp + 1;
            end
        end else begin
          for (i = 0; i < 60; i = i + 1)
            if (norm_num < norm_den) begin
              norm_num = norm_num <<< 1;
              bin_exp = bin_exp - 1;
            end
        end
        normq = div_q56(norm_num, norm_den);

        rounded32 = normq >>> 33;
        rem = normq - (rounded32 <<< 33);
        if ((rem > 64'sd4294967296) ||
            ((rem == 64'sd4294967296) && rounded32[0]))
          rounded32 = rounded32 + 1;
        if (rounded32 >= 16777216) begin
          rounded32 = 8388608;
          bin_exp = bin_exp + 1;
        end

        rounded = rounded32 >>> 16;
        rem = rounded32 - (rounded <<< 16);
        if ((rem > 64'sd32768) ||
            ((rem == 64'sd32768) && rounded[0]))
          rounded = rounded + 1;
        if (rounded >= 256) begin
          rounded = 128;
          bin_exp = bin_exp + 1;
        end
        out_exp = bin_exp + 127;
        y = {{result_sign, out_exp[7:0], rounded[6:0]}};
      end
    end
  end
endmodule
"""


def emit_bf16_sinh(detail: str) -> str:
    return _compact_bf16_fixed_point(f"""// {detail}
// Q40 exponential range reduction with reciprocal sinh correction
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE  = 64'sd1099511627776;
  localparam signed [63:0] LN2  = 64'sd762123384786;
  localparam signed [63:0] HALF = 64'sd381061692393;

  reg signed [63:0] aq, r, eq, inv_eq, corr, magq, normq;
  reg signed [63:0] k, bin_exp, out_exp, rounded32, rounded, rem;
  integer corr_shift;
  integer i;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  function signed [63:0] div_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] numerator;
    begin
      numerator = a * 64'sd1099511627776;
      div_q40 = numerator / b;
    end
  endfunction

  always @(*) begin
    y = 16'h0000;
    aq = 0; r = 0; eq = 0; inv_eq = 0; corr = 0;
    magq = 0; normq = 0; k = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; rem = 0; corr_shift = 0;

    if (x[14:7] == 8'hff) begin
      if (x[6:0] != 0)
        y = 16'h7fc0;
      else
        y = {{x[15], 15'h7f80}};
    end else if (x[14:7] == 0) begin
      y = {{x[15], 15'd0}};
    end else if (x[14:7] <= 8'd122) begin
      y = x;
    end else if (x[14:7] >= 8'd134) begin
      y = {{x[15], 15'h7f80}};
    end else begin
      aq = (64'sd128 + $signed({{1'b0, x[6:0]}}))
            <<< ({{1'b0, x[14:7]}} - 9'd94);
      k = (aq + HALF) / LN2;
      r = aq - k * LN2;

      eq = 64'sd9162596898;
      eq = 64'sd45812984491   + mul_q40(eq, r);
      eq = 64'sd183251937963  + mul_q40(eq, r);
      eq = 64'sd549755813888  + mul_q40(eq, r);
      eq = 64'sd1099511627776 + mul_q40(eq, r);
      eq = 64'sd1099511627776 + mul_q40(eq, r);

      inv_eq = div_q40(ONE, eq);
      corr = mul_q40(inv_eq, inv_eq);
      corr_shift = k * 2;
      if (corr_shift >= 63)
        corr = 0;
      else
        corr = corr >>> corr_shift;
      magq = mul_q40(eq, ONE - corr);
      normq = magq;
      bin_exp = k - 1;
      for (i = 0; i < 40; i = i + 1)
        if (normq < ONE) begin
          normq = normq <<< 1;
          bin_exp = bin_exp - 1;
        end

      rounded32 = normq >>> 17;
      rem = normq - (rounded32 <<< 17);
      if ((rem > 64'sd65536) ||
          ((rem == 64'sd65536) && rounded32[0]))
        rounded32 = rounded32 + 1;
      if (rounded32 >= 16777216) begin
        rounded32 = 8388608;
        bin_exp = bin_exp + 1;
      end

      rounded = rounded32 >>> 16;
      rem = rounded32 - (rounded <<< 16);
      if ((rem > 64'sd32768) ||
          ((rem == 64'sd32768) && rounded[0]))
        rounded = rounded + 1;
      if (rounded >= 256) begin
        rounded = 128;
        bin_exp = bin_exp + 1;
      end
      out_exp = bin_exp + 127;
      if (out_exp >= 255)
        y = {{x[15], 15'h7f80}};
      else
        y = {{x[15], out_exp[7:0], rounded[6:0]}};
    end
  end
endmodule
""")


def emit_bf16_tanh(detail: str) -> str:
    return _compact_bf16_fixed_point(f"""// {detail}
// Q40 range-reduced exponential and odd rational reconstruction
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE  = 64'sd1099511627776;
  localparam signed [63:0] LN2  = 64'sd762123384786;
  localparam signed [63:0] HALF = 64'sd381061692393;

  reg signed [63:0] aq, tq, r, eq, zq, magq, normq;
  reg signed [63:0] k, bin_exp, out_exp, rounded32, rounded, rem;
  integer i;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  function signed [63:0] div_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] numerator;
    begin
      numerator = a * 64'sd1099511627776;
      div_q40 = numerator / b;
    end
  endfunction

  always @(*) begin
    y = 16'h0000;
    aq = 0; tq = 0; r = 0; eq = 0; zq = 0;
    magq = 0; normq = 0; k = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; rem = 0;

    if (x[14:7] == 8'hff) begin
      if (x[6:0] != 0)
        y = 16'h7fc0;
      else
        y = {{x[15], 15'h3f80}};
    end else if (x[14:7] == 0) begin
      y = {{x[15], 15'd0}};
    end else if (x[14:0] <= 15'h3db8) begin
      y = x;
    end else if (x[14:0] >= 15'h405e) begin
      y = {{x[15], 15'h3f80}};
    end else begin
      aq = (64'sd128 + $signed({{1'b0, x[6:0]}}))
            <<< ({{1'b0, x[14:7]}} - 9'd94);
      tq = aq <<< 1;
      k = (tq + HALF) / LN2;
      r = tq - k * LN2;

      eq = 64'sd9162596898;
      eq = 64'sd45812984491   + mul_q40(eq, r);
      eq = 64'sd183251937963  + mul_q40(eq, r);
      eq = 64'sd549755813888  + mul_q40(eq, r);
      eq = 64'sd1099511627776 + mul_q40(eq, r);
      eq = 64'sd1099511627776 + mul_q40(eq, r);

      zq = div_q40(ONE, eq) >>> k;
      magq = div_q40(ONE - zq, ONE + zq);
      normq = magq;
      bin_exp = 0;
      for (i = 0; i < 40; i = i + 1)
        if (normq < ONE) begin
          normq = normq <<< 1;
          bin_exp = bin_exp - 1;
        end

      rounded32 = normq >>> 17;
      rem = normq - (rounded32 <<< 17);
      if ((rem > 64'sd65536) ||
          ((rem == 64'sd65536) && rounded32[0]))
        rounded32 = rounded32 + 1;
      if (rounded32 >= 16777216) begin
        rounded32 = 8388608;
        bin_exp = bin_exp + 1;
      end

      rounded = rounded32 >>> 16;
      rem = rounded32 - (rounded <<< 16);
      if ((rem > 64'sd32768) ||
          ((rem == 64'sd32768) && rounded[0]))
        rounded = rounded + 1;
      if (rounded >= 256) begin
        rounded = 128;
        bin_exp = bin_exp + 1;
      end
      out_exp = bin_exp + 127;
      y = {{x[15], out_exp[7:0], rounded[6:0]}};
    end
  end
endmodule
""")


def emit_bf16_sigmoid(detail: str) -> str:
    return _compact_bf16_fixed_point(f"""// {detail}
// Q40 range-reduced exponential with stable positive/negative rational branches
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE  = 64'sd1099511627776;
  localparam signed [63:0] LN2  = 64'sd762123384786;
  localparam signed [63:0] HALF = 64'sd381061692393;

  reg signed [63:0] aq, r, eq, inv_eq, zq, magq, normq;
  reg signed [63:0] k, bin_exp, out_exp, rounded32, rounded, rem;
  integer i;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  function signed [63:0] div_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] numerator;
    begin
      numerator = a * 64'sd1099511627776;
      div_q40 = numerator / b;
    end
  endfunction

  always @(*) begin
    y = 16'h0000;
    aq = 0; r = 0; eq = 0; inv_eq = 0; zq = 0;
    magq = 0; normq = 0; k = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; rem = 0;

    if ((x[14:7] == 8'hff) && (x[6:0] != 0)) begin
      y = 16'h7fc0;
    end else if (!x[15] && (x[14:0] >= 15'h40c8)) begin
      y = 16'h3f80;
    end else if (x[15] && (x[14:0] >= 15'h42af)) begin
      y = 16'h0000;
    end else if ((!x[15] && (x[14:0] <= 15'h3c00)) ||
                 ( x[15] && (x[14:0] <= 15'h3b80))) begin
      y = 16'h3f00;
    end else begin
      aq = (64'sd128 + $signed({{1'b0, x[6:0]}}))
            <<< ({{1'b0, x[14:7]}} - 9'd94);
      k = (aq + HALF) / LN2;
      r = aq - k * LN2;

      eq = 64'sd9162596898;
      eq = 64'sd45812984491   + mul_q40(eq, r);
      eq = 64'sd183251937963  + mul_q40(eq, r);
      eq = 64'sd549755813888  + mul_q40(eq, r);
      eq = 64'sd1099511627776 + mul_q40(eq, r);
      eq = 64'sd1099511627776 + mul_q40(eq, r);

      inv_eq = div_q40(ONE, eq);
      if (k >= 63)
        zq = 0;
      else
        zq = inv_eq >>> k;

      if (x[15]) begin
        magq = div_q40(inv_eq, ONE + zq);
        bin_exp = 0 - k;
      end else begin
        magq = div_q40(ONE, ONE + zq);
        bin_exp = 0;
      end

      normq = magq;
      for (i = 0; i < 4; i = i + 1)
        if (normq < ONE) begin
          normq = normq <<< 1;
          bin_exp = bin_exp - 1;
        end

      rounded32 = normq >>> 17;
      rem = normq - (rounded32 <<< 17);
      if ((rem > 64'sd65536) ||
          ((rem == 64'sd65536) && rounded32[0]))
        rounded32 = rounded32 + 1;
      if (rounded32 >= 16777216) begin
        rounded32 = 8388608;
        bin_exp = bin_exp + 1;
      end

      rounded = rounded32 >>> 16;
      rem = rounded32 - (rounded <<< 16);
      if ((rem > 64'sd32768) ||
          ((rem == 64'sd32768) && rounded[0]))
        rounded = rounded + 1;
      if (rounded >= 256) begin
        rounded = 128;
        bin_exp = bin_exp + 1;
      end

      out_exp = bin_exp + 127;
      if (out_exp <= 0)
        y = 16'h0000;
      else
        y = {{out_exp[7:0], rounded[6:0]}};
    end
  end
endmodule
""")


def emit_bf16_square(detail: str) -> str:
    return lowest_cost_source([emit_binary_square(8, 7, detail),
                               emit_guarded_binary_square(8, 7, detail)])


def emit_bf16_cube(detail: str) -> str:
    return emit_binary_cube(8, 7, detail)


def emit_bf16_cbrt(detail: str) -> str:
    return lowest_cost_source([emit_binary_root(8, 7, 3, False, detail, precision=None),
                               emit_staged_cubic_root(8, 7, detail, precision=None)])


def emit_bf16_recip_cube(detail: str) -> str:
    return emit_binary_recip_power(8, 7, 3, detail)


def emit_bf16_recip_cbrt(detail: str) -> str:
    return emit_inverse_cube_scan(8, 7, detail)


def emit_fp16_exp(detail: str) -> str:
    return f"""// {detail}
// structural fixed-point exp: Q40 ln(2) range reduction and degree-6 Horner polynomial
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE  = 64'sd1099511627776;
  localparam signed [63:0] LN2  = 64'sd762123384786;
  localparam signed [63:0] HALF = 64'sd381061692393;

  reg signed [63:0] xq, r, eq, normq, rounded32, rounded, rem;
  reg signed [63:0] k, bin_exp, out_exp;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  always @(*) begin
    y = 16'h3c00;
    xq = 0; r = 0; eq = 0; normq = 0;
    rounded32 = 0; rounded = 0; rem = 0;
    k = 0; bin_exp = 0; out_exp = 0;

    if (x[14:10] == 5'h1f) begin
      if (x[9:0] != 0)
        y = 16'h7e00;
      else if (x[15])
        y = 16'h0000;
      else
        y = 16'h7c00;
    end else if (x[14:10] == 0) begin
      y = 16'h3c00;
    end else if (x[14:10] >= 5'd19) begin
      y = x[15] ? 16'h0000 : 16'h7c00;
    end else begin
      xq = (64'sd1024 + $signed({{1'b0, x[9:0]}}))
            <<< ({{1'b0, x[14:10]}} + 6'd15);
      if (x[15])
        xq = -xq;

      if (xq >= 0)
        k = (xq + HALF) / LN2;
      else
        k = (xq - HALF) / LN2;
      r = xq - k * LN2;

      eq = 64'sd1527099483;
      eq = 64'sd9162596898    + mul_q40(eq, r);
      eq = 64'sd45812984491   + mul_q40(eq, r);
      eq = 64'sd183251937963  + mul_q40(eq, r);
      eq = 64'sd549755813888  + mul_q40(eq, r);
      eq = 64'sd1099511627776 + mul_q40(eq, r);
      eq = 64'sd1099511627776 + mul_q40(eq, r);

      if (eq >= ONE) begin
        normq = eq;
        bin_exp = k;
      end else begin
        normq = eq <<< 1;
        bin_exp = k - 1;
      end

      rounded32 = normq >>> 17;
      rem = normq - (rounded32 <<< 17);
      if ((rem > 64'sd65536) ||
          ((rem == 64'sd65536) && rounded32[0]))
        rounded32 = rounded32 + 1;
      if (rounded32 >= 16777216) begin
        rounded32 = 8388608;
        bin_exp = bin_exp + 1;
      end

      out_exp = bin_exp + 15;
      if (out_exp < 0)
        y = 16'h0000;
      else if (out_exp == 0) begin
        rounded = rounded32 >>> 14;
        rem = rounded32 - (rounded <<< 14);
        if ((rem > 64'sd8192) ||
            ((rem == 64'sd8192) && rounded[0]))
          rounded = rounded + 1;
        y = (rounded >= 1024) ? 16'h0400 : 16'h0000;
      end else begin
        rounded = rounded32 >>> 13;
        rem = rounded32 - (rounded <<< 13);
        if ((rem > 64'sd4096) ||
            ((rem == 64'sd4096) && rounded[0]))
          rounded = rounded + 1;
        if (rounded >= 2048) begin
          rounded = 1024;
          out_exp = out_exp + 1;
        end
        if (out_exp >= 31)
          y = 16'h7c00;
        else
          y = {{out_exp[4:0], rounded[9:0]}};
      end
    end
  end
endmodule
"""


def emit_fp16_pow2(detail: str) -> str:
    return f"""// {detail}
// structural fixed-point 2^x: integer/fraction reduction and Q40 exponential
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE  = 64'sd1099511627776;
  localparam signed [63:0] LN2  = 64'sd762123384786;
  localparam signed [63:0] HALF = 64'sd549755813888;

  reg signed [63:0] xq, rq, r, eq, normq, rounded32, rounded, rem;
  reg signed [63:0] k, bin_exp, out_exp;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  always @(*) begin
    y = 16'h3c00;
    xq = 0; rq = 0; r = 0; eq = 0; normq = 0;
    rounded32 = 0; rounded = 0; rem = 0;
    k = 0; bin_exp = 0; out_exp = 0;

    if (x[14:10] == 5'h1f) begin
      if (x[9:0] != 0)
        y = 16'h7e00;
      else if (x[15])
        y = 16'h0000;
      else
        y = 16'h7c00;
    end else if (x[14:10] == 0) begin
      y = 16'h3c00;
    end else if (x[14:10] >= 5'd20) begin
      y = x[15] ? 16'h0000 : 16'h7c00;
    end else begin
      xq = (64'sd1024 + $signed({{1'b0, x[9:0]}}))
            <<< ({{1'b0, x[14:10]}} + 6'd15);
      if (x[15])
        xq = -xq;

      if (xq >= 0)
        k = (xq + HALF) / ONE;
      else
        k = (xq - HALF) / ONE;
      rq = xq - k * ONE;
      r = mul_q40(rq, LN2);

      eq = 64'sd1527099483;
      eq = 64'sd9162596898    + mul_q40(eq, r);
      eq = 64'sd45812984491   + mul_q40(eq, r);
      eq = 64'sd183251937963  + mul_q40(eq, r);
      eq = 64'sd549755813888  + mul_q40(eq, r);
      eq = 64'sd1099511627776 + mul_q40(eq, r);
      eq = 64'sd1099511627776 + mul_q40(eq, r);

      if (eq >= ONE) begin
        normq = eq;
        bin_exp = k;
      end else begin
        normq = eq <<< 1;
        bin_exp = k - 1;
      end

      rounded32 = normq >>> 17;
      rem = normq - (rounded32 <<< 17);
      if ((rem > 64'sd65536) ||
          ((rem == 64'sd65536) && rounded32[0]))
        rounded32 = rounded32 + 1;
      if (rounded32 >= 16777216) begin
        rounded32 = 8388608;
        bin_exp = bin_exp + 1;
      end

      out_exp = bin_exp + 15;
      if (out_exp < 0)
        y = 16'h0000;
      else if (out_exp == 0) begin
        rounded = rounded32 >>> 14;
        rem = rounded32 - (rounded <<< 14);
        if ((rem > 64'sd8192) ||
            ((rem == 64'sd8192) && rounded[0]))
          rounded = rounded + 1;
        y = (rounded >= 1024) ? 16'h0400 : 16'h0000;
      end else begin
        rounded = rounded32 >>> 13;
        rem = rounded32 - (rounded <<< 13);
        if ((rem > 64'sd4096) ||
            ((rem == 64'sd4096) && rounded[0]))
          rounded = rounded + 1;
        if (rounded >= 2048) begin
          rounded = 1024;
          out_exp = out_exp + 1;
        end
        if (out_exp >= 31)
          y = 16'h7c00;
        else
          y = {{out_exp[4:0], rounded[9:0]}};
      end
    end
  end
endmodule
"""


def emit_fp16_pow10(detail: str) -> str:
    return f"""// {detail}
// structural fixed-point 10^x: Q40 x*ln(10), ln(2) reduction, degree-5 exp
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE  = 64'sd1099511627776;
  localparam signed [63:0] LN2  = 64'sd762123384786;
  localparam signed [63:0] HALF = 64'sd381061692393;
  localparam signed [63:0] LN10 = 64'sd2531719083691;

  reg signed [63:0] xq, z, r, eq, normq, rounded32, rounded, rem;
  reg signed [63:0] k, bin_exp, out_exp;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  always @(*) begin
    y = 16'h3c00;
    xq = 0; z = 0; r = 0; eq = 0; normq = 0;
    rounded32 = 0; rounded = 0; rem = 0;
    k = 0; bin_exp = 0; out_exp = 0;

    if (x[14:10] == 5'h1f) begin
      if (x[9:0] != 0)
        y = 16'h7e00;
      else if (x[15])
        y = 16'h0000;
      else
        y = 16'h7c00;
    end else if (x[14:10] == 0) begin
      y = 16'h3c00;
    end else begin
      xq = (64'sd1024 + $signed({{1'b0, x[9:0]}}))
            <<< ({{1'b0, x[14:10]}} + 6'd15);
      if (x[15])
        xq = -xq;
      z = mul_q40(xq, LN10);

      if (z >= 0)
        k = (z + HALF) / LN2;
      else
        k = (z - HALF) / LN2;
      r = z - k * LN2;

      eq = 64'sd1527099483;
      eq = 64'sd9162596898    + mul_q40(eq, r);
      eq = 64'sd45812984491   + mul_q40(eq, r);
      eq = 64'sd183251937963  + mul_q40(eq, r);
      eq = 64'sd549755813888  + mul_q40(eq, r);
      eq = 64'sd1099511627776 + mul_q40(eq, r);
      eq = 64'sd1099511627776 + mul_q40(eq, r);

      if (eq >= ONE) begin
        normq = eq;
        bin_exp = k;
      end else begin
        normq = eq <<< 1;
        bin_exp = k - 1;
      end

      rounded32 = normq >>> 17;
      rem = normq - (rounded32 <<< 17);
      if ((rem > 64'sd65536) ||
          ((rem == 64'sd65536) && rounded32[0]))
        rounded32 = rounded32 + 1;
      if (rounded32 >= 16777216) begin
        rounded32 = 8388608;
        bin_exp = bin_exp + 1;
      end

      out_exp = bin_exp + 15;
      if (out_exp < 0)
        y = 16'h0000;
      else if (out_exp == 0) begin
        rounded = rounded32 >>> 14;
        rem = rounded32 - (rounded <<< 14);
        if ((rem > 64'sd8192) ||
            ((rem == 64'sd8192) && rounded[0]))
          rounded = rounded + 1;
        y = (rounded >= 1024) ? 16'h0400 : 16'h0000;
      end else begin
        rounded = rounded32 >>> 13;
        rem = rounded32 - (rounded <<< 13);
        if ((rem > 64'sd4096) ||
            ((rem == 64'sd4096) && rounded[0]))
          rounded = rounded + 1;
        if (rounded >= 2048) begin
          rounded = 1024;
          out_exp = out_exp + 1;
        end
        if (out_exp >= 31)
          y = 16'h7c00;
        else
          y = {{out_exp[4:0], rounded[9:0]}};
      end
    end
  end
endmodule
"""


def emit_fp16_log(detail: str) -> str:
    return f"""// {detail}
// structural ln: exponent decomposition and Q40 centered atanh polynomial
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE = 64'sd1099511627776;
  localparam signed [63:0] LN2 = 64'sd762123384786;

  reg signed [63:0] m, z, z2, p, logm, valueq, absq, normq;
  reg signed [63:0] e, bin_exp, out_exp, rounded32, rounded, rem;
  integer i;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  function signed [63:0] div_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] numerator;
    begin
      numerator = a * 64'sd1099511627776;
      div_q40 = numerator / b;
    end
  endfunction

  always @(*) begin
    y = 16'h0000;
    m = 0; z = 0; z2 = 0; p = 0; logm = 0; valueq = 0;
    absq = 0; normq = 0; e = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; rem = 0;

    if (x[14:10] == 5'h1f) begin
      if (x[9:0] != 0)
        y = 16'h7e00;
      else if (x[15])
        y = 16'h7e00;
      else
        y = 16'h7c00;
    end else if (x[14:10] == 0) begin
      y = 16'hfc00;
    end else if (x[15]) begin
      y = 16'h7e00;
    end else begin
      m = (64'sd1024 + $signed({{1'b0, x[9:0]}})) <<< 30;
      e = $signed({{1'b0, x[14:10]}}) - 64'sd15;
      if ({{1'b1, x[9:0]}} >= 11'd1449) begin
        m = m >>> 1;
        e = e + 1;
      end

      z = div_q40(m - ONE, m + ONE);
      z2 = mul_q40(z, z);
      p = 64'sd122167958642;
      p = 64'sd157073089682 + mul_q40(z2, p);
      p = 64'sd219902325555 + mul_q40(z2, p);
      p = 64'sd366503875925 + mul_q40(z2, p);
      logm = mul_q40(z, ONE + mul_q40(z2, p)) <<< 1;
      valueq = e * LN2 + logm;

      if (valueq == 0) begin
        y = 16'h0000;
      end else begin
        absq = valueq[63] ? -valueq : valueq;
        normq = absq;
        bin_exp = 0;
        for (i = 0; i < 8; i = i + 1)
          if (normq >= 64'sd2199023255552) begin
            normq = normq >>> 1;
            bin_exp = bin_exp + 1;
          end
        for (i = 0; i < 40; i = i + 1)
          if (normq < ONE) begin
            normq = normq <<< 1;
            bin_exp = bin_exp - 1;
          end

        rounded32 = normq >>> 17;
        rem = normq - (rounded32 <<< 17);
        if ((rem > 64'sd65536) ||
            ((rem == 64'sd65536) && rounded32[0]))
          rounded32 = rounded32 + 1;
        if (rounded32 >= 16777216) begin
          rounded32 = 8388608;
          bin_exp = bin_exp + 1;
        end

        rounded = rounded32 >>> 13;
        rem = rounded32 - (rounded <<< 13);
        if ((rem > 64'sd4096) ||
            ((rem == 64'sd4096) && rounded[0]))
          rounded = rounded + 1;
        if (rounded >= 2048) begin
          rounded = 1024;
          bin_exp = bin_exp + 1;
        end
        out_exp = bin_exp + 15;
        y = {{valueq[63], out_exp[4:0], rounded[9:0]}};
      end
    end
  end
endmodule
"""


def emit_fp16_log2(detail: str) -> str:
    return (
        emit_fp16_log(detail)
        .replace(
            "// structural ln: exponent decomposition and Q40 centered atanh polynomial",
            "// structural log2: exponent decomposition and Q40 centered atanh polynomial",
        )
        .replace(
            "localparam signed [63:0] LN2 = 64'sd762123384786;",
            "localparam signed [63:0] INV_LN2 = 64'sd1586259972792;",
        )
        .replace(
            "valueq = e * LN2 + logm;",
            "valueq = e * ONE + mul_q40(logm, INV_LN2);",
        )
    )


def emit_fp16_log10(detail: str) -> str:
    return (
        emit_fp16_log(detail)
        .replace(
            "// structural ln: exponent decomposition and Q40 centered atanh polynomial",
            "// structural log10: exponent decomposition and Q40 centered atanh polynomial",
        )
        .replace(
            "localparam signed [63:0] LN2 = 64'sd762123384786;",
            "localparam signed [63:0] LOG10_2 = 64'sd330985980542;\n"
            "  localparam signed [63:0] INV_LN10 = 64'sd477511832732;",
        )
        .replace(
            "valueq = e * LN2 + logm;",
            "valueq = e * LOG10_2 + mul_q40(logm, INV_LN10);",
        )
    )


def emit_fp16_sin(detail: str) -> str:
    template = """// __DETAIL__
// Q40 pi/2 range reduction, polynomial quadrants, FP32 then FP16 RNE
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE  = 64'sd1099511627776;
  localparam signed [63:0] PIO2 = 64'sd1727108826179;
  localparam signed [63:0] PI4  = 64'sd863554413089;

  reg signed [63:0] aq, n, r, z, p, sq, cq, vq, magq, normq;
  reg signed [63:0] bin_exp, out_exp, rounded32, rounded;
  reg result_sign;
  integer i;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  always @(*) begin
    y = 16'h0000;
    aq = 0; n = 0; r = 0; z = 0; p = 0; sq = 0; cq = 0;
    vq = 0; magq = 0; normq = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; result_sign = 0;

    if (x[14:10] == 5'h1f) begin
      y = 16'h7e00;
    end else if (x[14:10] == 0) begin
      y = {x[15], 15'd0};
    end else begin
      aq = (64'sd1024 + $signed({1'b0, x[9:0]}))
            <<< ({1'b0, x[14:10]} + 15);
      n = (aq + PI4) / PIO2;
      r = aq - n * PIO2;
      z = mul_q40(r, r);

      p = 64'sd3029959;
      p = -64'sd218157069    + mul_q40(p, z);
      p = 64'sd9162596898    + mul_q40(p, z);
      p = -64'sd183251937963 + mul_q40(p, z);
      sq = r + mul_q40(mul_q40(r, z), p);

      p = 64'sd27269634;
      p = -64'sd1527099483   + mul_q40(p, z);
      p = 64'sd45812984491   + mul_q40(p, z);
      p = -64'sd549755813888 + mul_q40(p, z);
      cq = ONE + mul_q40(z, p);

      if (n[0])
        vq = cq;
      else
        vq = sq;
      if (n[1])
        vq = 0 - vq;

      result_sign = x[15] != vq[63];
      if (vq[63])
        magq = 0 - vq;
      else
        magq = vq;
      normq = magq;
      bin_exp = 0;
      for (i = 0; i < 48; i = i + 1)
        if (normq < ONE) begin
          normq = normq <<< 1;
          bin_exp = bin_exp - 1;
        end

      rounded32 = normq >>> 17;
      rounded32 = (normq + 64'sd65535 + rounded32[0]) >>> 17;
      if (rounded32 >= 16777216) begin
        rounded32 = 8388608;
        bin_exp = bin_exp + 1;
      end

      rounded = rounded32 >>> 13;
      rounded = (rounded32 + 64'sd4095 + rounded[0]) >>> 13;
      if (rounded >= 2048) begin
        rounded = 1024;
        bin_exp = bin_exp + 1;
      end

      out_exp = bin_exp + 15;
      if (out_exp <= 0)
        y = {result_sign, 15'd0};
      else
        y = {result_sign, out_exp[4:0], rounded[9:0]};
    end
  end
endmodule
"""
    return template.replace("__DETAIL__", detail)


def emit_fp16_tan(detail: str) -> str:
    template = """// __DETAIL__
// Q40 pi/2 reduction and cubic-over-cubic rational tangent
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE  = 64'sd1099511627776;
  localparam signed [63:0] TWO  = 64'sd2199023255552;
  localparam signed [63:0] PIO2 = 64'sd1727108826179;
  localparam signed [63:0] PI4  = 64'sd863554413089;

  reg signed [63:0] aq, n, r, z, p, sq, cq, vq, magq, normq;
  reg signed [63:0] bin_exp, out_exp, rounded32, rounded;
  reg result_sign;
  integer i;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  function signed [63:0] div_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] numerator;
    begin
      numerator = a * 128'sd1099511627776;
      div_q40 = numerator / b;
    end
  endfunction

  always @(*) begin
    y = 16'h0000;
    aq = 0; n = 0; r = 0; z = 0; p = 0; sq = 0; cq = 0;
    vq = 0; magq = 0; normq = 0; bin_exp = 0; out_exp = 0;
    rounded32 = 0; rounded = 0; result_sign = 0;

    if (x[14:10] == 5'h1f) begin
      y = 16'h7e00;
    end else if (x[14:10] == 0) begin
      y[15] = x[15];
    end else begin
      aq = (64'sd1024 + x[9:0]) <<< (x[14:10] + 15);
      n = (aq + PI4) / PIO2;
      r = aq - n * PIO2;
      z = mul_q40(r, r);

      p = -64'sd1099511627776;
      p = 64'sd415615395299328 + mul_q40(p, z);
      p = -64'sd19049038951219200 + mul_q40(p, z);
      sq = 64'sd148582503819509760 + mul_q40(p, z);

      p = -64'sd30786325577728;
      p = 64'sd3463461627494400 + mul_q40(p, z);
      p = -64'sd68576540224389120 + mul_q40(p, z);
      cq = 64'sd148582503819509760 + mul_q40(p, z);

      vq = mul_q40(r, div_q40(sq, cq));
      if (n[0])
        vq = 0 - div_q40(ONE, vq);

      result_sign = x[15] != vq[63];
      if (vq[63])
        magq = 0 - vq;
      else
        magq = vq;
      normq = magq;
      bin_exp = 0;
      for (i = 0; i < 48; i = i + 1)
        if (normq < ONE) begin
          normq = normq <<< 1;
          bin_exp = bin_exp - 1;
        end
      for (i = 0; i < 24; i = i + 1)
        if (normq >= TWO) begin
          normq = normq >>> 1;
          bin_exp = bin_exp + 1;
        end

      rounded32 = normq >>> 17;
      rounded32 = (normq + 64'sd65535 + rounded32[0]) >>> 17;
      rounded = rounded32 >>> 13;
      rounded = (rounded32 + 64'sd4095 + rounded[0]) >>> 13;
      out_exp = bin_exp + 15 + rounded[11];
      if (out_exp <= 0) begin
        y[15] = result_sign;
      end else if (out_exp >= 31) begin
        y = 16'h7c00;
        y[15] = result_sign;
      end else begin
        y[15] = result_sign;
        y[14:10] = out_exp[4:0];
        y[9:0] = rounded[9:0];
      end
    end
  end
endmodule
"""
    return template.replace("__DETAIL__", detail)


def emit_fp16_sinh(detail: str, words: Optional[Sequence[int]] = None) -> str:
    template = """// __DETAIL__
// Q40 ln2 reduction and shared degree-7 exp for sinh reconstruction
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE   = 64'sd1099511627776;
  localparam signed [63:0] TWO   = 64'sd2199023255552;
  localparam signed [63:0] LN2   = 64'sd762123384786;
  localparam signed [63:0] HLN2  = 64'sd381061692393;
  localparam signed [63:0] LIMIT = 64'sd12962211299328;

  reg signed [63:0] aq, k, r, ep, em, vq, normq;
  reg signed [63:0] bin_exp, out_exp, rounded32, rounded;
  reg [9:0] frac;
  reg [4:0] xe;
  integer i;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  function signed [63:0] exp_q40;
    input signed [63:0] a;
    reg signed [63:0] p;
    begin
      p = 64'sd218157069;
      p = 64'sd1527099483    + mul_q40(p, a);
      p = 64'sd9162596898    + mul_q40(p, a);
      p = 64'sd45812984491   + mul_q40(p, a);
      p = 64'sd183251937963  + mul_q40(p, a);
      p = 64'sd549755813888  + mul_q40(p, a);
      p = 64'sd1099511627776 + mul_q40(p, a);
      exp_q40 = 64'sd1099511627776 + mul_q40(p, a);
    end
  endfunction

  always @(*) begin
    y = 16'h0000;
    y[15] = x[15];
    frac = x[9:0];
    xe = x[14:10];
    aq = 0; k = 0; r = 0; ep = 0; em = 0; vq = 0; normq = 0;
    bin_exp = 0; out_exp = 0; rounded32 = 0; rounded = 0;

    if (xe == 5'h1f) begin
      if (frac == 0)
        y[14:0] = 15'h7c00;
      else
        y = 16'h7e00;
    end else if (xe != 0) begin
      aq = (64'sd1024 + frac) <<< (xe + 15);
      if (aq >= LIMIT) begin
        y[14:0] = 15'h7c00;
      end else begin
        k = (aq + HLN2) / LN2;
        r = aq - k * LN2;
        ep = exp_q40(r) <<< k;
        em = exp_q40(0 - r) >>> k;
        vq = (ep - em) >>> 1;

        normq = vq;
        bin_exp = 0;
        for (i = 0; i < 48; i = i + 1)
          if (normq < ONE) begin
            normq = normq <<< 1;
            bin_exp = bin_exp - 1;
          end
        for (i = 0; i < 24; i = i + 1)
          if (normq >= TWO) begin
            normq = normq >>> 1;
            bin_exp = bin_exp + 1;
          end

        rounded32 = normq >>> 17;
        rounded32 = (normq + 64'sd65535 + rounded32[0]) >>> 17;
        rounded = rounded32 >>> 13;
        rounded = (rounded32 + 64'sd4095 + rounded[0]) >>> 13;
        out_exp = bin_exp + 15 + rounded[11];
        if (out_exp > 0) begin
          y[14:10] = out_exp[4:0];
          y[9:0] = rounded[9:0];
        end
      end
    end
  end
endmodule
"""
    template = isolate_endpoint_kernel(template, words)
    return template.replace("__DETAIL__", detail).replace(
        "    end else if (xe != 0) begin",
        emit_endpoint_guards(words) + "    end else if (xe != 0) begin", 1)


def emit_fp16_tanh(detail: str) -> str:
    template = """// __DETAIL__
// Q40 exp(2|x|) rational reconstruction with signed-one saturation
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE   = 64'sd1099511627776;
  localparam signed [63:0] LN2   = 64'sd762123384786;
  localparam signed [63:0] HLN2  = 64'sd381061692393;
  localparam signed [63:0] LIMIT = 64'sd4956392259584;

  reg signed [63:0] aq, u, k, r, ep, vq, normq;
  reg signed [63:0] bin_exp, out_exp, rounded;
  reg [9:0] frac;
  reg [4:0] xe;
  integer i;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  function signed [63:0] div_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] numerator;
    begin
      numerator = a * 128'sd1099511627776;
      div_q40 = numerator / b;
    end
  endfunction

  function signed [63:0] exp_q40;
    input signed [63:0] a;
    reg signed [63:0] p;
    begin
      p = 64'sd1527099483;
      p = 64'sd9162596898    + mul_q40(p, a);
      p = 64'sd45812984491   + mul_q40(p, a);
      p = 64'sd183251937963  + mul_q40(p, a);
      p = 64'sd549755813888  + mul_q40(p, a);
      p = 64'sd1099511627776 + mul_q40(p, a);
      exp_q40 = 64'sd1099511627776 + mul_q40(p, a);
    end
  endfunction

  always @(*) begin
    y = 16'h0000;
    y[15] = x[15];
    frac = x[9:0];
    xe = x[14:10];
    aq = 0; u = 0; k = 0; r = 0; ep = 0; vq = 0; normq = 0;
    bin_exp = 0; out_exp = 0; rounded = 0;

    if (xe == 5'h1f) begin
      if (frac == 0)
        y[14:0] = 15'h3c00;
      else
        y = 16'h7e00;
    end else if (xe != 0) begin
      aq = (64'sd1024 + frac) <<< (xe + 15);
      if (aq >= LIMIT) begin
        y[14:0] = 15'h3c00;
      end else begin
        u = aq <<< 1;
        k = (u + HLN2) / LN2;
        r = u - k * LN2;
        ep = exp_q40(r) <<< k;
        vq = div_q40(ep - ONE, ep + ONE);

        normq = vq;
        bin_exp = 0;
        for (i = 0; i < 48; i = i + 1)
          if (normq < ONE) begin
            normq = normq <<< 1;
            bin_exp = bin_exp - 1;
          end

        rounded = normq >>> 30;
        rounded = (normq + 64'sd536870911 + rounded[0]) >>> 30;
        out_exp = bin_exp + 15 + rounded[11];
        y[14:10] = out_exp[4:0];
        y[9:0] = rounded[9:0];
      end
    end
  end
endmodule
"""
    # The positive Q40 quotient is normalized by the bounded loop; final RN10
    # yields a significand in [1024, 2048], including its rounding carry.
    return compact_semantic_rtl(template.replace("__DETAIL__", detail),
                                normalized_activation_format=(5, 10))


def emit_fp16_sigmoid(detail: str, words: Optional[Sequence[int]] = None) -> str:
    template = """// __DETAIL__
// structural FP16 logistic sigmoid: FP32 exp/add/div then FP16 RNE
module top(input [15:0] x, output reg [15:0] y);
  localparam signed [63:0] ONE    = 64'sd1099511627776;
  localparam signed [63:0] TWO    = 64'sd2199023255552;
  localparam signed [63:0] LN2    = 64'sd762123384786;
  localparam signed [63:0] HLN2   = 64'sd381061692393;
  localparam signed [63:0] PLIMIT = 64'sd9148280340480;
  localparam signed [63:0] NLIMIT = 64'sd10677288697856;

  reg signed [63:0] aq, k, r, eq, dq, vq, normq, limitq;
  reg signed [63:0] bin_exp, out_exp, rounded;
  reg [9:0] frac;
  reg [4:0] xe;
  reg xs;
  integer i;

  function signed [63:0] mul_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] product;
    begin
      product = a * b;
      mul_q40 = product / 128'sd1099511627776;
    end
  endfunction

  function signed [63:0] div_q40;
    input signed [63:0] a;
    input signed [63:0] b;
    reg signed [127:0] numerator;
    begin
      numerator = a * 128'sd1099511627776;
      div_q40 = numerator / b;
    end
  endfunction

  function signed [63:0] exp_q40;
    input signed [63:0] a;
    reg signed [63:0] p;
    begin
      p = 64'sd1527099483;
      p = 64'sd9162596898    + mul_q40(p, a);
      p = 64'sd45812984491   + mul_q40(p, a);
      p = 64'sd183251937963  + mul_q40(p, a);
      p = 64'sd549755813888  + mul_q40(p, a);
      p = 64'sd1099511627776 + mul_q40(p, a);
      exp_q40 = 64'sd1099511627776 + mul_q40(p, a);
    end
  endfunction

  function signed [63:0] f32_q40;
    input signed [63:0] a;
    reg signed [63:0] n, e, m;
    integer j;
    begin
      n = a;
      e = 0;
      for (j = 0; j < 48; j = j + 1)
        if (n < ONE) begin
          n = n <<< 1;
          e = e - 1;
        end
      for (j = 0; j < 32; j = j + 1)
        if (n >= TWO) begin
          n = n >>> 1;
          e = e + 1;
        end
      m = n >>> 17;
      m = (n + 64'sd65535 + m[0]) >>> 17;
      f32_q40 = m <<< (e + 17);
    end
  endfunction

  function [15:0] saturation;
    input s;
    begin
      if (s)
        saturation = 16'h0000;
      else
        saturation = 16'h3c00;
    end
  endfunction

  always @(*) begin
    y = 16'h3800;
    frac = x[9:0];
    xe = x[14:10];
    xs = x[15];
    aq = 0; k = 0; r = 0; eq = 0; dq = 0; vq = 0; normq = 0; limitq = 0;
    bin_exp = 0; out_exp = 0; rounded = 0;

    if (xe == 5'h1f) begin
      if (frac == 0)
        y = saturation(xs);
      else
        y = 16'h7e00;
    end else if (xe != 0) begin
      aq = (64'sd1024 + frac) <<< (xe + 15);
      limitq = xs ? NLIMIT : PLIMIT;
      if (aq >= limitq) begin
        y = saturation(xs);
      end else begin
        k = (aq + HLN2) / LN2;
        r = aq - k * LN2;
        if (xs)
          eq = exp_q40(r) <<< k;
        else
          eq = exp_q40(0 - r) >>> k;
        eq = f32_q40(eq);
        dq = f32_q40(ONE + eq);
        vq = div_q40(ONE, dq);
        vq = f32_q40(vq);

        normq = vq;
        bin_exp = 0;
        for (i = 0; i < 48; i = i + 1)
          if (normq < ONE) begin
            normq = normq <<< 1;
            bin_exp = bin_exp - 1;
          end

        rounded = normq >>> 30;
        rounded = (normq + 64'sd536870911 + rounded[0]) >>> 30;
        out_exp = bin_exp + 15 + rounded[11];
        y[14:10] = out_exp[4:0];
        y[9:0] = rounded[9:0];
      end
    end
  end
endmodule
"""
    template = isolate_endpoint_kernel(template, words)
    rtl = template.replace("__DETAIL__", detail).replace(
        "    end else if (xe != 0) begin",
        emit_endpoint_guards(words) + "    end else if (xe != 0) begin", 1)
    # Keep endpoint isolation and all FP32 stages before the proved positive
    # normalized-significand interval used by the final RN10 pack.
    return compact_semantic_rtl(rtl, normalized_activation_format=(5, 10))


def emit_fp16_square(detail: str) -> str:
    return lowest_cost_source([emit_binary_square(5, 10, detail),
                               emit_guarded_binary_square(5, 10, detail)])


def emit_fp16_recip(detail: str) -> str:
    return emit_binary_reciprocal(5, 10, detail)


def emit_fp16_recip_square(detail: str) -> str:
    return emit_binary_recip_power(5, 10, 2, detail)


def emit_fp16_recip_sqrt(detail: str) -> str:
    return lowest_cost_source([emit_newton_rounded_rsqrt(5, 10, detail),
                               emit_binary_reciprocal_sqrt(5, 10, detail)])


def emit_fp16_cube(detail: str) -> str:
    return emit_binary_cube(5, 10, detail)


def emit_fp16_cbrt(detail: str) -> str:
    return lowest_cost_source([emit_binary_root(5, 10, 3, False, detail, precision=23),
                               emit_staged_cubic_root(5, 10, detail, precision=23)])


def emit_fp16_recip_cube(detail: str) -> str:
    original = emit_binary_recip_power(5, 10, 3, detail)
    try:
        compact = emit_binary_reciprocal_power(5, 10, 3, detail)
    except ValueError:
        return original
    return lowest_cost_source([original, compact])


def emit_fp16_recip_cbrt(detail: str) -> str:
    return emit_inverse_cube_scan(5, 10, detail)


def try_float_simple_structured(
    n_in: int, n_out: int, words: List[int], description=_DESCRIPTION_UNSET,
) -> Optional[Candidate]:
    desc = describe_truth(n_in, n_out, words) if description is _DESCRIPTION_UNSET else description
    if desc is None or desc.family != "floating-point unary":
        return None
    if desc.detail.startswith("BF16 exp(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point exponential", emit_bf16_exp(desc.detail))
    if desc.detail.startswith("BF16 2^x,"):
        return Candidate(f"{desc.detail}; structural fixed-point power of two", emit_bf16_pow2(desc.detail))
    if desc.detail.startswith("BF16 10^x,"):
        return Candidate(f"{desc.detail}; structural fixed-point power of ten", emit_bf16_pow10(desc.detail))
    if desc.detail.startswith("BF16 ln(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point natural logarithm", emit_bf16_log(desc.detail))
    if desc.detail.startswith("BF16 log2(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point base-2 logarithm", emit_bf16_log2(desc.detail))
    if desc.detail.startswith("BF16 log10(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point base-10 logarithm", emit_bf16_log10(desc.detail))
    if desc.detail.startswith("BF16 sin(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point sine", emit_bf16_sin(desc.detail))
    if desc.detail.startswith("BF16 tan(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point tangent", emit_bf16_tan(desc.detail))
    if desc.detail.startswith("BF16 sinh(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point hyperbolic sine", emit_bf16_sinh(desc.detail))
    if desc.detail.startswith("BF16 tanh(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point hyperbolic tangent", emit_bf16_tanh(desc.detail))
    if desc.detail.startswith("BF16 1/(1+exp(-x)),"):
        return Candidate(f"{desc.detail}; structural fixed-point logistic sigmoid", emit_bf16_sigmoid(desc.detail))
    if desc.detail.startswith("BF16 1/x,"):
        return Candidate(f"{desc.detail}; structured reciprocal", emit_bf16_recip(desc.detail))
    if desc.detail.startswith("BF16 1/x^2,"):
        return Candidate(f"{desc.detail}; structured reciprocal square", emit_bf16_recip_square(desc.detail))
    if desc.detail.startswith("BF16 1/sqrt(x),"):
        return Candidate(f"{desc.detail}; structured reciprocal square root", emit_bf16_recip_sqrt(desc.detail))
    if desc.detail.startswith("BF16 x^2,"):
        return Candidate(f"{desc.detail}; structured square", emit_bf16_square(desc.detail))
    if desc.detail.startswith("BF16 x^3,"):
        return Candidate(f"{desc.detail}; structured cube", emit_bf16_cube(desc.detail))
    if desc.detail.startswith("BF16 cbrt(x),"):
        return Candidate(f"{desc.detail}; structured cube root", emit_bf16_cbrt(desc.detail))
    if desc.detail.startswith("BF16 1/x^3,"):
        return Candidate(f"{desc.detail}; structured reciprocal cube", emit_bf16_recip_cube(desc.detail))
    if desc.detail.startswith("BF16 1/cbrt(x),"):
        return Candidate(f"{desc.detail}; structured reciprocal cube root", emit_bf16_recip_cbrt(desc.detail))
    if desc.detail.startswith("FP16 exp(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point exponential", emit_fp16_exp(desc.detail))
    if desc.detail.startswith("FP16 2^x,"):
        return Candidate(f"{desc.detail}; structural fixed-point power of two", emit_fp16_pow2(desc.detail))
    if desc.detail.startswith("FP16 10^x,"):
        return Candidate(f"{desc.detail}; structural fixed-point power of ten", emit_fp16_pow10(desc.detail))
    if desc.detail.startswith("FP16 ln(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point natural logarithm", emit_fp16_log(desc.detail))
    if desc.detail.startswith("FP16 log2(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point base-2 logarithm", emit_fp16_log2(desc.detail))
    if desc.detail.startswith("FP16 log10(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point base-10 logarithm", emit_fp16_log10(desc.detail))
    if desc.detail.startswith("FP16 sin(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point sine", emit_fp16_sin(desc.detail))
    if desc.detail.startswith("FP16 tan(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point tangent", emit_fp16_tan(desc.detail))
    if desc.detail.startswith("FP16 sinh(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point hyperbolic sine", emit_fp16_sinh(desc.detail, words))
    if desc.detail.startswith("FP16 tanh(x),"):
        return Candidate(f"{desc.detail}; structural fixed-point hyperbolic tangent", emit_fp16_tanh(desc.detail))
    if desc.detail.startswith("FP16 1/(1+exp(-x)),"):
        return Candidate(f"{desc.detail}; structural fixed-point logistic sigmoid", emit_fp16_sigmoid(desc.detail, words))
    if desc.detail.startswith("FP16 1/x,"):
        return Candidate(f"{desc.detail}; structured reciprocal", emit_fp16_recip(desc.detail))
    if desc.detail.startswith("FP16 1/x^2,"):
        return Candidate(f"{desc.detail}; structured reciprocal square", emit_fp16_recip_square(desc.detail))
    if desc.detail.startswith("FP16 1/sqrt(x),"):
        return Candidate(f"{desc.detail}; structured reciprocal square root", emit_fp16_recip_sqrt(desc.detail))
    if desc.detail.startswith("FP16 x^3,"):
        return Candidate(f"{desc.detail}; structured cube", emit_fp16_cube(desc.detail))
    if desc.detail.startswith("FP16 cbrt(x),"):
        return Candidate(f"{desc.detail}; structured cube root", emit_fp16_cbrt(desc.detail))
    if desc.detail.startswith("FP16 1/x^3,"):
        return Candidate(f"{desc.detail}; structured reciprocal cube", emit_fp16_recip_cube(desc.detail))
    if desc.detail.startswith("FP16 1/cbrt(x),"):
        return Candidate(f"{desc.detail}; structured reciprocal cube root", emit_fp16_recip_cbrt(desc.detail))
    if desc.detail.startswith("FP16 x^2,"):
        return Candidate(f"{desc.detail}; structured square", emit_fp16_square(desc.detail))
    return None


def try_float_sqrt_structured(
    n_in: int, n_out: int, words: List[int], description=_DESCRIPTION_UNSET,
) -> Optional[Candidate]:
    desc = describe_truth(n_in, n_out, words) if description is _DESCRIPTION_UNSET else description
    if desc is None or desc.family != "floating-point unary":
        return None
    if " sqrt(x)," not in desc.detail:
        return None
    if desc.detail.startswith("BF16 "):
        return Candidate(f"{desc.detail}; structured sqrt", emit_bf16_sqrt(words, desc.detail))
    if desc.detail.startswith("FP16 "):
        return Candidate(f"{desc.detail}; structured sqrt", emit_fp16_sqrt(desc.detail))
    return None


def try_bit_projection(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    tables = words_to_bit_tables(words, n_out)
    exprs = [projection_expr(bit, n_in, table) for bit, table in enumerate(tables)]
    if any(expr is None for expr in exprs):
        return None
    concat = ", ".join(reversed([expr or "1'b0" for expr in exprs]))
    return Candidate("bit projection/inversion", module_wire(n_in, n_out, [f"  assign y = {{{concat}}};"]))


def affine_expr(n_in: int, table: List[int]) -> Optional[str]:
    const = table[0]
    coeffs = [table[1 << i] ^ const for i in range(n_in)]
    for x, value in enumerate(table):
        parity = const
        active = x
        bit = 0
        while active:
            if active & 1:
                parity ^= coeffs[bit]
            active >>= 1
            bit += 1
        if parity != value:
            return None
    terms = [f"x[{i}]" for i, coeff in enumerate(coeffs) if coeff]
    if const:
        terms.append("1'b1")
    if not terms:
        return "1'b0"
    return " ^ ".join(terms)


def try_affine(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    tables = words_to_bit_tables(words, n_out)
    exprs = [affine_expr(n_in, table) for table in tables]
    if any(expr is None for expr in exprs):
        return None
    concat = ", ".join(reversed([expr or "1'b0" for expr in exprs]))
    return Candidate("GF(2) affine outputs", module_wire(n_in, n_out, [f"  assign y = {{{concat}}};"]))


def try_integer_model(n_in: int, n_out: int, words: List[int]) -> Optional[Candidate]:
    """Adapt a full-domain learned word arithmetic model to the RTL API."""
    model = infer_integer_model(n_in, n_out, words)
    if model is None:
        return None
    family, verilog = model
    return Candidate(family, verilog)


STRUCTURAL_MATCHERS: Sequence[Callable[[int, int, List[int]], Optional[Candidate]]] = (
    try_constant,
    try_bit_projection,
    try_affine,
    try_unsigned_square,
    try_unsigned_div,
    try_isqrt,
    try_unsigned_mul,
    try_signed_mul,
    try_integer_model,
    try_popcount,
    try_fp4_e2m1_dot2,
    try_signed_magnitude_q21_dot2,
    try_unsigned_q11_dot4,
    try_unsigned_q11_sum8,
    try_fp4_e2m1_fma_fp8,
    try_fp8_e4m3fn_add,
    try_fp8_e4m3fn_mul,
    try_fp8_e4m3fn_div,
    try_fp8_e4m3fn_fmod,
    try_fp8_e4m3fn_hypot,
    try_fp8_e5m2_add,
    try_fp8_e5m2_mul,
    try_fp8_e5m2_div,
    try_fp8_e5m2_fmod,
    try_fp8_e5m2_hypot,
    try_float_simple_structured,
    try_float_sqrt_structured,
)


def infer_from_words(
    n_in: int,
    n_out: int,
    words: List[int],
    allow_field_cases: bool = False,
    allow_boolean_fallback: bool = False,
    description=_DESCRIPTION_UNSET,
) -> Optional[Candidate]:
    """Infer from already decoded ABC-oriented words, sharing one description.

    Omit description to classify lazily once; an explicit None means that
    classification already found no semantic match. No process-global input
    cache is used, so repeated calls with changed data remain independent.
    """
    matchers = list(STRUCTURAL_MATCHERS)
    if allow_field_cases:
        matchers.extend((try_float_field_factored, try_float_format_field_factored,
                         try_16to8_field_factored))
    semantic_matchers = (try_float_simple_structured, try_float_sqrt_structured,
                         try_float_field_factored)
    for matcher in matchers:
        if matcher in semantic_matchers:
            if description is _DESCRIPTION_UNSET:
                description = describe_truth(n_in, n_out, words)
            candidate = matcher(n_in, n_out, words, description=description)
        else:
            candidate = matcher(n_in, n_out, words)
        if candidate is not None:
            if candidate.high_level:
                candidate.verilog = compact_semantic_rtl(candidate.verilog)
            return candidate
    if allow_boolean_fallback:
        family, verilog, node_count = choose_exact_boolean_fallback(n_in, n_out, words)
        return Candidate(family, verilog, high_level=False, structural_nodes=node_count)
    return None


def infer_truth(
    truth_path: Path,
    allow_field_cases: bool = False,
    allow_boolean_fallback: bool = False,
) -> Tuple[int, int, Optional[Candidate]]:
    n_in, n_out, words = read_truth_words(truth_path)
    return n_in, n_out, infer_from_words(
        n_in, n_out, words, allow_field_cases, allow_boolean_fallback)


def verify_candidate(truth: Path, verilog: Path, timeout: int) -> bool:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "verify_truth_sim.py"),
        str(truth),
        str(verilog),
        "--json",
        "--run-timeout",
        str(timeout),
    ]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        return False
    try:
        row = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False
    return row.get("status") == "pass"


def verify_yosys_candidate(truth: Path, verilog: Path, timeout: int) -> bool:
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "verify_truth_yosys.py"),
        str(truth),
        str(verilog),
        "--json",
        "--run-timeout",
        str(timeout),
    ]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        return False
    try:
        row = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False
    return row.get("status") == "pass" and row.get("frontend") == "pass"


def verify_structural_candidate(truth: Path, verilog: Path, certificate: Path) -> bool:
    """Check scalar DAGs and reusable Boolean functions through the frontend.

    The legacy structural-only parser accepts packed nodes, whereas compact
    fallback emitters also produce scalar DAGs and function calls. The fixed
    frontend plus complete-domain checker covers all emitted representations.
    """
    cmd = [sys.executable, str(Path(__file__).resolve().parents[1] / "verify_truth_yosys.py"),
           str(truth), str(verilog), "--no-cache", "--json"]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    try:
        row = json.loads(proc.stdout)
    except json.JSONDecodeError:
        row = {"status": "error", "error": proc.stderr[-2000:]}
    row["strict"] = proc.returncode == 0 and row.get("status") == "pass" and row.get("frontend") == "pass"
    row["vectors_checked"] = row.get("vectors", 0)
    row["output_bits_checked"] = row.get("n_outputs", 0) if row["strict"] else 0
    certificate.parent.mkdir(parents=True, exist_ok=True)
    certificate.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n")
    return row["strict"]


def output_path_for(truth: Path, args: argparse.Namespace) -> Path:
    if args.output:
        return Path(args.output)
    out_dir = Path(args.out_dir)
    if args.flat:
        return out_dir / f"{truth.stem}.v"
    return out_dir / truth.stem / f"{truth.stem}.v"


def process_one(truth: Path, args: argparse.Namespace) -> dict:
    n_in, n_out, words = read_truth_words(truth)
    desc = describe_truth(n_in, n_out, words)
    candidate = infer_from_words(
        n_in, n_out, words,
        description=desc,
        allow_field_cases=args.allow_field_cases,
        allow_boolean_fallback=args.allow_boolean_fallback,
    )
    row = {
        "case": truth.stem,
        "truth": str(truth),
        "n_inputs": n_in,
        "n_outputs": n_out,
        "status": "no_match",
    }
    if desc:
        row.update(
            {
                "description_family": desc.family,
                "description": desc.detail,
                "description_confidence": desc.confidence,
            }
        )
    if candidate is None:
        return row
    out_path = output_path_for(truth, args)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(candidate.verilog)
    row.update(
        {
            "status": "generated",
            "family": candidate.family,
            "verilog": str(out_path),
            "high_level": candidate.high_level,
        }
    )
    if candidate.structural_nodes is not None:
        row["structural_nodes"] = candidate.structural_nodes
    if args.verify or args.verify_yosys:
        if args.verify_yosys:
            verified = verify_yosys_candidate(truth, out_path, args.run_timeout)
            row["verification_method"] = "Yosys-lowered exhaustive truth replay"
        elif candidate.high_level:
            verified = verify_candidate(truth, out_path, args.run_timeout)
            row["verification_method"] = "exhaustive Verilog simulation"
        else:
            certificate = out_path.with_suffix(".certificate.json")
            verified = verify_structural_candidate(truth, out_path, certificate)
            row["verification_method"] = "fixed Yosys frontend and complete-domain replay"
            row["certificate"] = str(certificate)
        row["verify"] = "pass" if verified else "fail"
        if row["verify"] != "pass" and args.remove_failed:
            out_path.unlink(missing_ok=True)
            row["status"] = "removed_failed"
    return row


def collect_truths(input_path: Path) -> List[Path]:
    if input_path.is_dir():
        return sorted(input_path.glob("*.truth"))
    return [input_path]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help=".truth file or directory")
    parser.add_argument("output", nargs="?", help="Output .v for single-file mode")
    parser.add_argument("--out-dir", default="truth_reverse_out")
    parser.add_argument("--flat", action="store_true", help="Write <out-dir>/<case>.v instead of per-case dirs")
    parser.add_argument("--verify", action="store_true", help="Run exhaustive iverilog verification after generation")
    parser.add_argument(
        "--verify-yosys",
        action="store_true",
        help="Require Yosys frontend acceptance and exhaustive replay of its lowered Verilog",
    )
    parser.set_defaults(allow_field_cases=False)
    parser.add_argument(
        "--allow-field-cases",
        dest="allow_field_cases",
        action="store_true",
        help="Explicitly allow generic field-factored LUT RTL. Disabled by default.",
    )
    parser.add_argument(
        "--no-field-cases",
        dest="allow_field_cases",
        action="store_false",
        help="Disable field-factored LUT RTL (the default).",
    )
    parser.add_argument(
        "--allow-boolean-fallback",
        action="store_true",
        help=(
            "After high-level recognizers fail, emit an exact structural ANF or shared ROBDD. "
            "The result is explicitly marked as low-level and is never counted as high-level RTL."
        ),
    )
    parser.add_argument("--remove-failed", action="store_true")
    parser.add_argument("--run-timeout", type=int, default=180)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    truths = collect_truths(Path(args.input))
    rows = [process_one(truth, args) for truth in truths]
    if args.json:
        print(json.dumps(rows if len(rows) != 1 else rows[0], indent=2, sort_keys=True))
    else:
        for row in rows:
            suffix = f" verify={row.get('verify')}" if "verify" in row else ""
            family = f" {row.get('family')}" if row.get("family") else ""
            print(f"{row['case']}: {row['status']}{family}{suffix}")
    failed = [row for row in rows if row["status"] in {"no_match", "removed_failed"} or row.get("verify") == "fail"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
