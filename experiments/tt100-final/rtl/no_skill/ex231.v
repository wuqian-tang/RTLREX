module top(input [15:0] x, output [15:0] y);
  // Binary16 reciprocal with denormals-as-zero, flush-to-zero, and
  // canonical NaNs.  2^21/divisor forms the normalized significand;
  // adding divisor/2 rounds it to the nearest binary16 significand.
  assign y = {
    x[14:0] > 15'h7c00 ? 16'h7e00 :
    16'h8000 * x[15] +
    (x[14:0] < 15'h0400 ? 16'h7c00 :
     x[14:0] > 15'h7400 ? 16'b0 :
     (5'd30 - x[14:10] - (x[9:0] ? 1'b1 : 1'b0)) * 16'd1024 +
     ((22'd2097152 + ((11'd1024 + x[9:0]) >> 1)) /
      (11'd1024 + x[9:0])) % 16'd1024)
  };
endmodule
