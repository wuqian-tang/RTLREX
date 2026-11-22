// FP8 E4M3FN divide x[7:0]/x[15:8], RNE, canonical NaN, finite saturation
// Word arithmetic; normalized integer encoding with exact ties-to-even rounding.
module top(input [15:0] x, output reg [7:0] y);
  wire [6:0] a = x[14:8], b = x[6:0];
  function [17:0] magnitude;
    input [6:0] v;
    reg [3:0] exponent;
    reg [2:0] fraction;
    reg normal;
    begin
      exponent = v[6:3];
      fraction = v;
      normal = exponent != 0;
      magnitude = {normal, fraction} << (exponent - normal);
    end
  endfunction
  wire [17:0] ma = magnitude(a), mb = magnitude(b);
  wire [36:0] target = mb << 10;
  reg [6:0] lower_code;
  reg [7:0] trial;
  reg [18:0] midpoint;
  reg [36:0] threshold;
  reg [6:0] weight;
  always @(*) begin
    lower_code = 0;
    trial = 0;
    midpoint = 0;
    threshold = 0;
    for (weight = 7'd64; weight; weight = weight >> 1) begin
      trial = lower_code + weight;
      midpoint = magnitude(trial) + magnitude(trial - 1'b1);
      threshold = midpoint * ma;
      if ((trial <= 126) && (target >= threshold + trial[0])) lower_code = trial;
    end
    y = {(x[15] != x[7]), lower_code};
    if ((a == 127) || (b == 127) || (a + b == 0)) y = 8'h7f;
  end
endmodule
