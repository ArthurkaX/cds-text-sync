{attribute 'qualified_only'}
VAR_GLOBAL
	// --- control (written by the host; a run starts itself 50 cycles after start) ---
	xRun			: BOOL;			// rising edge: run the tests again
	xRunUnaligned	: BOOL;			// TRUE: also run B8 (unaligned WORD, may crash)
	sCpuMode		: STRING(40);	// CPU frequency mode, written by the host before a run; printed in the log
	// --- observation ---
	xDone			: BOOL;			// run finished
	nState			: INT;			// state of the PRG_BitBench machine
	nTestIdx		: INT;			// current test 0..21 (a round = one test in one cycle)
	nMeasIdx		: INT;			// how many pairs went into the statistics of the last round
	nIter			: UDINT;		// iterations in one half of a pair (both halves are identical)
	nHeartbeat		: UDINT;		// ++ on every call of the task
	nLastNs			: ULINT;		// duration of the last round (without calibration), ns
	dwSink			: DWORD;		// read sink
	dwSinkW			: DWORD;		// write sink (write baseline)
	// --- results: index 0..10 = B0..B7c, B8 ---
	// Difference = variant - base within a pair, the unit is HUNDREDTHS of ns/operation.
	// The median and the percentiles are computed over the pair differences of one round (NPAIRS = 101).
	medDiffRead		: ARRAY [0..10] OF DINT;	// median of the difference, read
	p25DiffRead		: ARRAY [0..10] OF DINT;	// 25th percentile of the difference
	p75DiffRead		: ARRAY [0..10] OF DINT;	// 75th percentile of the difference
	minDiffRead		: ARRAY [0..10] OF DINT;	// the smallest difference (extreme point)
	minVarRead		: ARRAY [0..10] OF DWORD;	// absolute minimum of the variant, hundredths of ns/op
	minBaseRead		: ARRAY [0..10] OF DWORD;	// absolute minimum of the base, hundredths of ns/op
	nIterRead		: ARRAY [0..10] OF UDINT;	// nIter at the end of the test
	nRoundUsRead	: ARRAY [0..10] OF UDINT;	// duration of the round, us
	medDiffWrite	: ARRAY [0..10] OF DINT;	// median of the difference, write
	p25DiffWrite	: ARRAY [0..10] OF DINT;
	p75DiffWrite	: ARRAY [0..10] OF DINT;
	minDiffWrite	: ARRAY [0..10] OF DINT;
	minVarWrite		: ARRAY [0..10] OF DWORD;
	minBaseWrite	: ARRAY [0..10] OF DWORD;
	nIterWrite		: ARRAY [0..10] OF UDINT;
	nRoundUsWrite	: ARRAY [0..10] OF UDINT;
	nMeasDone		: ARRAY [0..10] OF INT;		// how many pairs went into the result (0 = SKIPPED)
	// --- one-off values ---
	aSizeof			: ARRAY [0..5] OF INT;		// SIZEOF of the types
	// --- enum live check ---
	eMode : E_BenchMode := E_BenchMode.Idle;
	aMode : ARRAY [0..2] OF E_BenchMode := [E_BenchMode.Idle, E_BenchMode.Run, E_BenchMode.Fault];
	// --- test data ---
	stBools			: ST_Bools8;
	stBits			: ST_Bits8;
	uBits			: U_Bits8;
	uExt			: U_ExtBits;
	wData			: WORD;
	dwDataB6		: DWORD;
	stPacked		: ST_Packed;
END_VAR
