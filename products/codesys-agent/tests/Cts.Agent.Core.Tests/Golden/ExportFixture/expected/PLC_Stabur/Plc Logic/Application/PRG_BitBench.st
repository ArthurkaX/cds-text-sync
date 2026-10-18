(*
BitBench — a self-contained benchmark of the cost of bit access.

Project created with the cds-text-sync daemon and LLM agent.
Bench: PLC_Stabur (RK3568, 4x ARM Cortex-A55), CODESYS Control 3.5.16.40,
task t#200 ms, timer SysTimeGetNs on the PLC.

RUN ORDER (counted in task cycles):
  PLC on / application started
  -> wait START_WAIT cycles (50 = 10 s)
  -> round 1: one test ENTIRELY in one cycle
  -> wait GAP_WAIT cycles (5 = 1 s)
  -> round 2 ... and so on up to the last test
  -> conclusion (Conclusion) and 'BitBench: done'.
The 20 tests (B0..B7c read and write) take about 30 s; B8 takes two more rounds.

THE METHOD OF ONE ROUND - PAIRED MEASUREMENTS.
The calibration (CAL_N iterations) chooses nIter so that one half of a pair runs
for about TARGET_EACH_NS. Then WARM_PAIRS warm-up pairs and NPAIRS measured pairs
in a row: a pair is the baseline and the variant with the same nIter, the order
alternates (even pair base -> variant, odd pair the other way round). The result
of a pair is the difference (variant - base) in hundredths of ns/operation. The
differences are sorted at the end of the round; Result is the median, with p25,
p75 and min beside it.

A round is limited by ROUND_BUDGET_NS: if the pairs did not fit, the round is cut
short and is computed from the pairs that made it (fewer than MIN_PAIRS -
SKIPPED). We reset the statistics of the task (CmpIecTask) in the last cycle of
the pause before the round and read them in the first cycle after it: the cycle
max is the round itself.

Restart. A run starts over (from the START_WAIT pause) if:
  - the application was downloaded or reset (the variables are initialised);
  - more than RESTART_GAP_NS passed between two cycles (Online -> Stop/Start:
    the variables survive, but the task was stopped);
  - a rising edge on GVL_Bench.xRun (then the pause is GAP_WAIT, not START_WAIT).
B8 (an unaligned WORD in a STRUCT with pack_mode 0) runs only when
GVL_Bench.xRunUnaligned is set, because it may raise an exception.

We keep the log strings no longer than 120 characters (the runtime cuts a record
at 127); anything longer is sent by LogSafe in pieces.
*)

PROGRAM PRG_BitBench
VAR CONSTANT
	// --- schedule, in task cycles ---
	START_WAIT	: INT := 50;			// after the application starts
	GAP_WAIT	: INT := 5;				// between rounds
	TASK_NS		: ULINT := 200000000;	// task period, ns (t#200 ms)
	RESTART_GAP_NS : ULINT := 1000000000;	// a gap between cycles longer than 1 s = the task was stopped
	// --- method ---
	CAL_N		: UDINT := 1000;		// iterations in the calibration half
	WARM_PAIRS	: INT := 5;				// warm-up pairs (they do not enter the statistics)
	NPAIRS		: INT := 101;			// measured pairs per test (odd - the median is unambiguous)
	MIN_PAIRS	: INT := 21;			// fewer - the test is SKIPPED
	MIN_ITER	: UDINT := 50;
	MAX_ITER	: UDINT := 2000000;
	TARGET_EACH_NS : ULINT := 200000;	// target duration of half a pair, ns (0.2 ms)
	ROUND_BUDGET_NS : ULINT := 80000000;	// round limit, ns (80 ms = 40 % of the cycle)
	// --- tests ---
	IDX_LAST_MAIN : INT := 19;			// 0..9 read B0..B7c, 10..19 write
	IDX_LAST	: INT := 21;			// 20 = read B8, 21 = write B8
	// --- states ---
	ST_IDLE		: INT := 0;				// no run in progress
	ST_WAIT		: INT := 10;			// pause before a round (nWait cycles)
	ST_ROUND	: INT := 20;			// round: one test in this cycle
	ST_DONE		: INT := 100;			// run finished
END_VAR
VAR
	// --- start and restart ---
	xInit		: BOOL;			// FALSE after a download/reset: the first cycle
	xRunPrev	: BOOL;
	tNow		: ULINT;
	tPrevCycle	: ULINT;
	// --- state machine ---
	nFsm		: INT;
	nWait		: INT;			// how many cycles of the pause are left
	xHeadDone	: BOOL;			// the run header has already been printed
	xStatPending : BOOL;		// print the statistics of the task for the round in this cycle
	nTestNo		: INT;			// 0..21
	// --- current test ---
	nMode		: INT;			// 0 = read, 1 = write
	nVariant	: INT;			// 0..10
	nIterCur	: UDINT;		// nIter of the round: the same for both halves of every pair
	// --- statistics of the task itself (CmpIecTask, as in FB_TaskInfo from a production sample) ---
	pTaskInfo	: POINTER TO Task_Info2;
	resTask		: UDINT;
	// --- measurements ---
	fbRun		: FB_BenchRun;
	tBase		: ULINT;
	tVar		: ULINT;
	tPair		: ULINT;
	tRound0		: ULINT;
	tRoundNs	: ULINT;		// duration of the round (without calibration), ns
	uCalBase	: ULINT;
	uCalVar		: ULINT;
	aDiff		: ARRAY [0..100] OF DINT;	// pair differences (NPAIRS = 101)
	nMeasCnt	: INT;
	xCut		: BOOL;			// the round was cut by ROUND_BUDGET_NS
	uMaxPair	: ULINT;
	uMinVar		: ULINT;		// absolute minimum of the variant, hundredths of ns/op
	uMinBase	: ULINT;
	dNew		: DINT;
	dMed		: DINT;
	dP25		: DINT;
	dP75		: DINT;
	dMn			: DINT;
	// --- processing ---
	p			: INT;
	i			: INT;
	j			: INT;
	uTmp		: ULINT;
	dwRes		: DWORD;
	xTimerBad	: BOOL;
	dRead		: DINT;
	dWrite		: DINT;
	dWorst		: DINT;
	dTmp		: DINT;
	// --- strings ---
	sMsg		: STRING(255);
	sName		: STRING(40);
	sWhat		: STRING(80);
END_VAR
// --- implementation ---
// ===================== 1. start, restart, manual run =====================
dwRes := SysTimeGetNs(tNow);

IF NOT xInit THEN
	// the first cycle after a download or a reset
	xInit := TRUE;
	nFsm := ST_WAIT;
	nWait := START_WAIT;
	xHeadDone := FALSE;
	xStatPending := FALSE;
	LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO,
		'BitBench: application started, first round after 50 cycles');
ELSIF tPrevCycle <> 0 AND tNow - tPrevCycle > RESTART_GAP_NS THEN
	// the task was stopped (Online -> Stop/Start): we start the run over
	nFsm := ST_WAIT;
	nWait := START_WAIT;
	xHeadDone := FALSE;
	xStatPending := FALSE;
	LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO,
		'BitBench: restart after a stop, first round after 50 cycles');
END_IF
tPrevCycle := tNow;

IF GVL_Bench.xRun AND NOT xRunPrev THEN
	nFsm := ST_WAIT;
	nWait := GAP_WAIT;
	xHeadDone := FALSE;
	xStatPending := FALSE;
END_IF
xRunPrev := GVL_Bench.xRun;

// ===================== 2. task statistics for the previous round =====================
IF xStatPending THEN
	xStatPending := FALSE;
	IF pTaskInfo <> 0 THEN
		sMsg := CONCAT('Task      ', sName);
		sMsg := CONCAT(sMsg, ': cycle max ');
		sMsg := CONCAT(sMsg, DWORD_TO_STRING(pTaskInfo^.dwMaxCycleTime));
		sMsg := CONCAT(sMsg, ' us, jitter max ');
		sMsg := CONCAT(sMsg, DINT_TO_STRING(pTaskInfo^.iJitterMax));
		sMsg := CONCAT(sMsg, ' us, min ');
		sMsg := CONCAT(sMsg, DINT_TO_STRING(pTaskInfo^.iJitterMin));
		sMsg := CONCAT(sMsg, ' us');
		LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, sMsg);
	END_IF
END_IF

// ===================== 3. state machine =====================
CASE nFsm OF
ST_IDLE:
	;	// waiting for xRun or a restart

ST_WAIT:	// pause; the last cycle of the pause prepares the round
	nWait := nWait - 1;
	IF nWait <= 0 THEN
		IF NOT xHeadDone THEN
			xHeadDone := TRUE;
			nTestNo := 0;
			xTimerBad := FALSE;
			GVL_Bench.xDone := FALSE;
			GVL_Bench.dwSink := 0;
			GVL_Bench.dwSinkW := 0;
			// clear the results of the previous run: after a SKIPPED or a crash
			// the GVL must not keep numbers from the previous run
			FOR i := 0 TO 10 DO
				GVL_Bench.medDiffRead[i] := 0;
				GVL_Bench.p25DiffRead[i] := 0;
				GVL_Bench.p75DiffRead[i] := 0;
				GVL_Bench.minDiffRead[i] := 0;
				GVL_Bench.minVarRead[i] := 0;
				GVL_Bench.minBaseRead[i] := 0;
				GVL_Bench.nIterRead[i] := 0;
				GVL_Bench.nRoundUsRead[i] := 0;
				GVL_Bench.medDiffWrite[i] := 0;
				GVL_Bench.p25DiffWrite[i] := 0;
				GVL_Bench.p75DiffWrite[i] := 0;
				GVL_Bench.minDiffWrite[i] := 0;
				GVL_Bench.minVarWrite[i] := 0;
				GVL_Bench.minBaseWrite[i] := 0;
				GVL_Bench.nIterWrite[i] := 0;
				GVL_Bench.nRoundUsWrite[i] := 0;
				GVL_Bench.nMeasDone[i] := 0;
			END_FOR
			GVL_Bench.nIter := 0;
			GVL_Bench.nLastNs := 0;
			GVL_Bench.nMeasIdx := 0;

			// the run header
			LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO,
				'BitBench: project created with cds-text-sync daemon and LLM agent');

			sMsg := CONCAT('BitBench: start, CPU mode ', GVL_Bench.sCpuMode);
			LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, sMsg);

			sMsg := 'BitBench: CPU RK3568 4x ARM Cortex-A55, task t#';
			sMsg := CONCAT(sMsg, ULINT_TO_STRING(TASK_NS / 1000000));
			sMsg := CONCAT(sMsg, ' ms, timer SysTimeGetNs on the PLC');
			LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, sMsg);

			sMsg := 'BitBench: 1 round = 1 test in one cycle, ';
			sMsg := CONCAT(sMsg, INT_TO_STRING(GAP_WAIT));
			sMsg := CONCAT(sMsg, ' cycles between rounds, round limit ');
			sMsg := CONCAT(sMsg, ULINT_TO_STRING(ROUND_BUDGET_NS / 1000000));
			sMsg := CONCAT(sMsg, ' ms');
			LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, sMsg);

			sMsg := 'BitBench: round = ';
			sMsg := CONCAT(sMsg, INT_TO_STRING(WARM_PAIRS));
			sMsg := CONCAT(sMsg, ' warm-up + ');
			sMsg := CONCAT(sMsg, INT_TO_STRING(NPAIRS));
			sMsg := CONCAT(sMsg, ' measured pairs (base and variant, same nIter), half ~');
			LogComponent.logger.Fmt100(ULINT_TO_DINT(TARGET_EACH_NS / 10000), FALSE);
			sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
			sMsg := CONCAT(sMsg, ' ms');
			LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, sMsg);

			GVL_Bench.aSizeof[0] := SIZEOF(GVL_Bench.stBools);
			GVL_Bench.aSizeof[1] := SIZEOF(GVL_Bench.stBits);
			GVL_Bench.aSizeof[2] := SIZEOF(GVL_Bench.uBits);
			GVL_Bench.aSizeof[3] := SIZEOF(GVL_Bench.uExt);
			GVL_Bench.aSizeof[4] := SIZEOF(GVL_Bench.stPacked);
			GVL_Bench.aSizeof[5] := SIZEOF(GVL_Bench.wData);

			sMsg := 'Memory: 8 BOOL in a STRUCT = ';
			sMsg := CONCAT(sMsg, INT_TO_STRING(GVL_Bench.aSizeof[0]));
			sMsg := CONCAT(sMsg, ' B, 8 BIT in a STRUCT = ');
			sMsg := CONCAT(sMsg, INT_TO_STRING(GVL_Bench.aSizeof[1]));
			sMsg := CONCAT(sMsg, ' B, UNION of 8 BIT = ');
			sMsg := CONCAT(sMsg, INT_TO_STRING(GVL_Bench.aSizeof[2]));
			sMsg := CONCAT(sMsg, ' B');
			LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, sMsg);

			sMsg := 'Memory: the same UNION + EXTENDS = ';
			sMsg := CONCAT(sMsg, INT_TO_STRING(GVL_Bench.aSizeof[3]));
			sMsg := CONCAT(sMsg, ' B, WORD = ');
			sMsg := CONCAT(sMsg, INT_TO_STRING(GVL_Bench.aSizeof[5]));
			sMsg := CONCAT(sMsg, ' B, pack_mode 0 (WORD after BOOL) = ');
			sMsg := CONCAT(sMsg, INT_TO_STRING(GVL_Bench.aSizeof[4]));
			sMsg := CONCAT(sMsg, ' B');
			LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, sMsg);

			LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO,
				'Base  read: dwSink := dwSink + 1; write: dwSinkW := UDINT_TO_DWORD(k AND 1)');

			IF pTaskInfo = 0 THEN
				pTaskInfo := IecTaskGetInfo3(hIecTask := IecTaskGetCurrent(ADR(resTask)),
				                             pResult := ADR(resTask));
			END_IF
		END_IF

		// the task statistics from this moment on are the statistics of the round
		IecTaskResetStatistics(IecTaskGetCurrent(ADR(resTask)));
		nFsm := ST_ROUND;
	END_IF

ST_ROUND:	// one test entirely in this cycle
	// ---------- which test ----------
	IF nTestNo < 10 THEN
		nMode := 0;
		nVariant := nTestNo;
	ELSIF nTestNo <= IDX_LAST_MAIN THEN
		nMode := 1;
		nVariant := nTestNo - 10;
	ELSIF nTestNo = IDX_LAST_MAIN + 1 THEN
		nMode := 0;
		nVariant := 10;
	ELSE
		nMode := 1;
		nVariant := 10;
	END_IF

	CASE nVariant OF
	0:	sName := 'B0 empty loop';
		sWhat := 'control: the variant is the base itself, expect 0';
	1:	sName := 'B1 BOOL fields';
		sWhat := '8 BOOL in a STRUCT, 1 byte each - the reference for the bit tests';
	2:	sName := 'B2 BIT fields';
		sWhat := '8 BIT packed into 1 byte - the write is a read-modify-write';
	3:	sName := 'B3 UNION+EXTENDS';
		sWhat := 'bit via a UNION that EXTENDS ST_Bits8; watch C0542';
	4:	sName := 'B4 UNION';
		sWhat := 'the same 8 BIT in a UNION, without EXTENDS';
	5:	sName := 'B5 WORD.3';
		sWhat := 'bit access to a WORD by dot: wData.3, 16 bits in 2 B';
	6:	sName := 'B6 mask var index';
		sWhat := 'mask (SHR(dwData, i) AND 1), no bit instruction';
	7:	sName := 'B7a 8 BOOL';
		sWhat := '8 BOOL one by one - one iteration = 8 accesses';
	8:	sName := 'B7b byte';
		sWhat := 'all 8 bits as one BYTE - one iteration = 1 access';
	9:	sName := 'B7c word';
		sWhat := 'all 16 bits as one WORD - one iteration = 1 access';
	10:	sName := 'B8 unaligned WORD';
		sWhat := 'pack_mode 0, wData.3 unaligned - the test may raise an exception';
	ELSE
		sName := 'B? unknown';
		sWhat := 'unknown variant';
	END_CASE

	sMsg := CONCAT('Testing ', sName);
	IF nMode = 0 THEN
		sMsg := CONCAT(sMsg, ' (read): ');
	ELSE
		sMsg := CONCAT(sMsg, ' (write): ');
	END_IF
	sMsg := CONCAT(sMsg, sWhat);
	LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, sMsg);

	IF nVariant = 10 THEN
		LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_WARNING,
			'B8 warning: unaligned WORD in a STRUCT with pack_mode 0; an exception here means the app restarts');
	END_IF

	// ---------- calibration: nIter for TARGET_EACH_NS from the slower half ----------
	fbRun(nWhich := 0, nMode := nMode, nVariant := nVariant, nIter := CAL_N);
	uCalBase := fbRun.tDur;
	IF fbRun.dwRes <> 0 THEN
		dwRes := fbRun.dwRes;
	END_IF
	fbRun(nWhich := 1, nMode := nMode, nVariant := nVariant, nIter := CAL_N);
	uCalVar := fbRun.tDur;
	IF fbRun.dwRes <> 0 THEN
		dwRes := fbRun.dwRes;
	END_IF

	uTmp := uCalBase;
	IF uCalVar > uTmp THEN
		uTmp := uCalVar;
	END_IF
	IF uTmp <> 0 THEN
		uTmp := (TARGET_EACH_NS * CAL_N) / uTmp;
	ELSE
		uTmp := MIN_ITER;
	END_IF
	IF uTmp < MIN_ITER THEN
		uTmp := MIN_ITER;
	END_IF
	IF uTmp > MAX_ITER THEN
		uTmp := MAX_ITER;
	END_IF
	nIterCur := ULINT_TO_UDINT(uTmp);
	GVL_Bench.nIter := nIterCur;

	// ---------- pairs: warm-up, then measured ----------
	nMeasCnt := 0;
	xCut := FALSE;
	uMaxPair := 0;
	uMinVar := 16#FFFFFFFFFFFFFFFF;
	uMinBase := 16#FFFFFFFFFFFFFFFF;
	SysTimeGetNs(tRound0);

	FOR p := 0 TO WARM_PAIRS + NPAIRS - 1 DO
		IF (p MOD 2) = 0 THEN
			fbRun(nWhich := 0, nMode := nMode, nVariant := nVariant, nIter := nIterCur);
			tBase := fbRun.tDur;
			fbRun(nWhich := 1, nMode := nMode, nVariant := nVariant, nIter := nIterCur);
			tVar := fbRun.tDur;
		ELSE
			fbRun(nWhich := 1, nMode := nMode, nVariant := nVariant, nIter := nIterCur);
			tVar := fbRun.tDur;
			fbRun(nWhich := 0, nMode := nMode, nVariant := nVariant, nIter := nIterCur);
			tBase := fbRun.tDur;
		END_IF
		IF fbRun.dwRes <> 0 THEN
			dwRes := fbRun.dwRes;
		END_IF

		IF p >= WARM_PAIRS THEN
			tPair := tBase + tVar;
			IF tPair > uMaxPair THEN
				uMaxPair := tPair;
			END_IF
			// the difference in hundredths of ns/op: each half is normalised separately
			uTmp := (tVar * 100) / nIterCur;
			IF uTmp < uMinVar THEN
				uMinVar := uTmp;
			END_IF
			dNew := ULINT_TO_DINT(uTmp);
			uTmp := (tBase * 100) / nIterCur;
			IF uTmp < uMinBase THEN
				uMinBase := uTmp;
			END_IF
			dNew := dNew - ULINT_TO_DINT(uTmp);
			aDiff[nMeasCnt] := dNew;
			nMeasCnt := nMeasCnt + 1;
		END_IF

		// round limit: the task cycle must not overrun the budget
		SysTimeGetNs(tPair);
		IF tPair - tRound0 > ROUND_BUDGET_NS THEN
			xCut := TRUE;
			EXIT;
		END_IF
	END_FOR

	SysTimeGetNs(tPair);
	tRoundNs := tPair - tRound0;
	GVL_Bench.nLastNs := tRoundNs;
	GVL_Bench.nMeasIdx := nMeasCnt;

	// ---------- insertion sort (101 elements, once per round) ----------
	FOR i := 1 TO nMeasCnt - 1 DO
		dNew := aDiff[i];
		j := i - 1;
		WHILE j >= 0 DO
			IF aDiff[j] > dNew THEN
				aDiff[j + 1] := aDiff[j];
				j := j - 1;
			ELSE
				EXIT;
			END_IF
		END_WHILE
		aDiff[j + 1] := dNew;
	END_FOR

	// ---------- round result ----------
	sMsg := CONCAT('Result  ', sName);
	IF nMode = 0 THEN
		sMsg := CONCAT(sMsg, ' (read): ');
	ELSE
		sMsg := CONCAT(sMsg, ' (write): ');
	END_IF

	IF nMeasCnt >= MIN_PAIRS THEN
		dMn := aDiff[0];
		dP25 := aDiff[nMeasCnt / 4];
		dMed := aDiff[nMeasCnt / 2];
		dP75 := aDiff[(nMeasCnt * 3) / 4];

		IF nMode = 0 THEN
			GVL_Bench.medDiffRead[nVariant] := dMed;
			GVL_Bench.p25DiffRead[nVariant] := dP25;
			GVL_Bench.p75DiffRead[nVariant] := dP75;
			GVL_Bench.minDiffRead[nVariant] := dMn;
			GVL_Bench.minVarRead[nVariant] := ULINT_TO_DWORD(uMinVar);
			GVL_Bench.minBaseRead[nVariant] := ULINT_TO_DWORD(uMinBase);
			GVL_Bench.nIterRead[nVariant] := nIterCur;
			GVL_Bench.nRoundUsRead[nVariant] := ULINT_TO_UDINT(tRoundNs / 1000);
		ELSE
			GVL_Bench.medDiffWrite[nVariant] := dMed;
			GVL_Bench.p25DiffWrite[nVariant] := dP25;
			GVL_Bench.p75DiffWrite[nVariant] := dP75;
			GVL_Bench.minDiffWrite[nVariant] := dMn;
			GVL_Bench.minVarWrite[nVariant] := ULINT_TO_DWORD(uMinVar);
			GVL_Bench.minBaseWrite[nVariant] := ULINT_TO_DWORD(uMinBase);
			GVL_Bench.nIterWrite[nVariant] := nIterCur;
			GVL_Bench.nRoundUsWrite[nVariant] := ULINT_TO_UDINT(tRoundNs / 1000);
		END_IF
		GVL_Bench.nMeasDone[nVariant] := nMeasCnt;

		// Result - the median of the pair differences, the sign comes from the number itself
		LogComponent.logger.Fmt100(dMed, TRUE);
		sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
		sMsg := CONCAT(sMsg, ' ns/op vs base (');
		sMsg := CONCAT(sMsg, INT_TO_STRING(nMeasCnt));
		sMsg := CONCAT(sMsg, ': p25 ');
		LogComponent.logger.Fmt100(dP25, TRUE);
		sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
		sMsg := CONCAT(sMsg, ', p75 ');
		LogComponent.logger.Fmt100(dP75, TRUE);
		sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
		sMsg := CONCAT(sMsg, ', min ');
		LogComponent.logger.Fmt100(dMn, TRUE);
		sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
		sMsg := CONCAT(sMsg, '), nIter ');
		sMsg := CONCAT(sMsg, UDINT_TO_STRING(nIterCur));
		LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, sMsg);
	ELSE
		// SKIPPED - explicitly, and nothing is left in the GVL
		IF nMode = 0 THEN
			GVL_Bench.medDiffRead[nVariant] := 0;
		ELSE
			GVL_Bench.medDiffWrite[nVariant] := 0;
		END_IF
		GVL_Bench.nMeasDone[nVariant] := 0;
		sMsg := CONCAT(sMsg, 'SKIPPED, only ');
		sMsg := CONCAT(sMsg, INT_TO_STRING(nMeasCnt));
		sMsg := CONCAT(sMsg, ' pairs fit the round limit');
		LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_ERROR, sMsg);
	END_IF

	// Round - the duration of the round and the absolute minima of both halves
	sMsg := CONCAT('Round     ', sName);
	sMsg := CONCAT(sMsg, ': ');
	LogComponent.logger.Fmt100(ULINT_TO_DINT(tRoundNs / 10000), FALSE);
	sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
	sMsg := CONCAT(sMsg, ' ms');
	IF xCut THEN
		sMsg := CONCAT(sMsg, ' (cut at the limit)');
	END_IF
	sMsg := CONCAT(sMsg, ', max pair ');
	LogComponent.logger.Fmt100(ULINT_TO_DINT(uMaxPair / 10000), FALSE);
	sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
	sMsg := CONCAT(sMsg, ' ms, min var ');
	LogComponent.logger.Fmt100(ULINT_TO_DINT(uMinVar), FALSE);
	sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
	sMsg := CONCAT(sMsg, ' / base ');
	LogComponent.logger.Fmt100(ULINT_TO_DINT(uMinBase), FALSE);
	sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
	sMsg := CONCAT(sMsg, ' ns/op');
	LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, sMsg);

	// ---------- next round, conclusion, or the end ----------
	xStatPending := TRUE;
	nTestNo := nTestNo + 1;

	IF nTestNo = IDX_LAST_MAIN + 1 THEN
		// Conclusion from the MEDIANS of the pair differences; min beside it
		dRead := GVL_Bench.medDiffRead[2] - GVL_Bench.medDiffRead[1];
		dWrite := GVL_Bench.medDiffWrite[2] - GVL_Bench.medDiffWrite[1];

		LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, '=========');

		sMsg := 'Conclusion: BIT vs BOOL fields (B2 - B1), median read ';
		LogComponent.logger.Fmt100(dRead, TRUE);
		sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
		sMsg := CONCAT(sMsg, ' (min ');
		LogComponent.logger.Fmt100(GVL_Bench.minDiffRead[2] - GVL_Bench.minDiffRead[1], TRUE);
		sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
		sMsg := CONCAT(sMsg, '), write ');
		LogComponent.logger.Fmt100(dWrite, TRUE);
		sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
		sMsg := CONCAT(sMsg, ' (min ');
		LogComponent.logger.Fmt100(GVL_Bench.minDiffWrite[2] - GVL_Bench.minDiffWrite[1], TRUE);
		sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
		sMsg := CONCAT(sMsg, ') ns/op');
		LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, sMsg);

		IF dWrite > dRead THEN
			dWorst := dWrite;
		ELSE
			dWorst := dRead;
		END_IF
		IF dWorst < 0 THEN
			dWorst := 0;
		END_IF

		// dWorst is in hundredths of ns/op, so 1000 accesses = dWorst/100 us.
		// The share of the cycle in ppm = dWorst * 10 ns * 1e6 / TASK_NS; printed in hundredths of ppm.
		sMsg := 'Conclusion: 1000 bit accesses cost ';
		LogComponent.logger.Fmt100(dWorst, FALSE);
		sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
		sMsg := CONCAT(sMsg, ' us = ');
		LogComponent.logger.Fmt100(LINT_TO_DINT(DINT_TO_LINT(dWorst) * 1000000000 / ULINT_TO_LINT(TASK_NS)), FALSE);
		sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
		sMsg := CONCAT(sMsg, ' ppm of the ');
		sMsg := CONCAT(sMsg, ULINT_TO_STRING(TASK_NS / 1000000));
		sMsg := CONCAT(sMsg, ' ms task cycle');
		LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, sMsg);

		dTmp := GVL_Bench.medDiffRead[7] - GVL_Bench.medDiffRead[8];
		sMsg := 'Conclusion: 8 BOOL one by one vs 1 BYTE read (B7a - B7b), median ';
		LogComponent.logger.Fmt100(dTmp, TRUE);
		sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
		sMsg := CONCAT(sMsg, ' (min ');
		LogComponent.logger.Fmt100(GVL_Bench.minDiffRead[7] - GVL_Bench.minDiffRead[8], TRUE);
		sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
		sMsg := CONCAT(sMsg, ') ns/iteration');
		LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, sMsg);

		dTmp := GVL_Bench.medDiffRead[3] - GVL_Bench.medDiffRead[4];
		sMsg := 'Conclusion: UNION+EXTENDS vs UNION (B3 - B4), median read ';
		LogComponent.logger.Fmt100(dTmp, TRUE);
		sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
		sMsg := CONCAT(sMsg, ', write ');
		LogComponent.logger.Fmt100(GVL_Bench.medDiffWrite[3] - GVL_Bench.medDiffWrite[4], TRUE);
		sMsg := CONCAT(sMsg, LogComponent.sNumFmt);
		sMsg := CONCAT(sMsg, ' ns/op');
		LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, sMsg);

		IF GVL_Bench.xRunUnaligned THEN
			nWait := GAP_WAIT;
			nFsm := ST_WAIT;
		ELSE
			LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO,
				'B8 skipped: GVL_Bench.xRunUnaligned = FALSE');
			nFsm := ST_DONE;
		END_IF
	ELSIF nTestNo > IDX_LAST THEN
		nFsm := ST_DONE;
	ELSE
		nWait := GAP_WAIT;
		nFsm := ST_WAIT;
	END_IF

ST_DONE:	// run finished
	GVL_Bench.xDone := TRUE;
	LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_INFO, 'BitBench: done');
	nFsm := ST_IDLE;

ELSE
	nFsm := ST_IDLE;
END_CASE

// timer return code: 0 = success; non-zero - the measurements are garbage
IF dwRes <> 0 AND NOT xTimerBad THEN
	xTimerBad := TRUE;
	sMsg := CONCAT('SysTimeGetNs error code ', DWORD_TO_STRING(dwRes));
	LogComponent.logger.LogSafe(LogComponent.BITBENCH, CmpLog.LogClass.LOG_ERROR, sMsg);
END_IF

// ===================== 4. observation =====================
GVL_Bench.nState := nFsm;
GVL_Bench.nTestIdx := nTestNo;
GVL_Bench.nHeartbeat := GVL_Bench.nHeartbeat + 1;
END_PROGRAM
