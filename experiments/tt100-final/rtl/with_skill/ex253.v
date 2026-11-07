// eight-lane packed unsigned Q1.1 sum to FP8 E4M3, exact reduction, RNE
// Exact two-bit lane sum; power-of-two normalization and ties-to-even.
module top(input [15:0] x, output reg [7:0] y);
  reg [15:0] remaining;
  reg [1:0] lane;
  reg [4:0] total;
  reg [6:0] base;
  always @(*) begin
    remaining = x;
    lane = 0;
    total = 0;
    repeat (8) begin
      lane = remaining;
      total = total + lane;
      remaining = remaining >> 2;
    end
    base = 7'd64;
    if (total[4]) begin
      total = (total + total[1]) >> 1;
      base = 7'd72;
    end else begin
      repeat (3) begin
        if (total < 8) begin
          total = total << 1;
          base = base - 8;
        end
      end
    end
    y = total ? base + total : 8'd0;
  end
endmodule
