PROGRAM MAIN
(* t76 timing probe *)
VAR
	eObservedMode : E_BenchMode;
END_VAR
// --- implementation ---
// Self-contained bit-access benchmark: it starts itself 50 cycles after the
// application starts, writes its report to the runtime log, and repeats on GVL_Bench.xRun.
// Project created with the cds-text-sync daemon and LLM agent.
PRG_BitBench();
eObservedMode := GVL_Bench.eMode;

GVL_Motors.fbMotor1(
	xStart := GVL_Motors.xM1Start,
	xStop := GVL_Motors.xM1Stop,
	xFeedback := GVL_Motors.xM1Feedback,
	xReset := GVL_Motors.xM1Reset,
	xRun => GVL_Motors.xM1Run,
	xFault => GVL_Motors.xM1Fault,
	nStarts => GVL_Motors.nM1Starts);
GVL_Motors.fbMotor2(
	xStart := GVL_Motors.xM2Start,
	xStop := GVL_Motors.xM2Stop,
	xFeedback := GVL_Motors.xM2Feedback,
	xReset := GVL_Motors.xM2Reset,
	xRun => GVL_Motors.xM2Run,
	xFault => GVL_Motors.xM2Fault,
	nStarts => GVL_Motors.nM2Starts);

// Fixture: exercise the function, property, action and interface kinds.
GVL_Fixture.nTicks := GVL_Fixture.nTicks + 1;
GVL_Fixture.rScaled := F_Scale(UDINT_TO_REAL(GVL_Fixture.nTicks), 0.5);
IF GVL_Fixture.nTicks MOD 10 = 0 THEN
	GVL_Fixture.fbValve.M_Toggle();
END_IF
GVL_Fixture.xValveOpen := GVL_Fixture.fbValve.P_Open;
END_PROGRAM
