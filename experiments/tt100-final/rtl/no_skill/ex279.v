module top(input [15:0] x, output [7:0] y);
  reg [15:0] root;
  reg [15:0] trial;
  integer bit;
  always @(*) begin
    root = 0;
    for (bit = 128; bit; bit = bit / 2) begin
      trial = root + bit;
      if (trial * trial <= x)
        root = trial;
    end
  end
  assign y = root;
endmodule
