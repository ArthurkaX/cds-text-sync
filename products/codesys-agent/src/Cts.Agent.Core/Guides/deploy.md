# Deploy

Deployment moves code from the project folder to the IDE, then to the PLC. Disconnect first if the IDE is online.

1. Edit `project-view/`, then run `cts import` to apply the changes to the IDE.
2. Run `cts build`; fix errors before downloading.
3. Run `cts download`, then check `cts status` or read a known variable to confirm the application is ready.

Simulation mode is controlled with `cts project simulate on` and `cts project simulate off`. A download after adding a POU, GVL, DUT, or other object with new symbols must be a full download so those symbols are exported to the running application. `cts download` forces a full download.

See `cts guide commands` under “PLC Lifecycle” for details, and `cts download --help` for options.
