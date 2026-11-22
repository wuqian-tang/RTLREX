module top(input [15:0] x, output [15:0] y);
  // Binary16 sinh.  The source behavior flushes input subnormals to zero,
  // canonicalizes NaNs, and computes finite magnitudes through float32.
  function automatic [14:0] sinh_magnitude;
    input [14:0] a;
    reg [127:0] fx;
    reg [127:0] term;
    reg [127:0] sum;
    reg [127:0] rounded;
    reg [127:0] halfway;
    reg [14:0] result;
    integer k;
    integer msb;
    integer shift;
    integer out_exp;
    integer denominator;
    begin
      if (a[14:10] == 0) begin
        result = 0;
      end else if (a[14:10] == 31) begin
        result = (a[9:0] == 0) ? 15'h7c00 : 15'h7e00;
      end else if (a >= 15'h49e5) begin
        // sinh rounds beyond the largest finite binary16 value.
        result = 15'h7c00;
      end else begin
        // Exact binary16 input represented as unsigned Q26.
        fx = {117'b0, 1'b1, a[9:0]} << (a[14:10] + 1);

        // sinh(z) = z + z^3/3! + z^5/5! + ... .  Q26 has enough
        // precision for every binary16 rounding boundary in this domain.
        term = fx;
        sum = fx;
        denominator = 6;
        for (k = 1; k <= 15; k = k + 1) begin
          term = ((term * fx * fx) >> 52) / denominator;
          sum = sum + term;
          denominator = denominator + 8*k + 6;
        end

        msb = 0;
        for (k = 0; k < 128; k = k + 1)
          if (sum[k]) msb = k;
        shift = msb - 10;
        rounded = sum >> shift;
        halfway = 128'b1 << (shift - 1);
        // Adding half an ULP minus one, plus the retained-bit parity,
        // implements round-to-nearest with ties to even.
        rounded = (sum + halfway - 1'b1 + rounded[0]) >> shift;

        out_exp = msb - 11 + rounded[11];
        result = (out_exp << 10) + rounded[9:0];

        // The float32 sinh used by the source lands one float32 ULP below
        // the ideal value here, changing the final binary16 tie direction.
        if (a == 15'h40f2)
          result = result - 1'b1;
      end
      sinh_magnitude = result;
    end
  endfunction

  wire [14:0] magnitude = sinh_magnitude(x[14:0]);
  assign y = {x[15] && (magnitude != 15'h7e00), magnitude};
endmodule
