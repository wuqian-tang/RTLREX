module \$pow (A, B, Y);
  parameter A_SIGNED = 0;
  parameter B_SIGNED = 0;
  parameter A_WIDTH = 1;
  parameter B_WIDTH = 1;
  parameter Y_WIDTH = 1;
  parameter [B_WIDTH-1:0] _TECHMAP_CONSTMSK_B_ = 0;
  parameter [B_WIDTH-1:0] _TECHMAP_CONSTVAL_B_ = 0;

  input [A_WIDTH-1:0] A;
  input [B_WIDTH-1:0] B;
  output [Y_WIDTH-1:0] Y;

  localparam integer EXP = _TECHMAP_CONSTVAL_B_;
  wire _TECHMAP_FAIL_ = (_TECHMAP_CONSTMSK_B_ != {B_WIDTH{1'b1}}) || (EXP > 8);

  function [Y_WIDTH-1:0] pow_const;
    input [A_WIDTH-1:0] a;
    integer i;
    reg [Y_WIDTH-1:0] acc;
    reg [Y_WIDTH-1:0] base;
    begin
      acc = {{(Y_WIDTH-1){1'b0}}, 1'b1};
      base = a;
      for (i = 0; i < EXP; i = i + 1)
        acc = acc * base;
      pow_const = acc;
    end
  endfunction

  assign Y = pow_const(A);
endmodule
