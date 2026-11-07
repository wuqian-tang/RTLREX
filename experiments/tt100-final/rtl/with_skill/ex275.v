// Bounded monotone arithmetic descent, exact unsigned floor square root.
module top(input [7:0] x, output reg [3:0] y);
  wire [7:0] radicand = x;
  always @(*) begin
    y = 4'd15;
    repeat (15) begin
      y = y - (y * y > radicand);
    end
  end
endmodule
