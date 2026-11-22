// Bounded monotone arithmetic descent, exact unsigned floor square root.
module top(input [11:0] x, output reg [5:0] y);
  wire [11:0] radicand = x;
  always @(*) begin
    y = 6'd63;
    repeat (63) begin
      y = y - (y * y > radicand);
    end
  end
endmodule
