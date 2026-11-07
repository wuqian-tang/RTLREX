module top(input [15:0] x, output [15:0] y);
  // bfloat16 reciprocal: flush denormals, preserve signed zero/infinity,
  // canonicalize NaNs, and round the seven-bit significand to nearest.
  assign y = {
    (x[14:7] == 8'd0) ? {x[15], 8'hff, 7'b0} :
    (x[14:7] == 8'd255) ? (x[6:0] ? 16'h7fc0 : {x[15], 15'b0}) :
    (x[14:7] + (|x[6:0]) >= 8'd254) ? {x[15], 15'b0} :
    {x[15], 15'b0} +
      ((16'd254 - x[14:7] - (|x[6:0])) << 7) +
      (((16'd32832 + (x[6:0] >> 1)) / (16'd128 + x[6:0])) % 16'd128)
  };
endmodule
