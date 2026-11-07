module top(input [15:0] x, output [15:0] y);
  wire [7:0] exponent = x[14:7];
  wire [7:0] significand = 8'd128 + x[6:0];
  wire [15:0] square = significand * significand;
  wire normalize = square[15];
  wire [3:0] shift = 4'd7 + normalize;

  // Adding half an ulp minus one plus the retained LSB implements RNE.
  wire [8:0] rounded = (square + (normalize ? 16'd127 : 16'd63)
                        + square[shift]) >> shift;
  wire [15:0] finite_square = exponent * 16'd256 + rounded
                              - (normalize ? 16'd16256 : 16'd16384);

  // Squaring clears the sign. Results that would be subnormal are flushed;
  // overflow becomes infinity, and all input NaNs become the canonical qNaN.
  assign y = (x[14:0] > 15'h7f80)            ? 16'h7fc0 :
             (exponent < 8'd64)              ? 16'h0000 :
             (exponent >= 8'd191)            ? 16'h7f80 :
                                                finite_square;
endmodule
