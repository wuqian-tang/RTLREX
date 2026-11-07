module top(input [15:0] x, output [15:0] y);
  reg [15:0] result;
  reg [7:0] input_exponent;
  reg [6:0] input_fraction;
  reg [8:0] e;
  reg [1:0] r;
  reg [7:0] output_exponent;
  reg [26:0] scaled_radicand;
  reg [8:0] significand;

  function integer rounded_cuberoot;
    input [26:0] scaled_n;
    integer i;
    reg [9:0] lo, hi, mid;
    reg [29:0] boundary_cubed;
    begin
      // Find the first t for which (2*t+1)^3 exceeds 8 times the radicand.
      lo = 9'd128;
      hi = 9'd257;
      for (i = 8; i; i = i - 1) begin
        mid = (lo + hi) >> 1;
        boundary_cubed = (mid * 2 + 1) ** 3;
        if (boundary_cubed <= scaled_n)
          lo = mid + 1'b1;
        else
          hi = mid;
      end
      rounded_cuberoot = lo;
    end
  endfunction

  always @(*) begin
    input_exponent = x[14:7];
    input_fraction = x;
    result = x[15] ? 16'h8000 : 16'h0000;
    e = input_exponent + 9'd254;
    r = e % 3;
    output_exponent = e / 3;
    scaled_radicand = (128 + input_fraction) << (17 + r);
    significand = rounded_cuberoot(scaled_radicand);

    if (input_exponent == 8'hff)
      result = input_fraction ? 16'h7fc0 : result + 16'h7f80;
    else if (input_exponent)
      result = result + output_exponent * 128 + significand - 128;
  end

  assign y = result;
endmodule
