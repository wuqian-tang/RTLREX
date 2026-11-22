"""High-level semantic descriptions for complete truth tables."""

from __future__ import annotations

import ctypes
import math
import struct
import warnings
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Iterable, List, Optional, Sequence


try:
    import numpy as np
except ImportError:  # pragma: no cover - optional classifier dependency
    np = None  # type: ignore[assignment]


@dataclass
class Description:
    family: str
    detail: str
    confidence: str = "exact"


def mask(width: int) -> int:
    return (1 << width) - 1


def signed_value(value: int, width: int) -> int:
    sign = 1 << (width - 1)
    return value - (1 << width) if value & sign else value


def fp8_e4m3fn_add_word(value: int) -> int:
    a = (value >> 8) & 0xFF
    b = value & 0xFF
    if (a & 0x7F) == 0x7F or (b & 0x7F) == 0x7F:
        return 0x7F

    def magnitude(v: int) -> int:
        exponent = (v >> 3) & 0xF
        fraction = v & 0x7
        return fraction if exponent == 0 else (8 + fraction) << (exponent - 1)

    va = -magnitude(a) if a & 0x80 else magnitude(a)
    vb = -magnitude(b) if b & 0x80 else magnitude(b)
    total = va + vb
    if total == 0:
        return 0x80 if value == 0x8080 else 0

    sign = 0x80 if total < 0 else 0
    absolute = abs(total)
    if absolute < 8:
        return sign | absolute

    leading = absolute.bit_length() - 1
    exponent = leading - 2
    shift = exponent - 1
    significand = absolute >> shift
    if shift > 0:
        remainder = absolute - (significand << shift)
        halfway = 1 << (shift - 1)
        if remainder > halfway or (remainder == halfway and (significand & 1)):
            significand += 1
    if significand == 16:
        significand = 8
        exponent += 1
    if (exponent << 4) + significand > 254:
        return sign | 0x7E
    return sign | (exponent << 3) | (significand & 0x7)


def fp8_e4m3fn_mul_word(value: int) -> int:
    a = (value >> 8) & 0xFF
    b = value & 0xFF
    if (a & 0x7F) == 0x7F or (b & 0x7F) == 0x7F:
        return 0x7F

    def magnitude(v: int) -> int:
        exponent = (v >> 3) & 0xF
        fraction = v & 0x7
        return fraction if exponent == 0 else (8 + fraction) << (exponent - 1)

    product = magnitude(a) * magnitude(b)
    sign = 0x80 if bool(a & 0x80) != bool(b & 0x80) else 0
    if product == 0:
        return sign

    leading = product.bit_length() - 1
    if leading < 12:
        exponent = 0
        shift = 9
    else:
        exponent = leading - 11
        shift = leading - 3
    significand = product >> shift
    remainder = product - (significand << shift)
    halfway = 1 << (shift - 1)
    if remainder > halfway or (remainder == halfway and (significand & 1)):
        significand += 1

    if leading < 12:
        return sign | (significand & 0x7F)
    if significand == 16:
        significand = 8
        exponent += 1
    if (exponent << 4) + significand > 254:
        return sign | 0x7E
    return sign | (exponent << 3) | (significand & 0x7)


def fp8_e4m3fn_div_word(value: int) -> int:
    denominator = (value >> 8) & 0xFF
    numerator = value & 0xFF
    if (denominator & 0x7F) == 0x7F or (numerator & 0x7F) == 0x7F:
        return 0x7F

    def magnitude(v: int) -> int:
        exponent = (v >> 3) & 0xF
        fraction = v & 0x7
        return fraction if exponent == 0 else (8 + fraction) << (exponent - 1)

    md = magnitude(denominator)
    mn = magnitude(numerator)
    sign = 0x80 if bool(denominator & 0x80) != bool(numerator & 0x80) else 0
    if md == 0:
        return 0x7F if mn == 0 else sign | 0x7E
    if mn == 0:
        return sign

    exponent = (mn.bit_length() - 1) - (md.bit_length() - 1)
    scaled_numerator = mn << max(0, -exponent)
    scaled_denominator = md << max(0, exponent)
    if scaled_numerator < scaled_denominator:
        exponent -= 1
    exponent += 7
    subnormal = exponent <= 0

    scaled_numerator = mn
    scaled_denominator = md
    if subnormal:
        scaled_numerator <<= 9
    else:
        scale = 10 - exponent
        if scale >= 0:
            scaled_numerator <<= scale
        else:
            scaled_denominator <<= -scale

    quotient, remainder = divmod(scaled_numerator, scaled_denominator)
    doubled_remainder = remainder << 1
    if doubled_remainder > scaled_denominator or (
        doubled_remainder == scaled_denominator and (quotient & 1)
    ):
        quotient += 1
    if subnormal:
        return sign | (quotient & 0x7F)
    if quotient == 16:
        quotient = 8
        exponent += 1
    if (exponent << 4) + quotient > 254:
        return sign | 0x7E
    return sign | (exponent << 3) | (quotient & 0x7)


def fp8_e4m3fn_fmod_word(value: int) -> int:
    denominator = (value >> 8) & 0xFF
    numerator = value & 0xFF
    if (denominator & 0x7F) == 0x7F or (numerator & 0x7F) == 0x7F:
        return 0x7F

    def magnitude(v: int) -> int:
        exponent = (v >> 3) & 0xF
        fraction = v & 0x7
        return fraction if exponent == 0 else (8 + fraction) << (exponent - 1)

    md = magnitude(denominator)
    mn = magnitude(numerator)
    if md == 0:
        return 0x7F
    remainder_value = mn % md
    sign = numerator & 0x80
    if remainder_value < 8:
        return sign | remainder_value

    leading = remainder_value.bit_length() - 1
    exponent = leading - 2
    shift = exponent - 1
    quotient = remainder_value >> shift
    if shift > 0:
        discarded = remainder_value - (quotient << shift)
        halfway = 1 << (shift - 1)
        if discarded > halfway or (discarded == halfway and (quotient & 1)):
            quotient += 1
    if quotient == 16:
        quotient = 8
        exponent += 1
    return sign | (exponent << 3) | (quotient & 0x7)


def fp8_e4m3fn_hypot_word(value: int) -> int:
    a = (value >> 8) & 0xFF
    b = value & 0xFF
    if (a & 0x7F) == 0x7F or (b & 0x7F) == 0x7F:
        return 0x7F

    def magnitude(v: int) -> int:
        exponent = (v >> 3) & 0xF
        fraction = v & 0x7
        return fraction if exponent == 0 else (8 + fraction) << (exponent - 1)

    sum_square = magnitude(a) ** 2 + magnitude(b) ** 2
    root = math.isqrt(sum_square)
    if root < 8:
        exponent = 0
        shift = 0
        quotient = root
    else:
        leading = root.bit_length() - 1
        exponent = leading - 2
        shift = exponent - 1
        quotient = root >> shift

    lower = quotient << shift
    upper = (quotient + 1) << shift
    midpoint_square = (lower + upper) ** 2
    four_sum_square = sum_square << 2
    if four_sum_square > midpoint_square or (
        four_sum_square == midpoint_square and (quotient & 1)
    ):
        quotient += 1
    if exponent == 0:
        return quotient & 0xFF
    if quotient == 16:
        quotient = 8
        exponent += 1
    if (exponent << 4) + quotient > 254:
        return 0x7E
    return (exponent << 3) | (quotient & 0x7)


def fp8_e5m2_add_word(value: int) -> int:
    a = (value >> 8) & 0xFF
    b = value & 0xFF
    if (a & 0x7F) == 0x7F or (b & 0x7F) == 0x7F:
        return 0x7F

    def magnitude(v: int) -> int:
        exponent = (v >> 2) & 0x1F
        fraction = v & 0x3
        return fraction if exponent == 0 else (4 + fraction) << (exponent - 1)

    va = -magnitude(a) if a & 0x80 else magnitude(a)
    vb = -magnitude(b) if b & 0x80 else magnitude(b)
    total = va + vb
    if total == 0:
        return 0x80 if value == 0x8080 else 0

    sign = 0x80 if total < 0 else 0
    absolute = abs(total)
    if absolute < 4:
        return sign | absolute
    leading = absolute.bit_length() - 1
    exponent = leading - 1
    shift = exponent - 1
    significand = absolute >> shift
    if shift > 0:
        remainder = absolute - (significand << shift)
        halfway = 1 << (shift - 1)
        if remainder > halfway or (remainder == halfway and (significand & 1)):
            significand += 1
    if significand == 8:
        significand = 4
        exponent += 1
    if (exponent << 3) + significand > 254:
        return sign | 0x7E
    return sign | (exponent << 2) | (significand & 0x3)


def fp8_e5m2_mul_word(value: int) -> int:
    a = (value >> 8) & 0xFF
    b = value & 0xFF
    if (a & 0x7F) == 0x7F or (b & 0x7F) == 0x7F:
        return 0x7F

    def magnitude(v: int) -> int:
        exponent = (v >> 2) & 0x1F
        fraction = v & 0x3
        return fraction if exponent == 0 else (4 + fraction) << (exponent - 1)

    product = magnitude(a) * magnitude(b)
    sign = 0x80 if bool(a & 0x80) != bool(b & 0x80) else 0
    if product == 0:
        return sign
    leading = product.bit_length() - 1
    if leading < 18:
        exponent = 0
        shift = 16
    else:
        exponent = leading - 17
        shift = leading - 2
    significand = product >> shift
    discarded = product - (significand << shift)
    halfway = 1 << (shift - 1)
    if discarded > halfway or (discarded == halfway and (significand & 1)):
        significand += 1
    if leading < 18:
        return sign | (significand & 0x7F)
    if significand == 8:
        significand = 4
        exponent += 1
    if (exponent << 3) + significand > 254:
        return sign | 0x7E
    return sign | (exponent << 2) | (significand & 0x3)


def fp8_e5m2_div_word(value: int) -> int:
    denominator = (value >> 8) & 0xFF
    numerator = value & 0xFF
    if (denominator & 0x7F) == 0x7F or (numerator & 0x7F) == 0x7F:
        return 0x7F

    def magnitude(v: int) -> int:
        exponent = (v >> 2) & 0x1F
        fraction = v & 0x3
        return fraction if exponent == 0 else (4 + fraction) << (exponent - 1)

    md = magnitude(denominator)
    mn = magnitude(numerator)
    sign = 0x80 if bool(denominator & 0x80) != bool(numerator & 0x80) else 0
    if md == 0:
        return 0x7F if mn == 0 else sign | 0x7E
    if mn == 0:
        return sign

    exponent = (mn.bit_length() - 1) - (md.bit_length() - 1)
    scaled_numerator = mn << max(0, -exponent)
    scaled_denominator = md << max(0, exponent)
    if scaled_numerator < scaled_denominator:
        exponent -= 1
    exponent += 15
    subnormal = exponent <= 0

    scaled_numerator = mn
    scaled_denominator = md
    if subnormal:
        scaled_numerator <<= 16
    else:
        scale = 17 - exponent
        if scale >= 0:
            scaled_numerator <<= scale
        else:
            scaled_denominator <<= -scale

    quotient, remainder = divmod(scaled_numerator, scaled_denominator)
    doubled_remainder = remainder << 1
    if doubled_remainder > scaled_denominator or (
        doubled_remainder == scaled_denominator and (quotient & 1)
    ):
        quotient += 1
    if subnormal:
        return sign | (quotient & 0x7F)
    if quotient == 8:
        quotient = 4
        exponent += 1
    if (exponent << 3) + quotient > 254:
        return sign | 0x7E
    return sign | (exponent << 2) | (quotient & 0x3)


def fp8_e5m2_fmod_word(value: int) -> int:
    divisor = (value >> 8) & 0xFF
    numerator = value & 0xFF
    if (divisor & 0x7F) == 0x7F or (numerator & 0x7F) == 0x7F:
        return 0x7F

    def magnitude(v: int) -> int:
        exponent = (v >> 2) & 0x1F
        fraction = v & 0x3
        return fraction if exponent == 0 else (4 + fraction) << (exponent - 1)

    divisor_mag = magnitude(divisor)
    if divisor_mag == 0:
        return 0x7F
    remainder_value = magnitude(numerator) % divisor_mag
    sign = numerator & 0x80
    if remainder_value < 4:
        return sign | remainder_value

    leading = remainder_value.bit_length() - 1
    exponent = leading - 1
    shift = exponent - 1
    quotient = remainder_value >> shift
    if shift > 0:
        discarded = remainder_value - (quotient << shift)
        halfway = 1 << (shift - 1)
        if discarded > halfway or (discarded == halfway and (quotient & 1)):
            quotient += 1
    if quotient == 8:
        quotient = 4
        exponent += 1
    if (exponent << 3) + quotient > 254:
        return sign | 0x7E
    return sign | (exponent << 2) | (quotient & 0x3)


def fp8_e5m2_hypot_word(value: int) -> int:
    a = (value >> 8) & 0xFF
    b = value & 0xFF
    if (a & 0x7F) == 0x7F or (b & 0x7F) == 0x7F:
        return 0x7F

    def magnitude(v: int) -> int:
        exponent = (v >> 2) & 0x1F
        fraction = v & 0x3
        return fraction if exponent == 0 else (4 + fraction) << (exponent - 1)

    sum_square = magnitude(a) ** 2 + magnitude(b) ** 2
    root = math.isqrt(sum_square)
    if root < 4:
        exponent = 0
        shift = 0
        quotient = root
    else:
        leading = root.bit_length() - 1
        exponent = leading - 1
        shift = exponent - 1
        quotient = root >> shift

    lower = quotient << shift
    upper = (quotient + 1) << shift
    midpoint_square = (lower + upper) ** 2
    four_sum_square = sum_square << 2
    if four_sum_square > midpoint_square or (
        four_sum_square == midpoint_square and (quotient & 1)
    ):
        quotient += 1
    if exponent == 0:
        return quotient & 0xFF
    if quotient == 8:
        quotient = 4
        exponent += 1
    if (exponent << 3) + quotient > 254:
        return 0x7E
    return (exponent << 2) | (quotient & 0x3)


def fp4_e2m1_dot2_word(value: int) -> int:
    def decode_fp4(v: int) -> int:
        exponent = (v >> 1) & 0x3
        magnitude = (v & 1) if exponent == 0 else (2 + (v & 1)) << (exponent - 1)
        return -magnitude if v & 0x8 else magnitude

    a0 = decode_fp4((value >> 8) & 0xF)
    a1 = decode_fp4((value >> 12) & 0xF)
    b0 = decode_fp4(value & 0xF)
    b1 = decode_fp4((value >> 4) & 0xF)
    product0 = a0 * b0
    product1 = a1 * b1
    total = product0 + product1
    if total == 0:
        negative_zero = (
            product0 == 0
            and bool((value >> 11) & 1) != bool((value >> 3) & 1)
            and product1 == 0
            and bool((value >> 15) & 1) != bool((value >> 7) & 1)
        )
        return 0x80 if negative_zero else 0

    absolute = abs(total)
    scaled = absolute << 7
    leading = scaled.bit_length() - 1
    exponent = leading - 2
    shift = exponent - 1
    significand = scaled >> shift
    discarded = scaled - (significand << shift)
    halfway = 1 << (shift - 1)
    if discarded > halfway or (discarded == halfway and (significand & 1)):
        significand += 1
    if significand == 16:
        significand = 8
        exponent += 1
    sign = 0x80 if total < 0 else 0
    return sign | (exponent << 3) | (significand & 0x7)


def signed_magnitude_q21_dot2_word(value: int) -> int:
    def decode_q21(v: int) -> int:
        magnitude = v & 0x7
        return -magnitude if v & 0x8 else magnitude

    a0 = decode_q21((value >> 8) & 0xF)
    a1 = decode_q21((value >> 12) & 0xF)
    b0 = decode_q21(value & 0xF)
    b1 = decode_q21((value >> 4) & 0xF)
    product0 = a0 * b0
    product1 = a1 * b1
    total = product0 + product1
    if total == 0:
        negative_zero = (
            product0 == 0
            and bool((value >> 11) & 1) != bool((value >> 3) & 1)
            and product1 == 0
            and bool((value >> 15) & 1) != bool((value >> 7) & 1)
        )
        return 0x80 if negative_zero else 0

    scaled = abs(total) << 7
    leading = scaled.bit_length() - 1
    exponent = leading - 2
    shift = exponent - 1
    significand = scaled >> shift
    discarded = scaled - (significand << shift)
    halfway = 1 << (shift - 1)
    if discarded > halfway or (discarded == halfway and (significand & 1)):
        significand += 1
    if significand == 16:
        significand = 8
        exponent += 1
    sign = 0x80 if total < 0 else 0
    return sign | (exponent << 3) | (significand & 0x7)


def unsigned_q11_dot4_word(value: int) -> int:
    total = sum(
        ((value >> (8 + 2 * lane)) & 0x3) * ((value >> (2 * lane)) & 0x3)
        for lane in range(4)
    )
    if total == 0:
        return 0
    scaled = total << 7
    leading = scaled.bit_length() - 1
    exponent = leading - 2
    shift = exponent - 1
    significand = scaled >> shift
    discarded = scaled - (significand << shift)
    halfway = 1 << (shift - 1)
    if discarded > halfway or (discarded == halfway and (significand & 1)):
        significand += 1
    if significand == 16:
        significand = 8
        exponent += 1
    return (exponent << 3) | (significand & 0x7)


def unsigned_q11_sum8_word(value: int) -> int:
    total = sum((value >> (2 * lane)) & 0x3 for lane in range(8))
    if total == 0:
        return 0
    scaled = total << 8
    leading = scaled.bit_length() - 1
    exponent = leading - 2
    shift = exponent - 1
    significand = scaled >> shift
    discarded = scaled - (significand << shift)
    halfway = 1 << (shift - 1)
    if discarded > halfway or (discarded == halfway and (significand & 1)):
        significand += 1
    if significand == 16:
        significand = 8
        exponent += 1
    return (exponent << 3) | (significand & 0x7)


def fp4_e2m1_fma_fp8_word(value: int) -> int:
    accumulator_bits = (value >> 8) & 0xFF
    a_bits = value & 0xF
    b_bits = (value >> 4) & 0xF
    if (accumulator_bits & 0x7F) == 0x7F:
        return 0x7F

    def decode_fp8(v: int) -> int:
        exponent = (v >> 3) & 0xF
        magnitude = (v & 0x7) if exponent == 0 else (8 + (v & 0x7)) << (exponent - 1)
        return -magnitude if v & 0x80 else magnitude

    def decode_fp4(v: int) -> int:
        exponent = (v >> 1) & 0x3
        magnitude = (v & 1) if exponent == 0 else (2 + (v & 1)) << (exponent - 1)
        return -magnitude if v & 0x8 else magnitude

    product = decode_fp4(a_bits) * decode_fp4(b_bits)
    total = decode_fp8(accumulator_bits) + (product << 7)
    if total == 0:
        negative_zero = (
            (accumulator_bits & 0x7F) == 0
            and bool(accumulator_bits & 0x80)
            and product == 0
            and bool(a_bits & 0x8) != bool(b_bits & 0x8)
        )
        return 0x80 if negative_zero else 0

    absolute = abs(total)
    if absolute < 8:
        magnitude_bits = absolute
    else:
        leading = absolute.bit_length() - 1
        exponent = leading - 2
        shift = exponent - 1
        significand = absolute >> shift
        if shift > 0:
            discarded = absolute - (significand << shift)
            halfway = 1 << (shift - 1)
            if discarded > halfway or (discarded == halfway and (significand & 1)):
                significand += 1
        if significand == 16:
            significand = 8
            exponent += 1
        magnitude_bits = (
            0x7E
            if (exponent << 4) + significand > 254
            else (exponent << 3) | (significand & 0x7)
        )
    return (0x80 if total < 0 else 0) | magnitude_bits


def describe_basic(n_in: int, n_out: int, words: Sequence[int]) -> Optional[Description]:
    if all(word == words[0] for word in words):
        return Description("constant", f"constant {n_out}'h{words[0]:x}")
    if n_in % 2 == 0:
        half = n_in // 2
        out_mask = mask(n_out)
        if all((((x & mask(half)) * ((x >> half) & mask(half))) & out_mask) == words[x] for x in range(1 << n_in)):
            return Description("integer arithmetic", f"unsigned {half}x{half} multiply")
        if all(
            (
                signed_value(x & mask(half), half)
                * signed_value((x >> half) & mask(half), half)
                & out_mask
            )
            == words[x]
            for x in range(1 << n_in)
        ):
            return Description("integer arithmetic", f"signed {half}x{half} multiply")
        if all(
            (
                mask(n_out)
                if ((x >> half) & mask(half)) == 0
                else ((x & mask(half)) // ((x >> half) & mask(half))) & out_mask
            )
            == words[x]
            for x in range(1 << n_in)
        ):
            return Description("integer arithmetic", f"unsigned {half}-bit divide, divide-by-zero saturates to all ones")
    out_mask = mask(n_out)
    if all(((x * x) & out_mask) == words[x] for x in range(1 << n_in)):
        return Description("integer arithmetic", "unsigned square")
    if all((math.isqrt(x) & out_mask) == words[x] for x in range(1 << n_in)):
        return Description("integer arithmetic", "integer square root")
    if all((x.bit_count() & out_mask) == words[x] for x in range(1 << n_in)):
        return Description("bit counting", "population count")
    if n_in == 16 and n_out == 8 and all(fp4_e2m1_dot2_word(x) == words[x] for x in range(1 << n_in)):
        return Description(
            "floating-point dot product",
            "two-lane packed FP4 E2M1 dot product to FP8 E4M3, fused exact sum, RNE",
        )
    if n_in == 16 and n_out == 8 and all(
        signed_magnitude_q21_dot2_word(x) == words[x] for x in range(1 << n_in)
    ):
        return Description(
            "fixed-point dot product",
            "two-lane packed signed-magnitude Q2.1 dot product to FP8 E4M3, fused exact sum, RNE",
        )
    if n_in == 16 and n_out == 8 and all(unsigned_q11_dot4_word(x) == words[x] for x in range(1 << n_in)):
        return Description(
            "fixed-point dot product",
            "four-lane packed unsigned Q1.1 dot product to FP8 E4M3, fused exact sum, RNE",
        )
    if n_in == 16 and n_out == 8 and all(unsigned_q11_sum8_word(x) == words[x] for x in range(1 << n_in)):
        return Description(
            "fixed-point reduction",
            "eight-lane packed unsigned Q1.1 sum to FP8 E4M3, exact reduction, RNE",
        )
    if n_in == 16 and n_out == 8 and all(fp4_e2m1_fma_fp8_word(x) == words[x] for x in range(1 << n_in)):
        return Description(
            "floating-point fused multiply-add",
            "FP8 E4M3 accumulator plus packed FP4 E2M1 product, exact fused sum, RNE",
        )
    if n_in == 16 and n_out == 8 and all(fp8_e4m3fn_add_word(x) == words[x] for x in range(1 << n_in)):
        return Description(
            "floating-point binary",
            "FP8 E4M3FN add, RNE, canonical NaN 8'h7f, finite saturation, signed-zero preservation",
        )
    if n_in == 16 and n_out == 8 and all(fp8_e4m3fn_mul_word(x) == words[x] for x in range(1 << n_in)):
        return Description(
            "floating-point binary",
            "FP8 E4M3FN multiply, RNE, canonical NaN 8'h7f, finite saturation, signed zero",
        )
    if n_in == 16 and n_out == 8 and all(fp8_e4m3fn_div_word(x) == words[x] for x in range(1 << n_in)):
        return Description(
            "floating-point binary",
            "FP8 E4M3FN divide x[7:0]/x[15:8], RNE, canonical NaN, finite saturation",
        )
    if n_in == 16 and n_out == 8 and all(fp8_e4m3fn_fmod_word(x) == words[x] for x in range(1 << n_in)):
        return Description(
            "floating-point binary",
            "FP8 E4M3FN fmod(x[7:0], x[15:8]), trunc-toward-zero quotient, RNE",
        )
    if n_in == 16 and n_out == 8 and all(fp8_e4m3fn_hypot_word(x) == words[x] for x in range(1 << n_in)):
        return Description(
            "floating-point binary",
            "FP8 E4M3FN hypot, sign-insensitive, exact squared-midpoint RNE, canonical NaN",
        )
    if n_in == 16 and n_out == 8 and all(fp8_e5m2_add_word(x) == words[x] for x in range(1 << n_in)):
        return Description(
            "floating-point binary",
            "FP8 E5M2 add, RNE, canonical NaN 8'h7f, finite saturation, signed-zero preservation",
        )
    if n_in == 16 and n_out == 8 and all(fp8_e5m2_mul_word(x) == words[x] for x in range(1 << n_in)):
        return Description(
            "floating-point binary",
            "FP8 E5M2 multiply, RNE, canonical NaN 8'h7f, finite saturation, signed zero",
        )
    if n_in == 16 and n_out == 8 and all(fp8_e5m2_div_word(x) == words[x] for x in range(1 << n_in)):
        return Description(
            "floating-point binary",
            "FP8 E5M2 divide x[7:0]/x[15:8], RNE, canonical NaN, finite saturation",
        )
    if n_in == 16 and n_out == 8 and all(fp8_e5m2_fmod_word(x) == words[x] for x in range(1 << n_in)):
        return Description(
            "floating-point binary",
            "FP8 E5M2 fmod(x[7:0], x[15:8]), trunc-toward-zero quotient, RNE",
        )
    if n_in == 16 and n_out == 8 and all(fp8_e5m2_hypot_word(x) == words[x] for x in range(1 << n_in)):
        return Description(
            "floating-point binary",
            "FP8 E5M2 hypot, sign-insensitive, exact squared-midpoint RNE, canonical NaN",
        )
    return None


def _load_libm():
    try:
        libm = ctypes.CDLL("libm.so.6")
    except OSError:
        return None
    for fn in [
        "expf",
        "exp2f",
        "log10f",
        "log2f",
        "logf",
        "sinf",
        "cosf",
        "tanf",
        "sinhf",
        "coshf",
        "tanhf",
        "sqrtf",
        "cbrtf",
    ]:
        if hasattr(libm, fn):
            getattr(libm, fn).restype = ctypes.c_float
            getattr(libm, fn).argtypes = [ctypes.c_float]
    libm.powf.restype = ctypes.c_float
    libm.powf.argtypes = [ctypes.c_float, ctypes.c_float]
    return libm


LIBM = _load_libm()


UNARY_OPS = [
    ("exp", "exp(x)"),
    ("exp2", "2^x"),
    ("pow10", "10^x"),
    ("log", "ln(x)"),
    ("log2", "log2(x)"),
    ("log10", "log10(x)"),
    ("sin", "sin(x)"),
    ("tan", "tan(x)"),
    ("sinh", "sinh(x)"),
    ("tanh", "tanh(x)"),
    ("sigmoid", "1/(1+exp(-x))"),
    ("sigmoid_f32exp", "1/(1+exp(-x))"),
    ("recip", "1/x"),
    ("square", "x^2"),
    ("sqrt", "sqrt(x)"),
    ("recip_sq", "1/x^2"),
    ("rsqrt", "1/sqrt(x)"),
    ("cube", "x^3"),
    ("cbrt", "cbrt(x)"),
    ("recip_cube", "1/x^3"),
    ("rcbrt", "1/cbrt(x)"),
]


def _f32_op(value: float, op_name: str) -> float:
    if LIBM is None:
        return float("nan")
    try:
        if op_name == "recip":
            return 1.0 / value if value != 0 else math.copysign(float("inf"), value)
        if op_name == "sqrt":
            return float(LIBM.sqrtf(ctypes.c_float(value)))
        if op_name == "rsqrt":
            root = float(LIBM.sqrtf(ctypes.c_float(value)))
            return 1.0 / root if root != 0 else math.copysign(float("inf"), root)
        if op_name == "cbrt":
            return float(LIBM.cbrtf(ctypes.c_float(value)))
        if op_name == "rcbrt":
            root = float(LIBM.cbrtf(ctypes.c_float(value)))
            return 1.0 / root if root != 0 else math.copysign(float("inf"), root)
        if op_name == "square":
            return float(ctypes.c_float(value * value).value)
        if op_name == "cube":
            return float(ctypes.c_float(value * value * value).value)
        if op_name == "recip_sq":
            square = float(ctypes.c_float(value * value).value)
            return 1.0 / square if square != 0 else float("inf")
        if op_name == "recip_cube":
            cube = float(ctypes.c_float(value * value * value).value)
            return 1.0 / cube if cube != 0 else math.copysign(float("inf"), cube)
        if op_name == "exp":
            return float(LIBM.expf(ctypes.c_float(value)))
        if op_name == "exp2":
            return float(LIBM.exp2f(ctypes.c_float(value)))
        if op_name == "pow10":
            return float(LIBM.powf(ctypes.c_float(10.0), ctypes.c_float(value)))
        if op_name == "log":
            return float(LIBM.logf(ctypes.c_float(value)))
        if op_name == "log2":
            return float(LIBM.log2f(ctypes.c_float(value)))
        if op_name == "log10":
            return float(LIBM.log10f(ctypes.c_float(value)))
        if op_name == "sin":
            return float(LIBM.sinf(ctypes.c_float(value)))
        if op_name == "tan":
            return float(LIBM.tanf(ctypes.c_float(value)))
        if op_name == "sinh":
            return float(LIBM.sinhf(ctypes.c_float(value)))
        if op_name == "tanh":
            return float(LIBM.tanhf(ctypes.c_float(value)))
        if op_name == "sigmoid":
            return 1.0 / (1.0 + float(LIBM.expf(ctypes.c_float(-value))))
        if op_name == "sigmoid_f32exp" and np is not None:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                expv = np.float32(LIBM.expf(ctypes.c_float(-value)))
                return float(np.float32(1.0) / (np.float32(1.0) + expv))
    except (ValueError, OverflowError, ZeroDivisionError):
        return float("nan")
    return float("nan")


def bf16_to_f32(bits: int) -> float:
    return struct.unpack("f", struct.pack("I", (bits & 0xFFFF) << 16))[0]


def f32_to_bf16_bits(value: float) -> int:
    packed = struct.pack("f", ctypes.c_float(value).value)
    raw = struct.unpack("I", packed)[0]
    lower = raw & 0xFFFF
    upper = (raw >> 16) & 0xFFFF
    round_bit = (lower >> 15) & 1
    sticky = lower & 0x7FFF
    if round_bit and (sticky or (upper & 1)):
        upper = (upper + 1) & 0xFFFF
    exp = (upper >> 7) & 0xFF
    mant = upper & 0x7F
    sign = (upper >> 15) & 1
    if exp == 0 and mant != 0:
        upper = sign << 15
    if exp == 0xFF and mant != 0:
        upper = 0x7FC0
    return upper


@lru_cache(maxsize=None)
def bf16_model(op_name: str) -> tuple[int, ...]:
    result: List[int] = []
    for bits in range(1 << 16):
        sign = (bits >> 15) & 1
        exp = (bits >> 7) & 0xFF
        mant = bits & 0x7F
        is_subnorm = exp == 0 and mant != 0
        is_nan = exp == 0xFF and mant != 0
        value_bits = (sign << 15) if is_subnorm else bits
        value = bf16_to_f32(value_bits)
        out = f32_to_bf16_bits(_f32_op(value, op_name))
        if is_nan:
            out = 0x7FC0
        result.append(out)
    return tuple(result)


def half_bits_to_f32(bits: int) -> float:
    if np is None:
        return float("nan")
    arr = np.array([bits & 0xFFFF], dtype=np.uint16).view(np.float16)
    return float(np.float32(arr[0]))


def f32_to_half_bits(value: float) -> int:
    if np is None:
        return 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        half = np.float16(np.float32(value))
    bits = int(np.array([half], dtype=np.float16).view(np.uint16)[0])
    exp = (bits >> 10) & 0x1F
    mant = bits & 0x3FF
    sign = (bits >> 15) & 1
    if exp == 0 and mant != 0:
        bits = sign << 15
    if exp == 0x1F and mant != 0:
        bits = 0x7E00
    return bits


@lru_cache(maxsize=None)
def fp16_model(op_name: str) -> Optional[tuple[int, ...]]:
    if np is None:
        return None
    result: List[int] = []
    for bits in range(1 << 16):
        sign = (bits >> 15) & 1
        exp = (bits >> 10) & 0x1F
        mant = bits & 0x3FF
        is_subnorm = exp == 0 and mant != 0
        is_nan = exp == 0x1F and mant != 0
        value_bits = (sign << 15) if is_subnorm else bits
        value = half_bits_to_f32(value_bits)
        out = f32_to_half_bits(_f32_op(value, op_name))
        if is_nan:
            out = 0x7E00
        result.append(out)
    return tuple(result)


def describe_float_unary(n_in: int, n_out: int, words: Sequence[int]) -> Optional[Description]:
    if n_in != 16 or n_out != 16 or LIBM is None:
        return None
    target = tuple(words)
    for op_name, label in UNARY_OPS:
        model = bf16_model(op_name)
        if model == target:
            return Description(
                "floating-point unary",
                f"BF16 {label}, DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0",
            )
        fp16 = fp16_model(op_name)
        if fp16 == target:
            return Description(
                "floating-point unary",
                f"FP16 {label}, DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00",
            )
    return None


def describe_truth(n_in: int, n_out: int, words: Sequence[int]) -> Optional[Description]:
    for describer in (describe_basic, describe_float_unary):
        desc = describer(n_in, n_out, words)
        if desc is not None:
            return desc
    return None
