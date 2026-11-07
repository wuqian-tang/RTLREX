// BF16 x^2, DAZ input, FTZ output, RNE-to-BF16, canonical NaN 16'h7fc0
module top(input [15:0] x, output [15:0] y);
  wire [14:0] magnitude = x;
  wire [7:0] exponent = magnitude[14:7];
  wire [6:0] fraction = magnitude;
  function [17:0] times;
    input [17:0] left, right;
    begin times = left * right; end
  endfunction
  function [17:0] plus;
    input [17:0] left, right;
    begin plus = left + right; end
  endfunction
  function [17:0] minus;
    input [17:0] left, right;
    begin minus = left - right; end
  endfunction
  function [15:0] choose;
    input condition;
    input [15:0] yes, no;
    begin choose = condition ? yes : no; end
  endfunction
  wire [7:0] significand = plus(18'd128, fraction);
  wire [15:0] product = times(significand, significand);
  function greater;
    input [15:0] left, right;
    begin greater = left > right; end
  endfunction
  wire normalize = greater(16'd32768, product);
  wire [15:0] aligned = times(product, plus(normalize, 18'd1));
  wire [8:0] rounded = plus(aligned, 18'd127) >> 8;
  wire [17:0] packed_result = plus(times(minus(minus(times(exponent, 18'd2),
      18'd127), normalize), 18'd128), rounded);
  assign y = choose(greater(magnitude, 16'd32640), 16'd32704,
             choose(greater(16'd24448, magnitude),
             choose(greater(16'd8192, magnitude), 16'd0, packed_result),
             16'd32640));
endmodule
