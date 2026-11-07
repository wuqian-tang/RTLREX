module top(input [15:0] x, output [7:0] y);
  wire [7:0] p = x[2:0] * x[10:8];
  wire [7:0] q = x[6:4] * x[14:12];
  wire ps = x[3] != x[11];
  wire qs = x[7] != x[15];
  wire signed [7:0] sp = ps ? -p : p;
  wire signed [7:0] sq = qs ? -q : q;
  wire signed [7:0] sum = sp + sq;
  wire [6:0] mag = sum[7] ? -sum : sum;
  wire [3:0] shifts = {
    mag[6] ? 2'd3 : mag[5] ? 2'd2 : 2'd1,
    mag[3] ? 2'd0 : mag[2] ? 2'd1 : mag[1] ? 2'd2 : 2'd3
  };

  assign y = {
    // Equal signed zeros retain a minus sign; exact cancellation is +0.
    (sum != 0) ? sum[7] : (ps & qs),
    // Round the integer magnitude to E4M3 (exponent bias 5).
    mag[6:4] ? 7'h38 + (shifts[3:2] << 3) +
               ((mag + (1 << (shifts[3:2] - 1)) - 1 + mag[shifts[3:2]])
                >> shifts[3:2]) :
    mag ? 7'h38 - (shifts[1:0] << 3) + (mag << shifts[1:0]) : 7'h00
  };
endmodule
