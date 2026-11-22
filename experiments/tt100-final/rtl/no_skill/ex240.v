module top(input [15:0] x, output [7:0] y);
  // x packs two FP8 E4M3 finite-only operands, low operand first.
  wire [7:0] a = x;
  wire [7:0] b = x >> 8;
  wire [6:0] a_payload = a;
  wire [6:0] b_payload = b;

  // Decode exactly into signed integer units of 2^-9.
  function signed [19:0] value;
    input [7:0] v;
    reg [18:0] m;
    reg [3:0] exponent;
    reg [2:0] fraction;
    begin
      exponent = v >> 3;
      fraction = v;
      if (exponent)
        m = (8 + fraction) << (exponent - 1);
      else
        m = fraction;
      if (v[7]) value = -m;
      else value = m;
    end
  endfunction

  // Normalize, round to nearest even, and saturate to the largest finite FP8.
  function [7:0] encode;
    input [18:0] m;
    input sign_bit;
    reg [3:0] shift;
    reg [18:0] rounded;
    reg rounded_lsb;
    integer i;
    begin
      shift = 0;
      for (i = 4; i < 19; i = i + 1)
        if (m[i]) shift = i - 3;
      rounded = m >> shift;
      rounded_lsb = rounded;
      rounded = (m + (((19'd1 << shift) - 1 + rounded_lsb) >> 1))
                >> shift;
      rounded = shift * 8 + rounded;
      if (rounded >= 126) encode = 126;
      else encode = rounded;
      encode[7] = sign_bit;
    end
  endfunction

  wire signed [19:0] total = value(a) + value(b);
  wire negative = total < 0;
  wire [18:0] result_magnitude = negative ? -total : total;
  wire result_sign = negative || x == 16'h8080;
  wire nan = a_payload == 7'h7f || b_payload == 7'h7f;

  assign y = nan ? 8'h7f : encode(result_magnitude, result_sign);
endmodule
