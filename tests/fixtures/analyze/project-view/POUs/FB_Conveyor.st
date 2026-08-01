FUNCTION_BLOCK FB_Conveyor
VAR_INPUT
    speed : INT;
    bDirection : BOOL;
END_VAR
VAR_OUTPUT
    bMoving : BOOL;
END_VAR
VAR
    tDrive : TON;
    counter : INT;
END_VAR

IMPLEMENTATION

bMoving := speed > 0;
tDrive(IN := bMoving, PT := T#5s);
IF tDrive.Q THEN
    counter := counter + 1;
END_IF
