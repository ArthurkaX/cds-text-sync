FUNCTION_BLOCK FB_Logger
VAR_INPUT
END_VAR
VAR_OUTPUT
END_VAR
VAR
	udiCmpId : UDINT;
	cmResult : Component_Manager.SysTypes.RTS_IEC_RESULT;
END_VAR
// --- implementation ---
// Logger modelled on a production sample.
// Component registration and writing live in the methods LogADD / LogADDLong,
// so that the component name arrives as a parameter on every call.
// Log file on the PLC: /var/volatile/log/codesyscontrol.log
END_FUNCTION_BLOCK

(*
Like LogADD, but for long strings: it cuts Message into pieces no longer than
CHUNK characters and writes each piece as a separate log record.
The runtime cuts a LogAdd2 record at 127 characters, hence CHUNK = 120.

The cut uses the built-in LEFT/RIGHT: copying characters one by one
(Short_Msg[i] := ...) does not advance the string length in CODESYS, and LogAdd2
receives an empty string - that is how the empty log records were produced.
*)

// LOG-file path: /var/volatile/log/codesyscontrol.log

METHOD LogADDLong : BOOL
VAR_INPUT
	Component : STRING;
	LogClass  : UDINT;
	Message   : STRING(1000) := 'something happened';
END_VAR
VAR CONSTANT
	CHUNK : INT := 120;		// chunk length, characters
END_VAR
VAR
	nLen  : INT;
	sRest : STRING(1000);
	sPart : STRING(255);
END_VAR
// --- implementation ---
Component_Manager.CMAddComponent2(Component, 16#01, ADR(udiCmpId), ADR(cmResult));

sRest := Message;
nLen := LEN(sRest);

WHILE nLen > CHUNK DO
	sPart := LEFT(sRest, CHUNK);
	CmpLog.LogAdd2(cmplog.LogConstants.STD_LOGGER, udiCmpID, LogClass, cmpErrors.Errors.ERR_FAILED, 0, sPart);
	sRest := RIGHT(sRest, nLen - CHUNK);
	nLen := nLen - CHUNK;
END_WHILE

IF nLen > 0 THEN
	sPart := LEFT(sRest, nLen);
	CmpLog.LogAdd2(cmplog.LogConstants.STD_LOGGER, udiCmpID, LogClass, cmpErrors.Errors.ERR_FAILED, 0, sPart);
END_IF

LogADDLong := TRUE;
END_METHOD

(*
Like LogADD, but it watches the length itself: a string no longer than LIMIT
characters goes as one record, a longer one goes through LogADDLong in pieces.
The runtime cuts a LogAdd2 record at 127 characters, hence LIMIT = 120.
*)

// LOG-file path: /var/volatile/log/codesyscontrol.log

METHOD LogSafe : BOOL
VAR_INPUT
	Component : STRING;
	LogClass  : UDINT;
	Message   : STRING(255) := 'something happened';
END_VAR
VAR CONSTANT
	MAXLINE : INT := 120;	// LIMIT is an IEC reserved word, hence MAXLINE
END_VAR
// --- implementation ---
IF LEN(Message) > MAXLINE THEN
	LogSafe := LogADDLong(Component, LogClass, Message);
ELSE
	LogSafe := LogADD(Component, LogClass, Message);
END_IF
END_METHOD

(*
Add new record in logfile
Component: STRING from LogComponent. Example: Component := LogComponent.BITBENCH
LogClass: CmpLog.LogClass. Example: LogClass := CmpLog.LogClass.LOG_ERROR
Message: STRING. Write here your Log Message.
*)

// LOG-file path: /var/volatile/log/codesyscontrol.log

METHOD LogADD : BOOL
VAR_INPUT
	Component : STRING;
	LogClass  : UDINT;
	Message   : STRING(255) := 'something happened';
END_VAR
// --- implementation ---
Component_Manager.CMAddComponent2(Component, 16#01, ADR(udiCmpId), ADR(cmResult));

CmpLog.LogAdd2(cmplog.LogConstants.STD_LOGGER, udiCmpID, LogClass, cmpErrors.Errors.ERR_FAILED, 0, Message);
END_METHOD

(*
Prints an integer given in HUNDREDTHS (for example ns/operation * 100) as a
string with two places after the point: 1234 -> 12.34, -5 -> -0.05.
The result goes into LogComponent.sNumFmt: the call always has one argument.
*)

METHOD Fmt100 : BOOL
VAR_INPUT
	v		: DINT;
	xPlus	: BOOL := FALSE;	// TRUE: print positive values with a '+' sign
END_VAR
VAR
	xNeg    : BOOL;
	dwAbs   : DWORD;
	sBuf    : STRING(80);
	dwWhole : DWORD;
	dwFrac  : DWORD;
END_VAR
// --- implementation ---
IF v < 0 THEN
	xNeg := TRUE;
	dwAbs := DINT_TO_DWORD(-v);
ELSE
	xNeg := FALSE;
	dwAbs := DINT_TO_DWORD(v);
END_IF

dwWhole := dwAbs / 100;
dwFrac  := dwAbs MOD 100;

sBuf := DWORD_TO_STRING(dwWhole);
sBuf := CONCAT(sBuf, '.');
IF dwFrac < 10 THEN
	sBuf := CONCAT(sBuf, '0');
END_IF
sBuf := CONCAT(sBuf, DWORD_TO_STRING(dwFrac));

IF xNeg THEN
	LogComponent.sNumFmt := CONCAT('-', sBuf);
ELSIF xPlus AND (v > 0) THEN
	LogComponent.sNumFmt := CONCAT('+', sBuf);
ELSE
	LogComponent.sNumFmt := sBuf;
END_IF

Fmt100 := TRUE;
END_METHOD
