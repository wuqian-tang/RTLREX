// Bounded monotone arithmetic descent, exact unsigned floor square root.
module top(input [15:0] x, output reg [7:0] y);
  wire [15:0] radicand = x;
  always @(*) begin
    y = 8'd255;
    repeat (255) begin
      y = y - (y * y > radicand);
    end
  end
endmodule
