{attribute 'qualified_only'}
{attribute 'symbol' := 'none'}
VAR_GLOBAL
	BITBENCH : STRING := 'BitBench';	// component name in the runtime log
	sNumFmt  : STRING(80);				// FB_Logger.Fmt100 puts the formatted number here

	logger : FB_Logger;					// the logger itself (production sample)
END_VAR
