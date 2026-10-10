"""Exact finite FP8 arithmetic with a shared normalized integer encoder.

These are parameterized arithmetic circuits, not truth-derived lookup tables.
Caller recognition and complete-domain checking establish the format contract.
"""


def emit_finite_fp8(operation: str, exponent_bits: int, fraction_bits: int,
                    detail: str) -> str:
    if (type(exponent_bits) is not int or type(fraction_bits) is not int
            or exponent_bits + fraction_bits != 7 or exponent_bits < 2
            or fraction_bits < 1):
        raise ValueError('finite FP8 needs seven magnitude bits')
    if operation not in ('add', 'multiply', 'divide', 'fmod', 'hypot'):
        raise ValueError('unsupported compact finite FP8 operation')
    e, f = exponent_bits, fraction_bits
    width = ((1 << e) - 2) + f + 1
    scale = (1 << (e - 1)) - 1 + f - 1
    value_width = 2 * width if operation == 'multiply' else width + 2
    quantization_scale = scale if operation == 'multiply' else 0
    if operation == 'hypot':
        return _hypot_header(e, f, width, detail) + _hypot_body(width) + 'endmodule\n'
    header = f'''// {detail}
// Word arithmetic; normalized integer encoding with exact ties-to-even rounding.
module top(input [15:0] x, output reg [7:0] y);
  wire [6:0] a = x[14:8], b = x[6:0];
  function [{width-1}:0] magnitude;
    input [6:0] v;
    reg [{e-1}:0] exponent;
    reg [{f-1}:0] fraction;
    reg normal;
    begin
      exponent = v[6:{f}];
      fraction = v;
      normal = exponent != 0;
      magnitude = {{normal, fraction}} << (exponent - normal);
    end
  endfunction
  wire [{width-1}:0] ma = magnitude(a), mb = magnitude(b);
'''
    if operation == 'add':
        signed_decoder = f"""  function signed [{width+1}:0] signed_value;
    input [6:0] v;
    input sign;
    reg [{e-1}:0] exponent;
    reg [{f-1}:0] fraction;
    reg normal;
    reg [{width+1}:0] value;
    begin
      exponent = v[6:{f}];
      fraction = v;
      normal = exponent != 0;
      value = {{normal, fraction}} << (exponent - normal);
      signed_value = sign ? -$signed(value) : $signed(value);
    end
  endfunction
"""
        header = header[:header.index('  function')] + signed_decoder
    if operation == 'divide':
        return header + _divide_body(width, scale) + 'endmodule\n'
    if quantization_scale == 0:
        shift_formula = f"""      shift = 0;
      for (j = {f+1}; j < {value_width}; j = j + 1)
        if (value[j]) shift = j - {f};
      exponent = shift;
"""
    else:
        shift_formula = f"""      shift = {quantization_scale};
      for (j = {quantization_scale+f+1}; j < {value_width}; j = j + 1)
        if (value[j]) shift = j - {f};
      exponent = shift - {quantization_scale};
"""
    encoder = f'''  function [6:0] encode;
    input [{value_width-1}:0] value;
    reg [{value_width}:0] rounded;
    integer j, shift, exponent, code;
    begin
{shift_formula.rstrip()}
      rounded = (value + (({value_width+1}'d1 << shift) >> 1) -
                 (shift && !value[shift])) >> shift;
      code = (exponent << {f}) + rounded;
      encode = code > 126 ? 7'd126 : code;
    end
  endfunction
'''
    if operation == 'add':
        arithmetic = f'''  wire sa = x[15], sb = x[7];
  wire signed [{width+1}:0] total = signed_value(a, sa) + signed_value(b, sb);
  wire negative = total[{width+1}];
  wire [{value_width-1}:0] absolute = negative ? -total : total;
  wire [6:0] result = encode(absolute);
  always @(*) begin
    if ((a == 127) || (b == 127)) y = 8'h7f;
    else y = {{(negative || (sa && sb)), result}};
  end
'''
    elif operation == 'multiply':
        arithmetic = f'''  wire sa = x[15], sb = x[7];
  wire [{value_width-1}:0] product = ma * mb;
  wire [6:0] result = encode(product);
  always @(*) begin
    if ((a == 127) || (b == 127)) y = 8'h7f;
    else y = {{(sa != sb), result}};
  end
'''
    else:
        arithmetic = f'''  wire sb = x[7];
  wire [{value_width-1}:0] remainder = mb % ma;
  wire [6:0] result = encode(remainder);
  always @(*) begin
    if ((a == 127) || (b == 127) || (ma == 0)) y = 8'h7f;
    else y = {{sb, result}};
  end
'''
    return header + encoder + arithmetic + 'endmodule\n'


def _hypot_header(e: int, f: int, width: int, detail: str) -> str:
    """Decode and square either a doubled magnitude or an adjacent midpoint.

    Folding these always-composed arithmetic helpers preserves the full typed
    decoded word and product; source reuse does not imply physical sharing.
    """
    return f'''// {detail}
// Word arithmetic; exact squared dyadic midpoints with ties-to-even rounding.
module top(input [15:0] x, output reg [7:0] y);
  wire [6:0] a = x[14:8], b = x[6:0];
  function [{2*width+1}:0] magnitude_squared;
    input [6:0] v;
    input half_step;
    reg [{e-1}:0] exponent;
    reg [{f-1}:0] fraction;
    reg normal;
    reg [{width}:0] decoded;
    begin
      exponent = v[6:{f}];
      fraction = v;
      normal = exponent != 0;
      decoded = {{normal, fraction, half_step}} << (exponent - normal);
      magnitude_squared = decoded * decoded;
    end
  endfunction
'''


def _hypot_body(width: int) -> str:
    """Binary search RNE midpoint thresholds of finite representable codes.

    Each trial is a numeric FP encoding; its preceding midpoint's squared
    magnitude defines the exact decision boundary. Midpoint equality selects
    the even code. No ROM, case enumeration or input-specific patch occurs.
    The reusable square function shares source syntax, not a physical resource.
    D(v,0)=2*M(v), while D(v,1)=M(v)+M(v+1). For adjacent codes the
    spacing is the preceding code's power of two, even at binade boundaries.
    Thus input squares already have the midpoint comparison's factor of four.
    """
    return f"""  wire [{2*width+2}:0] four_value = magnitude_squared(a, 1'b0) + magnitude_squared(b, 1'b0);
  reg [6:0] lower_code;
  reg [7:0] trial;
  reg [{2*width+1}:0] midpoint_square;
  reg [6:0] weight;
  always @(*) begin
    lower_code = 0;
    trial = 0;
    midpoint_square = 0;
    for (weight = 7'd64; weight; weight = weight >> 1) begin
      trial = lower_code + weight;
      midpoint_square = magnitude_squared(trial - 1'b1, 1'b1);
      if ((trial <= 126) && (four_value >= midpoint_square + trial[0])) lower_code = trial;
    end
    y = lower_code;
    if ((a == 127) || (b == 127)) y = 8'h7f;
  end
"""


def _divide_body(width: int, scale: int) -> str:
    """Round the exact positive quotient against representable midpoints.

    High-byte a is the divisor and low-byte b the dividend. Numeric code
    search uses seven monotone comparisons, not an input table. Zero divisor
    saturates finite nonzero division and the explicit 0/0 guard returns NaN.
    """
    return f"""  wire [{2*width}:0] target = mb << {scale+1};
  reg [6:0] lower_code;
  reg [7:0] trial;
  reg [{width}:0] midpoint;
  reg [{2*width}:0] threshold;
  reg [6:0] weight;
  always @(*) begin
    lower_code = 0;
    trial = 0;
    midpoint = 0;
    threshold = 0;
    for (weight = 7'd64; weight; weight = weight >> 1) begin
      trial = lower_code + weight;
      midpoint = magnitude(trial) + magnitude(trial - 1'b1);
      threshold = midpoint * ma;
      if ((trial <= 126) && (target >= threshold + trial[0])) lower_code = trial;
    end
    y = {{(x[15] != x[7]), lower_code}};
    if ((a == 127) || (b == 127) || ((ma == 0) && (mb == 0))) y = 8'h7f;
  end
"""
