module top(input [13:0] x, output reg [6:0] y);
  integer bit_value;
  reg [13:0] trial;

  always @(x) begin
    y = 0;
    bit_value = 64;
    repeat (7) begin
      trial = y + bit_value;
      if (trial * trial <= x)
        y = trial;
      bit_value = bit_value >> 1;
    end
  end
endmodule
