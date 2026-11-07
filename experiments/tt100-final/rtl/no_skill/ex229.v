module top(input [15:0] x, output [15:0] y);
  wire sign = x[15];
  wire [14:0] mag = x[14:0];

  /*
   * Magnitude of binary16 tanh.  Starting with tanh(x/4096) ~= x/4096,
   * twelve applications of tanh(2z)=2*tanh(z)/(1+tanh(z)^2) restore the
   * range.  Q40 precision makes this limit construction exact at binary16
   * rounding boundaries over the interval which reaches this function.
   */
  function [14:0] tanh_mag;
    input [14:0] a;
    reg [4:0] e;
    reg [10:0] mant;
    reg [40:0] t, den, half;
    reg [11:0] sig;
    reg [95:0] wide;
    integer i;
    integer p;
    reg found;
    begin
      e = a[14:10];
      mant = 11'h400 + a[9:0];
      t = mant << (e + 3);       // (input / 4096) in Q40
      for (i = 0; i < 12; i = i + 1) begin
        wide = t; wide = wide * t;
        den = 41'h1_0000000000 + (wide >> 40);
        wide = t; wide = wide << 41;
        t = wide / den;
      end

      p = 0;
      found = 0;
      for (i = 40; i >= 0; i = i - 1)
        if (!found && t[i]) begin p = i; found = 1; end

      p = p - 10;
      sig = t >> p;
      half = 41'b1 << (p - 1);
      sig = (t + half - 1'b1 + sig[0]) >> p; // nearest, ties to even
      // The arithmetic form also carries a rounded 2048 significand.
      tanh_mag = ((p - 15) << 10) + sig - 1024;
    end
  endfunction

  reg [15:0] result;
  always @* begin
    if (mag < 15'h0400)
      result = {sign, 15'b0};             // flush input subnormals
    else if (mag > 15'h7c00)
      result = 16'h7e00;                  // canonical NaN
    else
      result = {sign, (mag >= 15'h4482) ? 15'h3c00 : tanh_mag(mag)};
  end
  assign y = result;
endmodule
