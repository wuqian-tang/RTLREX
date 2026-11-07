module top(input [11:0] x, output reg [5:0] y);
  always @(x) begin
    y = 63;
    // Fixed combinational search for floor(sqrt(x)).
    repeat (63)
      y = y - (y*y > x);
  end
endmodule
