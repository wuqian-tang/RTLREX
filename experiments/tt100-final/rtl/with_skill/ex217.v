// BF16 cbrt(x), DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0
module top(input [15:0] x, output reg [15:0] y);
  wire sign_in = x[15];
  wire [7:0] exponent = x[14:7];
  wire [6:0] fraction = x;
  wire [14:0] input_magnitude = x;
  wire [7:0] significand = add(8'd128, fraction);
  wire [9:0] biased_exponent = add(exponent, 10'd254);
  wire [9:0] exponent_quotient = biased_exponent / 3;
  wire [1:0] remainder = biased_exponent % 3;
  reg [26:0] target;
  reg [8:0] midpoint;
  reg [14:0] code;
  function [26:0] add;
    input [26:0] a, b;
    begin add = a + b; end
  endfunction
  function [26:0] multiply;
    input [26:0] a, b;
    begin multiply = a * b; end
  endfunction
  function greater;
    input [26:0] a, b;
    begin greater = a > b; end
  endfunction
  function same_exponent;
    input [7:0] a, b;
    begin same_exponent = a == b; end
  endfunction
  function [26:0] choose;
    input condition;
    input [26:0] a, b;
    begin if (condition) choose = a; else choose = b; end
  endfunction
  always @(*) begin
    target = significand << add(17, remainder);
    midpoint = 9'd257;
    code = multiply(exponent_quotient, 15'd128);
    repeat (128) begin
      code = add(code, greater(target,
          multiply(multiply(midpoint, midpoint), midpoint)));
      midpoint = add(midpoint, 9'd2);
    end
    code = choose(same_exponent(exponent, 8'd0), 0,
        choose(same_exponent(exponent, 8'd255), 15'd32640, code));
    y = choose(greater(input_magnitude, 27'd32640), 16'd32704,
        {sign_in, code});
  end
endmodule
