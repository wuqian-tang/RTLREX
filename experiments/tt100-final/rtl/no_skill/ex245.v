module top(input [15:0] x, output [7:0] y);
  // Add the finite-only E5M2 operands x[7:0] and x[15:8].
  // Decode an E5M2 finite value into exact fixed-point units.
  function signed [37:0] decode;
    input [7:0] a;
    reg [37:0] m;
    reg [4:0] e;
    begin
      e = a[6:2];
      m = a[1:0];
      if (e) begin
        m[2] = 1'b1;
        m = m << (e - 1'b1);
      end
      decode = a[7] ? -$signed(m) : $signed(m);
      // A large positive marker carries either NaN through the addition.
      if (m > 38'h180000000)
        decode = 38'h800000000;
    end
  endfunction

  function [6:0] encode;
    input [36:0] v;
    reg [36:0] q, half;
    integer shift, i, code;
    begin
      q = v;
      shift = 0;
      for (i = 35; i; i = i - 1)
        if (q >= 8) begin
          q = q >> 1;
          shift = shift + 1;
        end
      // Round to nearest, with ties going to an even low significand bit.
      if (shift) begin
        half = 37'd1 << (shift - 1);
        q = (v + half - 1 + q[0]) >> shift;
      end
      code = 4*shift + q;
      // Marker values become canonical NaN; finite overflow saturates.
      encode = (code > 132) ? 7'd127 : (code > 126) ? 7'd126 : code;
    end
  endfunction

  wire signed [37:0] sum = decode(x[7:0]) + decode(x[15:8]);
  wire negative = sum[37];
  wire [36:0] magnitude = negative ? -sum : sum;

  assign y = (sum == 0) ? ((x == 16'h8080) ? 8'h80 : 8'h00) :
             {negative, encode(magnitude)};
endmodule
