"""Exact normalized square roots with bounded nearest-integer Newton updates.

Format constants determine normalization and iteration bounds. Complete RTL
checking remains required, including all IEEE guards and signed zero.
"""

def emit_newton_rounded_sqrt(e,f,detail):
 """Exact integer nearest-square-root Newton recurrence.

 For integer A, the nearest root R uniquely satisfies
 R*(R-1) <= A-1 < R*(R+1). The update
 (u+floor((A-1)/u)+1)//2 fixes R and, for u>R,
 0 <= next_u-R <= floor((u-R)/2). Starting u=2**(f+1)
 therefore reaches R in at most f+1 steps, including rounded carry.
 """
 if e<3 or f<1:raise ValueError('supported format')
 width=1+e+f;bias=(1<<(e-1))-1;maximum=(1<<e)-1
 infinity=maximum<<f;nan=infinity|(1<<(f-1))
 return f'''// {detail}
// Exact nearest-integer square-root Newton recurrence, bounded by fraction width.
module top(input [{width-1}:0] x, output reg [{width-1}:0] y);
  wire [{e-1}:0] exponent = x[{e+f-1}:{f}];
  wire [{e}:0] exponent_before_hidden = (exponent + {e+1}'d{bias-2}) >> 1;
  reg [{f}:0] significand;
  reg [{2*f+1}:0] radicand_minus_one;
  reg [{f+1}:0] root;
  always @(*) begin
    significand = x;
    significand[{f}] = 1'b1;
    radicand_minus_one = (significand << ({f} + !exponent[0])) - 1;
    root = {f+2}'d{1<<(f+1)};
    repeat ({f+1}) root = (root + radicand_minus_one / root + 1) >> 1;
    if (exponent == 0) y = {{x[{width-1}], {width-1}'d0}};
    else if (x > {width}'h{infinity:x}) y = {width}'h{nan:x};
    else if (x == {width}'h{infinity:x}) y = {width}'h{infinity:x};
    else y = exponent_before_hidden * {width}'d{1<<f} + root;
  end
endmodule
'''


def emit_newton_rounded_rsqrt(e,f,detail):
 """Exact nearest root of a normalized positive rational using integer bias.

 For A=N/S, RNE sqrt(A) equals nearest sqrt(floor(A+3/4))
 when no squared-halfway tie exists. Since N is a power of two and R>=2,
 a tie would require an odd square >1 to divide a power of two and is
 impossible. The integer Newton kernel therefore uses
 B=floor(A-1/4)=(4N-S)//(4S), preserving every rational midpoint.
 """
 if e<3 or f<1:raise ValueError('supported format')
 width=e+f+1;bias=(1<<(e-1))-1;maximum=(1<<e)-1
 infinity=maximum<<f;nan=infinity|(1<<(f-1));numerator_width=3*f+5
 return f'''// {detail}
// Exact reciprocal sqrt: rational midpoint-preserving bias and nearest-root Newton.
module top(input [{width-1}:0] x, output reg [{width-1}:0] y);
  wire [{e-1}:0] exponent = x[{e+f-1}:{f}];
  wire [{e}:0] exponent_before_hidden = ({e+1}'d{3*bias-3} - exponent) >> 1;
  reg [{f}:0] significand;
  reg [{2*f+1}:0] biased_radicand;
  reg [{f+1}:0] root;
  always @(*) begin
    significand = x;
    significand[{f}] = 1'b1;
    biased_radicand = (({numerator_width}'d{1<<(3*f+3)} << exponent[0]) - significand) / (significand << 2);
    root = {f+2}'d{1<<(f+1)};
    repeat ({f+1}) root = (root + biased_radicand / root + 1) >> 1;
    if (exponent == 0) y = {{x[{width-1}], {width-1}'h{infinity:x}}};
    else if (x > {width}'h{infinity:x}) y = {width}'h{nan:x};
    else if (x == {width}'h{infinity:x}) y = {width}'d0;
    else y = exponent_before_hidden * {width}'d{1<<f} + root;
  end
endmodule
'''


def emit_factored_newton_sqrt(e, f, detail):
 """Use the two exact normalization factors instead of a variable shift count.

 The radicand is S*2**f for odd encoded exponent and S*2**(f+1)
 for even exponent. A typed factor mux eliminates the logical negation and
 shift-count addition while preserving the same exact integer Newton kernel.
 """
 rtl = emit_newton_rounded_sqrt(e, f, detail)
 old = f'radicand_minus_one = (significand << ({f} + !exponent[0])) - 1;'
 new = (f'radicand_minus_one = significand * (exponent[0] ? '
        f"{2*f+2}'d{1<<f} : {2*f+2}'d{1<<(f+1)}) - 1;")
 assert rtl.count(old) == 1
 return rtl.replace(old, new)
