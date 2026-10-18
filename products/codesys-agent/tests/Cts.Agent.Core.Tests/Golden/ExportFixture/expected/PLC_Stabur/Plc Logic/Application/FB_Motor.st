FUNCTION_BLOCK FB_Motor
VAR_INPUT
	xStart : BOOL;
	xStop : BOOL;
	xFeedback : BOOL;
	xReset : BOOL;
	tFbTimeout : TIME := T#3S;
END_VAR
VAR_OUTPUT
	xRun : BOOL;
	xFault : BOOL;
	nStarts : UDINT;
END_VAR
VAR
	xStartPrev : BOOL;
	xResetPrev : BOOL;
	xStartRise : BOOL;
	xResetRise : BOOL;
	xAwaitingFeedback : BOOL;
	tFeedback : TON;
END_VAR
// --- implementation ---
xStartRise := xStart AND NOT xStartPrev;
xResetRise := xReset AND NOT xResetPrev;
xStartPrev := xStart;
xResetPrev := xReset;

tFeedback(IN := xAwaitingFeedback, PT := tFbTimeout);

IF xResetRise THEN
	xFault := FALSE;
	xRun := FALSE;
	xAwaitingFeedback := FALSE;
END_IF

IF xStop THEN
	xRun := FALSE;
	xAwaitingFeedback := FALSE;
ELSIF xFault THEN
	xRun := FALSE;
	xAwaitingFeedback := FALSE;
ELSIF xRun AND NOT xAwaitingFeedback THEN
	IF NOT xFeedback THEN
		xRun := FALSE;
		xFault := TRUE;
	END_IF
ELSIF xAwaitingFeedback THEN
	IF tFeedback.Q THEN
		xRun := FALSE;
		xAwaitingFeedback := FALSE;
		xFault := TRUE;
	ELSIF xFeedback THEN
		xAwaitingFeedback := FALSE;
		nStarts := nStarts + 1;
	END_IF
ELSIF xStartRise THEN
	xRun := TRUE;
	xAwaitingFeedback := TRUE;
END_IF
END_FUNCTION_BLOCK
