module top(input [15:0] x, output [7:0] y);
  function [3:0] fp4_lane;
    input [15:0] word;
    input [1:0] lane;
    begin
      fp4_lane = word >> (lane * 4);
    end
  endfunction

  // Decode finite FP4 E2M1 into a signed integer scaled by two.
  function signed [4:0] fp4;
    input [15:0] word;
    input [1:0] lane;
    reg [3:0] a;
    reg signed [4:0] magnitude;
    reg [1:0] exponent;
    reg fraction;
    begin
      a = fp4_lane(word, lane);
      exponent = a[2:1];
      fraction = a[0];
      magnitude = (exponent == 0) ? fraction
                                  : ((2 + fraction) << (exponent - 1'b1));
      fp4 = a[3] ? -magnitude : magnitude;
    end
  endfunction

  wire signed [4:0] a = fp4(x, 0);
  wire signed [4:0] b = fp4(x, 1);
  wire signed [4:0] c = fp4(x, 2);
  wire signed [4:0] d = fp4(x, 3);
  wire signed [9:0] sum = a * c + b * d;
  wire negative = sum < 0;
  wire [9:0] magnitude = negative ? -sum : sum;

  // Encode a nonzero value scaled by four as FP8 E4M3, RNE.
  function [6:0] fp8_magnitude;
    input [9:0] m;
    integer i;
    integer leading;
    reg [9:0] significand;
    reg [12:0] numerator;
    reg [9:0] divisor;
    begin
      leading = 0;
      for (i = 0; i < 10; i = i + 1)
        if (m >> i) leading = i;

      numerator = m << 3;
      divisor = 10'd1 << leading;
      significand = (numerator + (divisor - 1) / 2
                       + (numerator / divisor) % 2) / divisor;
      fp8_magnitude = ((leading + 4) << 3) + significand;
    end
  endfunction

  // IEEE addition preserves -0 only when both zero products are negative.
  function fp4_sign;
    input [15:0] word;
    input [1:0] lane;
    begin
      fp4_sign = fp4_lane(word, lane) >= 8;
    end
  endfunction

  wire negative_zero = (fp4_sign(x, 0) != fp4_sign(x, 2)) &&
                       (fp4_sign(x, 1) != fp4_sign(x, 3));
  assign y = {sum ? negative : negative_zero,
              sum ? fp8_magnitude(magnitude) : 7'b0};
endmodule
