module top(input [15:0] x, output reg [7:0] y);
  reg [6:0] p, q;
  reg [17:0] a, b, lo, hi;
  reg [18:0] midpoint;
  reg [37:0] a2, b2, boundary2;
  reg [38:0] sum2;
  reg [40:0] four_sum2, temp;
  reg [7:0] r, next_r;

  task add;
    input [40:0] u, v;
    output [40:0] s;
    begin
      s = u + v;
    end
  endtask

  // Decode the magnitude of a positive E4M3FN value in units of 2^-9.
  task decode;
    input [6:0] f;
    output [17:0] m;
    begin
      m = f < 8 ? f : ((8 + f[2:0]) << (f[6:3] - 1));
    end
  endtask

  task square;
    input [18:0] v;
    output [37:0] v2;
    begin
      v2 = v * v;
    end
  endtask

  always @(*) begin
    p = x;
    q = x >> 8;
    decode(p, a);
    decode(q, b);
    square(a, a2);
    square(b, b2);
    add(a2, b2, temp);
    sum2 = temp;
    four_sum2 = sum2 << 2;
    r = p > q ? p : q;

    // Quantize the Euclidean magnitude, walking at most five adjacent FP8 bins.
    // Exact midpoint comparisons implement round-to-nearest, ties-to-even.
    // Code 127 naturally remains unchanged, propagating E4M3FN NaN.
    repeat (5) begin
      if (r < 8'd126) begin
        add(r, 1'b1, temp);
        next_r = temp;
        decode(r, lo);
        decode(next_r, hi);
        add(lo, hi, temp);
        midpoint = temp;
        square(midpoint, boundary2);
        add(four_sum2, r[0], temp);
        if (temp > boundary2)
          r = next_r;
      end
    end
    y = r;
  end
endmodule
