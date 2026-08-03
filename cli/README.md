# zph

`zph` is the lightweight command-line client for Zephyr. It has no runtime
dependencies outside Python's standard library.

```console
pipx install 'git+https://github.com/solidsgroup/zephyr.git#subdirectory=cli'
zph login https://zephyr.solids.group
zph import .
zph add /scratch/alamo-results
zph add 'output*'
zph watch . --pid 12345
zph put '*.png'
zph put output/myfile.png
zph get HASH
```

Login uses a short-lived browser link. If a browser cannot be opened on the
machine running `zph`, copy the printed URL to any browser, sign in, and return
to the waiting terminal. No API token needs to be copied through the clipboard.

Every directory is identified by the `HASH` in its ALAMO `metadata` file. The
CLI does not create a Zephyr-specific identity file in the run directory.

`zph add PATH...` expands wildcard patterns, walks every matching path
recursively, and imports each directory containing an ALAMO `metadata` file.
Both `zph add output*` and `zph add 'output*'` work. Each result is clearly
labeled as `ADDED`, `UPDATED`, `SKIPPED`, or `ERROR`; `thermo.dat` is imported
when present, along with ALAMO's `out.log` and `diff.patch`. Watchers refresh
the captured terminal output as the simulation runs. Interactive output uses
color; set `NO_COLOR=1` for plain output.

`zph put` looks for `metadata` beside each target file. Thus
`zph put output/myfile.png` automatically selects the run described by
`output/metadata`, and files from multiple run directories can be uploaded in
one command. Pass `--directory RUN_DIRECTORY` to override this association.

See the repository's main README for the complete workflow.
