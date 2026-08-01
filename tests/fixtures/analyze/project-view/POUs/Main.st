PROGRAM MAIN
VAR_INPUT
    bEnable : BOOL;
    nTarget : INT;    (* this input is never read *)
    sName : STRING(80);
END_VAR
VAR_OUTPUT
    bRunning : BOOL;
END_VAR
VAR
    x : INT;
    y : INT;
END_VAR

IMPLEMENTATION

x := 10;
bRunning := bEnable;
IF bEnable THEN
    x := x + 1;
END_IF
// y := x + 5;
(* y := y + 2; *)
