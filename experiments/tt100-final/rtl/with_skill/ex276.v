// Bounded monotone arithmetic descent, exact unsigned floor square root.
module top(input [9:0] x, output reg [4:0] y);
  wire [9:0] radicand = x;
  always @(*) begin
    y = 5'd31;
    repeat (31) begin
      y = y - (y * y > radicand);
    end
  end
endmodule
