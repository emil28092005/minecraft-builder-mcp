# Isolated material registry regression probe

This optional test plugin exercises the **installed production plugin** through reflection. It is excluded from Maven modules and never installed by the development server launcher or this builder.

It verifies every registered block default, every catalog description, and each distinct state obtained by varying one property at a time. Property cases cover fresh placement, changing an existing block of the same material, and exact private snapshot restoration. It also verifies that preparation does not modify the world. This is not a Cartesian enumeration of all property combinations or a test of later game ticks.

Build from the repository root after the development Paper runtime and JDK have been prepared:

```bash
python3 scripts/material-registry-probe/build.py
```

The only build outputs are under `.runtime/material-registry-probe/`. Use `--paper-home PATH` to select a prepared Paper installation for its dependency libraries and `--java-home PATH` to select another JDK 25 or newer.

Install **only into a disposable isolated test server**, using the pinned Paper version and the production plugin JAR being tested:

```bash
cp .runtime/material-registry-probe/material-registry-probe.jar .runtime/material-test-server/plugins/
```

Start or restart that isolated server, then enter `registryprobe` in its server console. The plugin does nothing on startup and ignores player invocations. It requires port **25576**, world **`world`**, and air at **(4, 100, 4)** and **(5, 100, 4)**. It temporarily uses the second position as a stone anchor, then restores both positions; the anchor makes `cave_air` and `void_air` observable because Minecraft treats entirely empty sections as ordinary air. Do not use a valuable world just because it happens to match these guards.

Read `plugins/MaterialRegistryProbe/report.json` in the isolated server directory. A successful report has matching default/property/catalog counts, `anchor_restored: true`, `fatal: null`, and zero failures. Reports contain only material/state identifiers, counts, timings and exception types—no block-entity payloads. The probe caps property cases at 30,000, execution at 35 seconds, and detailed failures at 128. The console command runs on the server thread; the test server should have no players. Remove the test plugin after use.

The initial Paper 26.2 verification covered 1,196 block defaults, 186 block-entity defaults, and 5,392 distinct property cases in approximately three seconds. These counts are observations, not hardcoded expectations; the probe follows the runtime registry.
