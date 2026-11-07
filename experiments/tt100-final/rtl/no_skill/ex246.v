module top(input [15:0] x, output reg [7:0] y);
  reg [5:0] p;
  reg [31:0] t;
  reg [6:0] m;
  integer e, l, r;
  always @* begin
    if ((x[14:8] == 7'h7f) || (x[6:0] == 7'h7f))
      y = 8'h7f;
    else if ((x[14:8] == 0) || (x[6:0] == 0))
      y = {x[15] ^ x[7], 7'b0};
    else begin
      p = (x[14:10] ? {1'b1,x[9:8]} : {1'b0,x[9:8]}) *
          (x[6:2]   ? {1'b1,x[1:0]} : {1'b0,x[1:0]});
      if (p[5]) l = 5;
      else if (p[4]) l = 4;
      else if (p[3]) l = 3;
      else if (p[2]) l = 2;
      else if (p[1]) l = 1;
      else l = 0;
      e = (x[14:10] ? x[14:10] : 1) +
          (x[6:2] ? x[6:2] : 1) + l - 19;
      if (e <= 0) begin
        t = p << ((x[14:10] ? x[14:10] : 1) +
                  (x[6:2] ? x[6:2] : 1));
        m = (t + 17'h1ffff + t[18]) >> 18;
      end else begin
        t = p << (5-l);
        r = (t + 3 + t[3]) >> 3;
        if (r == 8) begin r = 4; e = e + 1; end
        r = (e << 2) + r - 4;
        m = r > 126 ? 126 : r;
      end
      y = {x[15] ^ x[7],m};
    end
  end
endmodule
