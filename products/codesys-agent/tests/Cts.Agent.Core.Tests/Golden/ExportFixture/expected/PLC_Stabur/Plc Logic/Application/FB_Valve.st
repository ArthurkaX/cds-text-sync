FUNCTION_BLOCK FB_Valve
VAR
	xOpen : BOOL;
END_VAR
END_FUNCTION_BLOCK

PROPERTY P_Open : BOOL
GET
// --- implementation ---
P_Open := xOpen;
END_GET
SET
// --- implementation ---
xOpen := P_Open;
END_SET
END_PROPERTY

ACTION A_Reset:
xOpen := FALSE;
END_ACTION

METHOD M_Toggle : BOOL
// --- implementation ---
xOpen := NOT xOpen;
M_Toggle := xOpen;
END_METHOD
