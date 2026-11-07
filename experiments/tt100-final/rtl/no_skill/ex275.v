module top(input [7:0] x, output reg [3:0] y);
  reg [4:0] i;

  // Unsigned integer square root: max i such that i*i <= x.
  always @(x) begin
    y = 0;
    i = 1;
    repeat (15) begin
      if (x >= i*i)
        y = i;
      i = i + 1;
    end
  end
endmodule
