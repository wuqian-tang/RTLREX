module top(input [15:0] x, output [7:0] y);
  wire [6:0] a = x[6:0];
  wire [6:0] b = x[14:8];
  wire [3:0] am = a[6:3] ? {1'b1, a[2:0]} : {1'b0, a[2:0]};
  wire [3:0] bm = b[6:3] ? {1'b1, b[2:0]} : {1'b0, b[2:0]};
  wire [3:0] ae = a[6:3] ? a[6:3] - 1'b1 : 4'b0;
  wire [3:0] be = b[6:3] ? b[6:3] - 1'b1 : 4'b0;
  wire [17:0] av = {{14{1'b0}}, am} << ae;
  wire [17:0] bv = {{14{1'b0}}, bm} << be;
  wire [17:0] r = av % bv;

  function [6:0] fp8;
    input [17:0] v;
    integer i;
    begin
      fp8 = v[6:0];
      for (i = 3; i < 18; i = i + 1)
        if (v[i]) fp8 = ((i - 2) << 3) | ((v >> (i - 3)) & 7);
    end
  endfunction

  assign y = (a == 7'h7f || b == 0 || b == 7'h7f)
             ? 8'h7f : {x[7], fp8(r)};
endmodule
