"""Exact packed unsigned two-bit lane reduction to finite E4M3."""


def emit_packed_q11_sum(lanes: int, detail: str) -> str:
    """Sum up to ten Q1.1 lanes and encode their half-unit result exactly.

    The bound makes the sole lossy normalization a one-bit RNE operation.
    This is a format/range-derived arithmetic implementation, not a LUT.
    """
    if type(lanes) is not int or not 1 <= lanes <= 10:
        raise ValueError('compact Q1.1 reduction supports one to ten lanes')
    return f'''// {detail}
// Exact two-bit lane sum; power-of-two normalization and ties-to-even.
module top(input [{2*lanes-1}:0] x, output reg [7:0] y);
  reg [{2*lanes-1}:0] remaining;
  reg [1:0] lane;
  reg [4:0] total;
  reg [6:0] base;
  always @(*) begin
    remaining = x;
    lane = 0;
    total = 0;
    repeat ({lanes}) begin
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
'''
