`define P ((128 + x[6:0]) ** 3)
`define S ((`P >> 23) ? 16 : ((`P >> 22) ? 15 : 14))
`define Z ((3 * x[14:7] + `S - 269) * 128 + (`P >> `S) \
           + ((`P >> (`S - 1)) & 1))

module top(input [15:0] x, output [15:0] y);
  // bfloat16 x^3, RNE; flush underflow, saturate overflow, canonicalize NaN.
  assign y = {&x[14:7] ?
                (|x[6:0] ? 16'h7fc0 : x[15] * 32768 + 16'h7f80) :
              x[14:7] < 85 ? x[15] * 32768 :
              `Z >= 16'h7f80 ? x[15] * 32768 + 16'h7f80 :
                               x[15] * 32768 + `Z};
endmodule
