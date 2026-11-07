// Bounded monotone arithmetic descent, exact unsigned floor square root.
module top(input [13:0] x, output reg [6:0] y);
  wire [13:0] radicand = x;
  always @(*) begin
    y = 7'd127;
    repeat (127) begin
      y = y - (y * y > radicand);
    end
  end
endmodule
