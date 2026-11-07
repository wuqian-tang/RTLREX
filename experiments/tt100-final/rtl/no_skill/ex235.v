module top(input [15:0] x, output [15:0] y);
  wire [4:0] exponent;
  wire [11:0] significand;

  // Rounded binary16 significand of 1/sqrt(x).  The trial root is
  // floor(2*sqrt(2^(31+exponent_parity)/m)), where m is the 11-bit
  // input significand.  A half-way tie would require an odd square times
  // m to be a power of two, which is impossible here, so root[0] suffices
  // for exact round-to-nearest-even.
  function integer rounded_significand;
    input [9:0] fraction;
    input        exponent_parity;
    reg [12:0] root, bit_value;
    reg [36:0] wide_m, wide_root, target, product;
    begin
      wide_m = 11'h400 + fraction;
      target = 37'h200000000 << exponent_parity;
      root = 0;
      for (bit_value = 13'h1000; bit_value;
           bit_value = bit_value >> 1) begin
        wide_root = root + bit_value;
        product = wide_m * wide_root * wide_root;
        if (product <= target)
          root = wide_root;
      end
      rounded_significand = (root + 1'b1) >> 1;
    end
  endfunction

  assign exponent = x[14:10];
  // Function arguments retain the low fraction/parity bits respectively.
  assign significand = rounded_significand(x, exponent);

  assign y = (exponent == 0) ? (x[15] ? 16'hfc00 : 16'h7c00) :
             (x >= 16'h7c01) ? 16'h7e00 :
             (x == 16'h7c00) ? 16'h0000 :
             (((16'd42 - exponent) >> 1) << 10) + significand;
endmodule
