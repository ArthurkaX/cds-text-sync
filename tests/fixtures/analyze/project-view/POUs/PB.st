PROGRAM PB
VAR
    x : INT;
    y : INT;
END_VAR

IMPLEMENTATION

(* scaling factor *) x := 4095;
y := x + 4095;
x := y;
END_PROGRAM
