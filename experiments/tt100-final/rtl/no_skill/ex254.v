module top(input [15:0] x, output reg [7:0] y);
  integer sum;

  // Normalize, round, saturate, and attach the E4M3FN sign/special cases.
  function integer finish;
    input integer s;
    input [15:0] a;
    integer k;
    begin
      // Leading-one encoder for abs(s); k is the number of discarded bits.
      k = {(s < 0 ? -s : s) >= 131072 ? 14 :
           (s < 0 ? -s : s) >= 65536 ? 13 :
           (s < 0 ? -s : s) >= 32768 ? 12 :
           (s < 0 ? -s : s) >= 16384 ? 11 :
           (s < 0 ? -s : s) >= 8192 ? 10 :
           (s < 0 ? -s : s) >= 4096 ? 9 :
           (s < 0 ? -s : s) >= 2048 ? 8 :
           (s < 0 ? -s : s) >= 1024 ? 7 :
           (s < 0 ? -s : s) >= 512 ? 6 :
           (s < 0 ? -s : s) >= 256 ? 5 :
           (s < 0 ? -s : s) >= 128 ? 4 :
           (s < 0 ? -s : s) >= 64 ? 3 :
           (s < 0 ? -s : s) >= 32 ? 2 :
           (s < 0 ? -s : s) >= 16 ? 1 : 0};

      // Round-to-nearest-even, finite saturation, canonical NaN, signed zero.
      finish = {(a[14:8] == 127) ? 127 :
        ((((k << 3) +
            (k ? ((s < 0 ? -s : s) + (1 << (k - 1)) - 1 +
                  (((s < 0 ? -s : s) >> k) % 2)) >> k :
                 (s < 0 ? -s : s))) > 126) ? 126 :
          ((k << 3) +
            (k ? ((s < 0 ? -s : s) + (1 << (k - 1)) - 1 +
                  (((s < 0 ? -s : s) >> k) % 2)) >> k :
                 (s < 0 ? -s : s)))) +
         128 * ((s < 0) || ((s == 0) && a[15] && (a[7] != a[3])))};
    end
  endfunction

  always @(x) begin
    // E4M3FN accumulator plus exact E2M1 product, in units of 2^-9.
    sum = {(x[15] ? -1 : 1) *
           (x[14:11] ? (8 + x[10:8]) << (x[14:11] - 1) : x[10:8]) +
           (x[7] != x[3] ? -1 : 1) *
           (x[6:5] ? (2 + x[4]) << (x[6:5] - 1) : x[4]) *
           (x[2:1] ? (2 + x[0]) << (x[2:1] - 1) : x[0]) * 128};
    y = finish(sum, x);
  end
endmodule
