module top(input [15:0] x, output [7:0] y);
  reg [7:0] result;
  reg [3:0] ma, mb;
  reg [9:0] product;
  integer ea, eb, exponent, lead, shift, rounded, i;

  task decode;
    input [6:0] a;
    output integer e;
    output [3:0] m;
    reg [3:0] m;
    begin
      e = a[6:3];
      m = a[2:0];
      if (e) m = m + 8;
      else e = 1;
    end
  endtask

  always @* begin
    decode(x[14:8], ea, ma);
    decode(x[6:0], eb, mb);
    product = ma * mb;
    lead = -3;

    if ((x[14:8] == 7'h7f) || (x[6:0] == 7'h7f))
      result = 8'h7f;
    else begin
      for (i = 0; i < 8; i = i + 1)
        if (product[i]) lead = i;
      exponent = ea + eb + lead - 13;

      if (exponent <= 0) begin
        shift = 11 - ea - eb;
        exponent = 1;
      end else
        shift = lead - 3;
      if (shift > 0)
        rounded = (product + (1 << (shift-1)) - 1
                   + product[shift]) >> shift;
      else
        rounded = product;

      rounded = (exponent << 3) + rounded - 8;
      if (rounded > 126)
        rounded = 126;
      result = {x[15] ^ x[7], rounded[6:0]};
    end
  end

  assign y = result;
endmodule
