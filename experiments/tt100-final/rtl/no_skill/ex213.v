module top(input [15:0] x, output reg [15:0] y);
  reg [9:0] root;

  always @(x) begin
    // Four Newton steps give the scaled significand square root.
    root = 10'd512;
    repeat (4)
      root = {(root + ((18'd128 + x[6:0]) << (10 - x[7])) / root) >> 1};

    // Flush subnormals to signed zero; preserve +infinity; canonicalize NaNs.
    y = {(x[14:7] == 8'b0) ? {x[15], 15'b0} :
         (x < 16'h7f80) ?
           {x[14:8] + 8'd63 + x[7], root[7:1] + root[0]} :
           16'h7fc0 - ((x == 16'h7f80) << 6)};
  end
endmodule
