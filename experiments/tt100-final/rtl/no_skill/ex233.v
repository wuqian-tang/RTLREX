module top(input [15:0] x, output [15:0] y);
  wire [21:0] radicand = (1024 + x[9:0]) << (11-x[10]);
  reg [10:0] significand;
  always @(radicand) begin
    // Integer Newton iteration, biased to round the square root to nearest.
    significand = 2047;
    repeat (4)
      significand = (significand + (radicand-1)/significand + 1) >> 1;
  end
  wire [15:0] exponent_base = (x[14:10] + 13) >> 1;

  assign y = x[14:10] == 0  ? 16'h8000*x[15] :
             x == 16'h7c00 ? x :
             x > 16'h7c00  ? 16'h7e00 :
                              (exponent_base << 10) + significand;
endmodule
