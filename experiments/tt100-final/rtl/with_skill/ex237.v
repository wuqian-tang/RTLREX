// FP16 cbrt(x), DAZ input, FTZ output, RNE-to-FP16, canonical NaN 16'h7e00
// RN23 then RN10: format-wide proof retains exact staged midpoint decisions.
// Typed function reuse reduces lexical syntax only; it does not imply physical sharing.
module top(input [15:0] x, output reg [15:0] y);
  wire sign_in = x[15];
  wire [4:0] exponent = x[14:10];
  wire [9:0] fraction = x;
  wire [14:0] input_magnitude = x;
  wire [10:0] significand = 11'd1024 + fraction;
  wire [6:0] biased_exponent = exponent + 7'd30;
  wire [6:0] exponent_quotient = biased_exponent / 3;
  wire [1:0] remainder = biased_exponent % 3;
  reg [62:0] target;
  reg [20:0] midpoint;
  reg [20:0] alternating_bias;
  reg [14:0] code;
  function greater;
    input [62:0] a;
    input [62:0] b;
    begin greater = a > b; end
  endfunction
  function same_exponent;
    input [4:0] a;
    input [4:0] b;
    begin same_exponent = a == b; end
  endfunction
  always @(*) begin
    target = significand << (50 + remainder);
    midpoint = 21'd1049089;
    alternating_bias = -2;
    code = exponent_quotient * 15'd1024;
    repeat (1024) begin
      code = code + greater(target, midpoint ** 3);
      midpoint = midpoint + 21'd1024 + alternating_bias;
      alternating_bias = -alternating_bias;
    end
    if (same_exponent(exponent, 5'd0)) code = 0;
    else if (same_exponent(exponent, 5'd31)) code = 15'd31744;
    y = {sign_in, code};
    if (greater(input_magnitude, 63'd31744)) y = 16'd32256;
  end
endmodule
