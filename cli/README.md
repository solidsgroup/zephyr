# zph

`zph` is the lightweight command-line client for Zephyr. It supports Python
3.7 and newer and has no runtime dependencies outside Python's standard
library.

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

On a cluster without `pipx`, recent packaging tools, or internet access from
compute nodes, clone or copy the repository once and build a self-contained
executable using only the Python standard library:

```console
python3 cli/install.py --prefix "$HOME/.local"
export PATH="$HOME/.local/bin:$PATH"
zph --version
```

The resulting `~/.local/bin/zph` is a single zip application. It can be copied
to another machine with the same or a newer Python interpreter; it does not
need a virtual environment, `pip`, `setuptools`, or `wheel`.

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
color; set `NO_COLOR=1` for plain output. Recursive scans prune numbered BoxLib
data trees such as `00000cell` and `00000node` without entering them. A
directory containing `metadata` is treated as a complete run root, so its
potentially large descendants are not scanned. ALAMO source/vendor trees,
virtual environments, VCS data, and package caches are also excluded. Bulk
registration resolves the server catalog once and synchronizes up to four runs
concurrently.

`zph put` looks for `metadata` beside each target file. Thus
`zph put output/myfile.png` automatically selects the run described by
`output/metadata`, and files from multiple run directories can be uploaded in
one command. Pass `--directory RUN_DIRECTORY` to override this association.

See the repository's main README for the complete workflow.
