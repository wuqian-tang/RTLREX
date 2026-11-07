// FP8 E4M3 accumulator plus packed FP4 E2M1 product, exact fused sum, RNE
module top(input [15:0] x, output reg [7:0] y);
  wire [6:0] input_field_14_8 = x[14:8];
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
      decode_fp8 = mag;
      if (value[7]) decode_fp8 = -decode_fp8;
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
      decode_fp4 = mag;
      if (value[3]) decode_fp4 = -decode_fp4;
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
        shift = leading - 3;
        significand = value >> shift;
        discarded = value - (significand << shift);
        halfway = 0;
        if (shift > 0) begin
          halfway = 20'b1 << (shift - 1);
          if (discarded + significand[0] > halfway)
            significand = significand + 1;
        end
        if (significand == 16) begin
          significand = 8;
          exponent = exponent + 1;
        end
        if ({exponent, significand} >= 10'b0111101111)
          encode_fp8 = 7'h7e;
        else
          encode_fp8 = {exponent[3:0], significand[2:0]};
      end
    end
  endfunction

  always @* begin
    accumulator = decode_fp8(x[15:8]);
    multiplicand_a = decode_fp4(x[3:0]);
    multiplicand_b = decode_fp4(x[7:4]);
    product = multiplicand_a * multiplicand_b;
    product_scaled = product;
    product_scaled = product_scaled <<< 7;
    fused_sum = accumulator + product_scaled;
    magnitude = fused_sum;
    if (fused_sum[19]) magnitude = -magnitude;
    negative_zero = ((input_field_14_8 == 0) && x[15] &&
                     (product == 0) && (x[3] ^ x[7]));
    if (input_field_14_8 == 7'h7f)
      y = 8'h7f;
    else if (fused_sum == 0)
      begin
        y = 0;
        y[7] = negative_zero;
      end
    else begin
      y = encode_fp8(magnitude);
      y[7] = fused_sum[19];
    end
  end
endmodule
