// Binary16 sine.  The datapath uses Q48 range reduction and a degree-11
// odd polynomial; subnormal inputs/results are flushed to signed zero.
module top(input [15:0] x, output [15:0] y);
  function [15:0] sine16;
    input [15:0] a;
    reg signed [127:0] X, R, T, Z, P, S, MAG;
    reg [127:0] SIG;
    reg [14:0] magin;
    reg input_sign, result_sign, small;
    integer i, k, sh, eout, exponent;
    begin
      magin = a[14:0];
      input_sign = a[15];
      exponent = magin[14:10];
      if (exponent == 0) begin
        sine16 = 0;
        sine16[15] = input_sign;
      end else if (exponent == 31) begin
        sine16 = 16'h7e00;
      end else begin
        // Exact conversion of the finite binary16 magnitude to Q48.
        X = 1024 + magin[9:0];
        X = X << (exponent + 23);

        // Reduce to [-pi,pi], then reflect into [-pi/2,pi/2].
        R = (X + 128'sd884279719003555) % 128'sd1768559438007110
            - 128'sd884279719003555;
        if (R > 128'sd442139859501778)
          T = 128'sd884279719003555 - R;
        else if (R < -128'sd442139859501778)
          T = -128'sd884279719003555 - R;
        else
          T = R;

        // Odd degree-9 minimax approximation to sin(T), tuned to the source
        // library's binary16 tie decisions, in Q48.
        Z = (T * T) >>> 48;
        P =  128'sd733472611;
        P = -128'sd55757427136 + ((P * Z) >>> 48);
        P =  128'sd2345545102716 + ((P * Z) >>> 48);
        P = -128'sd46912471577143 + ((P * Z) >>> 48);
        P =  128'sd281474973249978 + ((P * Z) >>> 48);
        S = (T * P) >>> 48;

        result_sign = (S < 0);
        MAG = result_sign ? -S : S;
        result_sign = input_sign != result_sign;
        k = 0;
        for (i = 0; i < 128; i = i + 1)
          if (MAG[i]) k = i;

        // Round to nearest, ties to even.  Subnormal results are flushed,
        // except when rounding promotes the value to the minimum normal.
        small = (k < 34);
        if (small) sh = 24;
        else sh = k - 10;
        SIG = (MAG + (128'd1 << (sh-1)) - 1 + MAG[sh]) >> sh;

        if (small)
          sine16 = {result_sign, (SIG >= 1024 ? 15'h0400 : 15'd0)};
        else begin
          eout = k - 33;
          if (SIG == 2048) begin
            SIG = 1024;
            eout = eout + 1;
          end
          sine16 = SIG;
          sine16[14:10] = eout;
          sine16[15] = result_sign;
        end
      end
    end
  endfunction

  assign y = sine16(x);
endmodule
