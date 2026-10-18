(*
FB_BenchRun — one benchmark loop body: baseline or variant, nIter iterations.

One call = one measured half of a pair. The base and the variant live in the same
block and at the same nesting level, so that the dispatch overhead is the same
and only the loop body differs.

Baseline:
  read - GVL_Bench.dwSink := dwSink + 1 (the same shape as the read variants);
  write - GVL_Bench.dwSinkW := UDINT_TO_DWORD(k AND 1), that is, writing a
  computed value into a separate DWORD sink without touching bits.
The timer is SysTimeGetNs on the PLC (as before, one measurement = one loop pass).

nIter is chosen by the calibration in PRG_BitBench: half of a pair is about
0.2 ms, the whole round (one test) is no more than 80 ms of the t#200 ms cycle.
*)

FUNCTION_BLOCK FB_BenchRun
VAR_INPUT
	nWhich		: INT;			// 0 = baseline, 1 = variant
	nMode		: INT;			// 0 = read, 1 = write
	nVariant	: INT;			// 0..10
	nIter		: UDINT;		// iterations in the loop
END_VAR
VAR_OUTPUT
	tDur		: ULINT;		// duration of the loop, ns
	dwRes		: DWORD;		// return code of SysTimeGetNs (0 = success)
END_VAR
VAR
	k			: UDINT;
	t0			: ULINT;
	t1			: ULINT;
END_VAR
// --- implementation ---
dwRes := SysTimeGetNs(t0);

IF nWhich = 0 THEN
	// ---------------- baseline ----------------
	IF nMode = 0 THEN
		FOR k := 1 TO nIter DO
			GVL_Bench.dwSink := GVL_Bench.dwSink + 1;
		END_FOR
	ELSE
		FOR k := 1 TO nIter DO
			GVL_Bench.dwSinkW := UDINT_TO_DWORD(k AND 1);
		END_FOR
	END_IF
ELSE
	// ---------------- variant ----------------
	IF nMode = 0 THEN		// ---------- READ ----------
		CASE nVariant OF
		0:	// B0 baseline (the same code as the base - a check of the method)
			FOR k := 1 TO nIter DO
				GVL_Bench.dwSink := GVL_Bench.dwSink + 1;
			END_FOR
		1:	// B1 BOOL field of a STRUCT
			FOR k := 1 TO nIter DO
				GVL_Bench.dwSink := GVL_Bench.dwSink + BOOL_TO_DWORD(GVL_Bench.stBools.b3);
			END_FOR
		2:	// B2 BIT field of a STRUCT
			FOR k := 1 TO nIter DO
				GVL_Bench.dwSink := GVL_Bench.dwSink + BOOL_TO_DWORD(GVL_Bench.stBits.bit3);
			END_FOR
		3:	// B3 bit through UNION + EXTENDS
			FOR k := 1 TO nIter DO
				GVL_Bench.dwSink := GVL_Bench.dwSink + BOOL_TO_DWORD(GVL_Bench.uExt.bits.bit3);
			END_FOR
		4:	// B4 bit through UNION
			FOR k := 1 TO nIter DO
				GVL_Bench.dwSink := GVL_Bench.dwSink + BOOL_TO_DWORD(GVL_Bench.uBits.bits.bit3);
			END_FOR
		5:	// B5 bit access to a WORD by dot
			FOR k := 1 TO nIter DO
				GVL_Bench.dwSink := GVL_Bench.dwSink + BOOL_TO_DWORD(GVL_Bench.wData.3);
			END_FOR
		6:	// B6 mask with a variable index
			FOR k := 1 TO nIter DO
				GVL_Bench.dwSink := GVL_Bench.dwSink + (SHR(GVL_Bench.dwDataB6, k AND 7) AND 1);
			END_FOR
		7:	// B7a: read 8 BOOL one after another (8 accesses per iteration)
			FOR k := 1 TO nIter DO
				GVL_Bench.dwSink := GVL_Bench.dwSink
					+ BOOL_TO_DWORD(GVL_Bench.stBools.b0) + BOOL_TO_DWORD(GVL_Bench.stBools.b1)
					+ BOOL_TO_DWORD(GVL_Bench.stBools.b2) + BOOL_TO_DWORD(GVL_Bench.stBools.b3)
					+ BOOL_TO_DWORD(GVL_Bench.stBools.b4) + BOOL_TO_DWORD(GVL_Bench.stBools.b5)
					+ BOOL_TO_DWORD(GVL_Bench.stBools.b6) + BOOL_TO_DWORD(GVL_Bench.stBools.b7);
			END_FOR
		8:	// B7b: read all 8 bits as one byte
			FOR k := 1 TO nIter DO
				GVL_Bench.dwSink := GVL_Bench.dwSink + BYTE_TO_DWORD(GVL_Bench.uBits.b);
			END_FOR
		9:	// B7c: read all 16 bits as one word
			FOR k := 1 TO nIter DO
				GVL_Bench.dwSink := GVL_Bench.dwSink + WORD_TO_DWORD(GVL_Bench.wData);
			END_FOR
		10:	// B8 bit of a WORD at an unaligned offset (pack_mode 0)
			FOR k := 1 TO nIter DO
				GVL_Bench.dwSink := GVL_Bench.dwSink + BOOL_TO_DWORD(GVL_Bench.stPacked.wData.3);
			END_FOR
		ELSE
			GVL_Bench.dwSink := GVL_Bench.dwSink + 1;
		END_CASE
	ELSE					// ---------- WRITE ----------
		CASE nVariant OF
		0:	// B0 baseline (the same shape as the write base)
			FOR k := 1 TO nIter DO
				GVL_Bench.dwSinkW := UDINT_TO_DWORD(k AND 1);
			END_FOR
		1:	// B1 BOOL field of a STRUCT
			FOR k := 1 TO nIter DO
				GVL_Bench.stBools.b3 := (k AND 1) <> 0;
			END_FOR
		2:	// B2 BIT field of a STRUCT
			FOR k := 1 TO nIter DO
				GVL_Bench.stBits.bit3 := (k AND 1) <> 0;
			END_FOR
		3:	// B3 bit through UNION + EXTENDS
			FOR k := 1 TO nIter DO
				GVL_Bench.uExt.bits.bit3 := (k AND 1) <> 0;
			END_FOR
		4:	// B4 bit through UNION
			FOR k := 1 TO nIter DO
				GVL_Bench.uBits.bits.bit3 := (k AND 1) <> 0;
			END_FOR
		5:	// B5 bit access to a WORD by dot
			FOR k := 1 TO nIter DO
				GVL_Bench.wData.3 := (k AND 1) <> 0;
			END_FOR
		6:	// B6 mask with a variable index (clear and set the bit)
			FOR k := 1 TO nIter DO
				GVL_Bench.dwDataB6 := (GVL_Bench.dwDataB6 AND NOT SHL(DWORD#1, k AND 7))
					OR SHL(BOOL_TO_DWORD((k AND 1) <> 0), k AND 7);
			END_FOR
		7:	// B7a group reset of 8 BOOL. The value depends on the previous one,
			// otherwise the compiler hoists the constant write out of the loop.
			FOR k := 1 TO nIter DO
				GVL_Bench.stBools.b0 := NOT GVL_Bench.stBools.b0;
				GVL_Bench.stBools.b1 := NOT GVL_Bench.stBools.b1;
				GVL_Bench.stBools.b2 := NOT GVL_Bench.stBools.b2;
				GVL_Bench.stBools.b3 := NOT GVL_Bench.stBools.b3;
				GVL_Bench.stBools.b4 := NOT GVL_Bench.stBools.b4;
				GVL_Bench.stBools.b5 := NOT GVL_Bench.stBools.b5;
				GVL_Bench.stBools.b6 := NOT GVL_Bench.stBools.b6;
				GVL_Bench.stBools.b7 := NOT GVL_Bench.stBools.b7;
			END_FOR
		8:	// B7b write all 8 bits as one byte (for the same reason - XOR)
			FOR k := 1 TO nIter DO
				GVL_Bench.uBits.b := GVL_Bench.uBits.b XOR BYTE#1;
			END_FOR
		9:	// B7c write all 16 bits as one word
			FOR k := 1 TO nIter DO
				GVL_Bench.wData := GVL_Bench.wData XOR WORD#1;
			END_FOR
		10:	// B8 write of a WORD bit at an unaligned offset (pack_mode 0)
			FOR k := 1 TO nIter DO
				GVL_Bench.stPacked.wData.3 := (k AND 1) <> 0;
			END_FOR
		ELSE
			GVL_Bench.dwSinkW := UDINT_TO_DWORD(k AND 1);
		END_CASE
	END_IF
END_IF

dwRes := SysTimeGetNs(t1);
tDur := t1 - t0;
END_FUNCTION_BLOCK
