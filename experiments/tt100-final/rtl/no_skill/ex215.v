module top(input [15:0] x, output [15:0] y);
  reg [15:0] result;
  reg [7:0] exponent;
  reg [8:0] significand;
  reg sign;
  reg [7:0] input_exponent;
  reg [6:0] fraction;
  reg even_power;

  // Correctly rounded significand of the reciprocal square root.
  function [8:0] root_significand;
    input [7:0] a;
    input even_power;
    integer i;
    reg [31:0] k;
    reg [31:0] quotient;
    reg [9:0] r;
    begin
      // floor(sqrt(4*k/a)) carries the half-unit rounding bit.
      k = even_power ? 32'd33554432 : 32'd16777216;
      quotient = k / a;
      r = 10'd512;
      for (i = 0; i < 4; i = i + 1)
        r = (r + quotient / r) >> 1;
      root_significand = (r + 1) >> 1;
    end
  endfunction

  always @(x) begin
    sign = x[15];
    input_exponent = x[14:7];
    fraction = x[6:0];
    even_power = x[7];
    result = 16'h7fc0;
    exponent = 0;
    significand = 0;
    if (input_exponent) begin
      if (sign)
        result = 16'h7fc0;
      else if (input_exponent == 8'hff)
        result = fraction ? 16'h7fc0 : 16'h0000;
      else begin
        exponent = ((9'd381 - input_exponent) >> 1)
                   - (even_power && fraction);
        significand = root_significand(8'd128 + fraction, even_power);
        result = 0;
        result[14:7] = exponent;
        result[6:0] = significand;
      end
    end else begin
      result = 16'h7f80;
      result[15] = sign;
    end
  end

  assign y = result;
endmodule
