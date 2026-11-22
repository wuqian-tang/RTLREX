module top(input [15:0] x, output reg [15:0] y);
  reg [10:0] mantissa;
  reg [32:0] cube;
  reg [43:0] numerator;
  reg [11:0] rounded;
  reg [15:0] magnitude;
  integer e, exponent_bias, result_base;

  always @(x) begin
    e = x[14:10];
    mantissa = x;
    mantissa[10] = 1;
    cube = mantissa ** 3;

    if (mantissa <= 1290) begin
      numerator = 44'h20000000000;
      exponent_bias = 58;
    end else if (mantissa <= 1625) begin
      numerator = 44'h40000000000;
      exponent_bias = 57;
    end else begin
      numerator = 44'h80000000000;
      exponent_bias = 56;
    end

    rounded = (numerator + (cube >> 1)) / cube;

    result_base = exponent_bias - 3*e;
    magnitude = 0;
    if (result_base >= 0) begin
      magnitude = (result_base << 10) + rounded;
      if (magnitude >= 16'h7c00)
        magnitude = 16'h7c00;
    end
    y = x;
    y[14:0] = magnitude;
    if ((e == 31) && (mantissa != 1024))
      y = 16'h7e00;
  end
endmodule
