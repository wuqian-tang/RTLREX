// four-lane packed unsigned Q1.1 dot product to FP8 E4M3, fused exact sum, RNE
// Exact unsigned integer product sum and dyadic ties-to-even encoding.
module top(input [15:0] x, output [7:0] y);
  function signed [31:0] word_add;
    input signed [31:0] a, b;
    begin word_add = a + b; end
  endfunction
  function [1:0] lane;
    input [15:0] word;
    input [2:0] index;
    begin lane = word >> (index * 2); end
  endfunction
  function [6:0] encode;
    input [5:0] value;
    integer leading, bit_index, shift;
    reg [6:0] rounded;
    begin
      encode = 0;
      leading = 0;
      shift = 0;
      rounded = 0;
      if (value) begin
        for (bit_index = 0; bit_index < 6; bit_index = bit_index + 1)
          if (value[bit_index]) leading = bit_index;
        shift = leading - 3;
        if (shift > 0)
          rounded = word_add(value, (word_add((7'd1 << shift) - 1, value[shift]) >> 1)) >> shift;
        else
          rounded = value << -shift;
        encode = word_add(word_add(leading, 4) << 3, rounded);
      end
    end
  endfunction
  reg [3:0] product;
  reg [5:0] total;
  integer index;
  always @(*) begin
    total = 0;
    product = 0;
    for (index = 0; index < 4; index = index + 1) begin
      product = lane(x, index) * lane(x, index + 4);
      total = total + product;
    end
  end
  assign y = encode(total);
endmodule
