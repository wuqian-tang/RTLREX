module top(input [15:0] x, output reg [7:0] y);
  reg [6:0] nmag, dmag;
  reg [31:0] nval, dval, scaled, step, q, rem;
  integer i, sh;
  reg sign;

  always @* begin
    nmag = x[6:0];
    dmag = x[14:8];
    sign = x[7] ^ x[15];
    nval = (nmag[6:3] == 0) ? nmag[2:0]
                                  : ({1'b1, nmag[2:0]} << (nmag[6:3] - 1));
    dval = (dmag[6:3] == 0) ? dmag[2:0]
                                  : ({1'b1, dmag[2:0]} << (dmag[6:3] - 1));
    scaled = 0;
    step = 0;
    q = 0;
    rem = 0;
    sh = 0;

    if ((nmag == 7'h7f) || (dmag == 7'h7f)) begin
      y = 8'h7f;
    end else if (dmag == 0) begin
      y = (nmag == 0) ? 8'h7f : {sign, 7'h7e};
    end else if (nmag == 0) begin
      y = {sign, 7'h00};
    end else begin
      scaled = nval << 9;
      q = scaled / dval;
      for (i = 4; i < 27; i = i + 1)
        if (q[i]) sh = i - 3;
      step = dval << sh;
      q = scaled / step;
      rem = scaled % step;
      if ((rem + rem > step) || ((rem + rem == step) && q[0]))
        q = q + 1;
      q = q + (sh << 3);
      y = {sign, (q > 126) ? 7'h7e : q[6:0]};
    end
  end
endmodule
