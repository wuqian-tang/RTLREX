// FP16 x^2, DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
// Exact binary square with constant input guard boundaries and fixed RNE scale.
module top(input [15:0] x, output [15:0] y);
  wire [14:0] magnitude = x;
  wire [4:0] exponent = magnitude[14:10];
  wire [9:0] fraction = magnitude;
  wire [10:0] significand = 11'd1024 + fraction;
  wire [21:0] product = significand * significand;
  function greater;
    input [21:0] left, right;
    begin greater = left > right; end
  endfunction
  wire normalize = greater(22'd2097152, product);
  wire [21:0] aligned = product << normalize;
  wire [11:0] rounded = (aligned + 23'd1023) >> 11;
  wire [17:0] packed_result = (exponent * 18'd2 - 18'd15 - normalize) *
      18'd1024 + rounded;
  assign y = greater(magnitude, 22'd31744) ? 16'd32256 :
             greater(22'd23552, magnitude) ?
             (greater(22'd8192, magnitude) ? 16'd0 : packed_result) :
             16'd31744;
endmodule
