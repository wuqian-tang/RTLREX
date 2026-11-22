module top(input [9:0] x, output reg [4:0] y);
  reg [4:0] t, b;
  always @(x) begin
    y = 0;
    b = 16;
    repeat (5) begin
      t = y + b;
      if (t * t <= x)
        y = t;
      b = b / 2;
    end
  end
endmodule
