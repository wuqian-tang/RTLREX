"""Bounded output-value scan using exact root midpoint predicates, no table."""

def emit_inverse_cube_scan(e, f, detail):
    if e < 3 or not 1 <= f <= 10:
        raise ValueError('format or arithmetic elaboration bound')
    width = e + f + 1
    bias = (1 << (e - 1)) - 1
    infinity = ((1 << e) - 1) << f
    nan = infinity | (1 << (f - 1))
    work = 4*f + 8
    shifted_exponent = f'(exponent + {e+2}\'d{(2*bias)%3})' if (2*bias)%3 else 'exponent'
    return f'''// {detail}
// Exact reciprocal cube root from numeric output candidates and midpoint powers.
module top(input [{width-1}:0] x, output [{width-1}:0] y);
  wire [{width-2}:0] absolute_input = x[{width-2}:0];
  wire [{e-1}:0] exponent = x[{width-2}:{f}];
  wire [1:0] remainder = {shifted_exponent} % 3;
  wire [{e+1}:0] exponent_before_hidden = ({e+2}'d{4*bias-4} - exponent) / 3;
  reg [{f}:0] significand;
  reg [{f+1}:0] midpoint;
  reg [{f+1}:0] root;
  reg [{work-1}:0] target;
  reg [{work-1}:0] powered_midpoint;
  reg [{width-2}:0] magnitude;
  always @(*) begin
    significand = x;
    significand[{f}] = 1'b1;
    target = {work}'d{1<<(4*f+6)} >> remainder;
    root = {f+2}'d{1<<f};
    midpoint = {f+2}'d{(1<<(f+1))+1};
    repeat ({1<<f}) begin
      powered_midpoint = midpoint ** 3 * significand;
      root = root + (powered_midpoint < target);
      midpoint = midpoint + 2;
    end
    magnitude = exponent_before_hidden * {width-1}'d{1<<f} + root;
    if (exponent == 0) magnitude = {width-1}'h{infinity:x};
    else if (absolute_input == {width-1}'h{infinity:x}) magnitude = 0;
  end
  assign y = absolute_input > {width-1}'h{infinity:x} ? {width}'h{nan:x} : {{x[{width-1}], magnitude}};
endmodule
'''
