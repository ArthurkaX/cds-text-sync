---
title: Overridable method called from FB_Init
since: 3.1.0
related: [CTS0085]
---

## What it is

`FB_Init` calls a method that is overridden by a known derived FB:

```st
METHOD FB_Init : BOOL
    Configure();
END_METHOD
```

If `FB_Derived` overrides `Configure`, the call can dispatch to the derived
implementation during base initialization.

## Why it is dangerous

The derived FB's fields may not yet be ready when its override runs. The
failure is usually startup-only and can depend on which instance is being
created.

The rule requires an observed `EXTENDS` relationship and an observed method
override. Explicit `SUPER^` calls are treated as statically bound and are not
reported.

## Example

```st bad 1
METHOD FB_Init : BOOL
// cts:owner FB_Base
// cts:fb FB_Base
// cts:fb FB_Derived extends FB_Base
// cts:method FB_Base: Configure
// cts:method FB_Derived: Configure
    Configure(); // overridden by a derived FB // cts:here
END_METHOD
```

```st good
METHOD FB_Init : BOOL
// cts:owner FB_Base
// cts:fb FB_Base
// cts:fb FB_Derived extends FB_Base
// cts:method FB_Base: Configure
// cts:method FB_Derived: Configure
    SUPER^.Configure();
END_METHOD
```

## When ignoring is legitimate

Ignore only when the overridden method is intentionally safe before derived
fields are initialized. Prefer moving the call to the cyclic phase.

## How to fix

Keep `FB_Init` limited to base-field initialization. Move polymorphic work to
the first cyclic call after construction, or call the base implementation
explicitly with `SUPER^` when that is the intended behavior.
