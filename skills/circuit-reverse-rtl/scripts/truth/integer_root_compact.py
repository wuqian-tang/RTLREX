"""Bounded arithmetic scan for small unsigned integer square roots.

This is a compact source-level alternative. Its unrolled arithmetic structure
can be larger than a bit-prefix root, so callers must retain their active cost
objective and resource guards rather than equating source cost with area.
"""


def emit_bounded_integer_sqrt(input_width: int, output_width: int) -> str:
    if (type(input_width) is not int or type(output_width) is not int
            or not 1 <= input_width <= 16
            or output_width != (input_width + 1) // 2):
        raise ValueError('bounded root needs 1..16 input bits and the exact root width')
    return f'''// Bounded numeric candidates, exact unsigned floor square root.
module top(input [{input_width-1}:0] x, output reg [{output_width-1}:0] y);
  reg [{output_width-1}:0] candidate;
  reg [{2*output_width-1}:0] squared;
  always @(*) begin
    y = 0;
    candidate = 0;
    squared = 0;
    repeat ({1 << output_width}) begin
      squared = candidate * candidate;
      y = squared <= x ? candidate : y;
      candidate = candidate + 1'b1;
    end
  end
endmodule
'''


def choose_integer_sqrt(input_width: int, output_width: int, prefix_source: str) -> str:
    """Keep the bounded scan only when the caller's price ranks it lower.

    Wider inputs and truncated/extended outputs retain the established prefix
    implementation. This bound caps elaboration at 256 numeric trials.
    """
    if not (type(input_width) is int and type(output_width) is int
            and 1 <= input_width <= 16 and output_width == (input_width+1)//2):
        return prefix_source
    from truth.rtl_cost_selection import lowest_cost_source
    candidates = [prefix_source,
                  emit_bounded_integer_sqrt(input_width, output_width),
                  emit_descending_integer_sqrt(input_width, output_width)]
    return lowest_cost_source(candidates)


def emit_descending_integer_sqrt(input_width: int, output_width: int) -> str:
    """Fixed monotone descent; multiplication retains its full unsigned width.

    Starting at the largest representable root, decrement whenever its exact
    square exceeds the radicand. After at most 2**output_width-1 iterations
    the value is floor(sqrt(x)); once reached it is unchanged. Widening the
    comparison operand is essential for odd input widths, where the square
    needs one additional bit. No input enumeration or stored answers occur.
    """
    if (type(input_width) is not int or type(output_width) is not int
            or not 1 <= input_width <= 16
            or output_width != (input_width + 1) // 2):
        raise ValueError('bounded root needs 1..16 input bits and the exact root width')
    maximum = (1 << output_width) - 1
    return f'''// Bounded monotone arithmetic descent, exact unsigned floor square root.
module top(input [{input_width-1}:0] x, output reg [{output_width-1}:0] y);
  wire [{2*output_width-1}:0] radicand = x;
  always @(*) begin
    y = {output_width}'d{maximum};
    repeat ({maximum}) begin
      y = y - (y * y > radicand);
    end
  end
endmodule
'''
