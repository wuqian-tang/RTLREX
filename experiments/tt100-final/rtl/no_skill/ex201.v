module top(input [15:0] x, output [15:0] y);
  reg [15:0] z;
  reg [31:0] v;
  reg [15:0] r;
  reg [6:0] f;
  reg [63:0] p;
  integer e, q, m;

  assign y = z;

  always @(x) begin
    e = x[14:7];
    f = x;
    if (e == 255 && f)
      z = 16'h7fc0;                   // canonical NaN
    else if ($signed(x) >= 16'sh4300)
      z = 16'h7f80;                   // overflow (including +infinity)
    else if (x >= 16'hc2fd)
      z = 0;                          // underflow (including -infinity)
    else begin
      // Exact magnitude in Q16; tiny inputs shift out and round to one.
      v = (128 + f) << (e - 118);
      v = x[15] ? -v : v;
      q = $signed(v) >>> 16;
      r = v;

      // Degree-four fixed-point approximation of 128*2**(r/65536).
      // Its error is below the bfloat16 rounding margin on this domain.
      p = 64'd7518749203;
      p = 64'd28404149646  + ((p * r) >> 16);
      p = 64'd132881652441 + ((p * r) >> 16);
      p = 64'd380942991046 + ((p * r) >> 16);
      // The last coefficient also carries rounding and output exponent bias.
      p = 64'd69821139853014 + ((p * r) >> 16);
      m = p >> 32;
      z = (q << 7) + m;
    end
  end
endmodule
