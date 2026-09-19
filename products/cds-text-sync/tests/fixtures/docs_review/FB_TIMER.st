FUNCTION_BLOCK FB_TIMER
VAR_INPUT
    Enable : BOOL; // starts the timer
END_VAR
VAR_OUTPUT
    Done : BOOL; // completion flag
END_VAR
VAR
    TON_1 : TON;
END_VAR
IMPLEMENTATION
    TON_1(IN := Enable, PT := T#1S);
    IF Enable THEN
        Done := TRUE;
    END_IF
END_FUNCTION_BLOCK
