module top(input [15:0] x, output [15:0] y);
  // Combinational bfloat16 exponential: canonical NaN and flushed underflow.
  wire sign = x[15];
  wire [7:0] exponent = x[14:7];
  wire [6:0] fraction = x[6:0];
  reg [15:0] r_y;
  reg signed [63:0] a, r, p;
  reg signed [127:0] product;
  reg signed [15:0] k;
  reg [8:0] significand;
  integer i, shift;

  assign y = r_y;

  always @* begin
    r_y = 16'h3f80;
    a = 0;
    r = 0;
    p = 0;
    product = 0;
    k = 0;
    significand = 0;
    shift = 0;

    if ((exponent == 8'hff) && fraction) begin
      r_y = 16'h7fc0;
    end else if (x[14:0] >= (sign ? 15'h42af : 15'h42b2)) begin
      r_y = sign ? 16'h0000 : 16'h7f80;
    end else if (exponent >= 8'd118) begin
      // Decode the bfloat16 argument exactly into signed Q26.
      shift = exponent - 108;
      a = (64'sd128 + fraction) <<< shift;
      if (sign)
        a = -a;

      // x = k*ln(2) + r, with 0 <= r < ln(2).
      k = a / 64'sd46516320;
      r = a % 64'sd46516320;
      if (sign) begin
        k = k - 1;
        r = r + 64'sd46516320;
      end

      // Q26 Horner evaluation of exp(r), through r^8/8!.
      p = 64'sd67108864;
      for (i = 8; i >= 1; i = i - 1) begin
        product = r * p;
        p = 64'sd67108864 + ((product / i) >>> 26);
      end

      // Round to 8 significant bits. No Q26 midpoint occurs on this domain,
      // so this half-up form is identical to round-to-nearest-even here.
      significand = (p + 64'sd262144) >>> 19;

      // Adding the full 8/9-bit significand also handles mantissa carry.
      r_y = ((k + 126) << 7) + significand;
    end
  end
endmodule
