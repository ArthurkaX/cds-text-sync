METHOD Run
VAR_INPUT
    nSteps : INT;
END_VAR
VAR
    i : INT;
END_VAR

IMPLEMENTATION

THIS.speed := nSteps * 10;
FOR i := 0 TO nSteps DO
    THIS.bMoving := TRUE;
END_FOR
