module top(input [15:0] x, output [7:0] y);
  // Sum the eight unsigned 2-bit fields (range 0 through 24).
  reg [4:0] count;
  reg [15:0] fields;
  reg [7:0] normalized;
  reg [7:0] base;
  reg [5:0] limit;
  reg [7:0] result;
  assign y = result;
  always @(x) begin
    count = 0;
    fields = x;
    repeat (8) begin
      count = count + fields[1:0];
      fields = fields >> 2;
    end

    // Three fractional log2 bits; retain the last normalized candidate.
    // The recurrence rounds a discarded half to even.
    result = 0;
    normalized = count << 3;
    base = 40;
    limit = 1;
    repeat (5) begin
      if (count >= limit)
        result = base + normalized;
      normalized = (normalized >> 1) + (normalized % 4 == 3);
      base = base + 8;
      limit = limit << 1;
    end
  end
endmodule
