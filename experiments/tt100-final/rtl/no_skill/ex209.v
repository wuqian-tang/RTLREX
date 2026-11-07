module top(input [15:0] x, output [15:0] y);
  reg [15:0] result;
  reg [127:0] xf, z, ex, t, q;
  reg [14:0] base, mag;
  reg sign;
  integer sh;

  assign y = result;

  always @* begin
    sign = x[15];
    if (x[14:7] == 0)
      mag = 0;                              // flush bfloat16 subnormals
    else if (x[14:7] == 8'hff) begin
      if (x[6:0]) begin
        mag = 15'h7fc0;                     // canonical NaN
        sign = 0;
      end else
        mag = 15'h3f80;                     // tanh(+/- infinity)
    end
    else if (x[14:0] <= 15'h3db8)
      mag = x[14:0];                        // correctly rounded tanh(x) is x
    else if (x[14:0] >= 15'h405e)
      mag = 15'h3f80;                       // correctly rounds to +/- 1
    else begin
      // Q32 evaluation of tanh(a)=(exp(2a)-1)/(exp(2a)+1).
      xf = (128'd128 + x[6:0]) << (x[14:7] - 102);
      z = xf << 1;
      // exp(z) = limit (1 + z/n)^n, using n=2^16.
      ex = 4294967296 + (z >> 16);
      repeat (16)
        ex = (ex * ex) >> 32;
      t = ((ex - 4294967296) << 32) / (ex + 4294967296);

      // Convert positive Q32 tanh(a) back to bfloat16, round-to-nearest-even.
      if (t >= 2147483648) begin sh = 24; base = 16'h3e80; end
      else if (t >= 1073741824) begin sh = 23; base = 16'h3e00; end
      else if (t >= 536870912) begin sh = 22; base = 16'h3d80; end
      else begin sh = 21; base = 16'h3d00; end
      q = (t + (128'd1 << (sh-1))) >> sh;
      mag = base + q;
    end
    result = {sign, mag};
  end
endmodule
