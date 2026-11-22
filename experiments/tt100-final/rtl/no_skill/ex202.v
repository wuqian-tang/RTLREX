module top(input [15:0] x, output [15:0] y);
  function [15:0] exp10_bf16;
    input [15:0] a;
    integer i;
    reg sign;
    reg [7:0] e;
    reg [6:0] q;
    reg [14:0] mag;
    reg [8:0] m;
    reg signed [63:0] t;
    reg signed [63:0] n;
    reg [63:0] f;
    reg [127:0] z, sum, term, product;
    reg [24:0] sig32;
    reg [8:0] sig8;
    begin
      sign = a[15];
      e = a[14:7];
      q = a[6:0];
      mag = a[14:0];
      m = 128+q;
      if (mag > 15'h7f80)
        exp10_bf16 = 16'h7fc0;
      else if (mag >= (sign ? 15'h4218 : 15'h421b))
        exp10_bf16 = sign ? 0 : 16'h7f80;
      else begin
        // t = x*log2(10), in signed Q48 fixed point.
        t = (64'd935039633142894 * m) >> (134-e);
        if (sign) t = -t;
        n = t >>> 48;
        f = t[47:0];

        // 2^fraction = exp(fraction*ln(2)), evaluated in Q48.
        product = f * 128'd195103586505167;
        z = product >> 48;
        sum = 128'd281474976710656;
        term = 128'd281474976710656;
        for (i=1; i<=9; i=i+1) begin
          product = term*z;
          term = (product >> 48)/i;
          sum = sum+term;
        end

        // First round to a float32 significand, then to bfloat16.
        sig32 = (sum+128'd16777216) >> 25;
        sig8 = (sig32+32767+sig32[16]) >> 16;
        exp10_bf16 = ((n+126) <<< 7)+sig8;
      end
    end
  endfunction
  assign y = exp10_bf16(x);
endmodule
