# zph

`zph` is the lightweight command-line client for Zephyr. It supports Python
3.7 and newer and has no runtime dependencies outside Python's standard
library.

```console
python3 -m pip install --user --upgrade \
  'https://github.com/solidsgroup/zephyr/archive/refs/heads/master.zip#subdirectory=cli'
export PATH="$HOME/.local/bin:$PATH"
zph login https://zephyr.solids.group
zph import .
zph add /scratch/alamo-results
zph add 'output*'
zph sync /scratch/alamo-results
zph watch . --pid 12345
zph put '*.png'
zph put output/myfile.png
zph get output.481516
```

The archive install does not require `pipx` or `git`. Omit `--user` when using
an activated virtual or Conda environment. Future upgrades use the same Python
environment automatically:

```console
zph --upgrade
```

On a cluster without usable packaging tools or internet access from compute
nodes, clone or copy the repository once and build a self-contained executable
using only the Python standard library:

```console
python3 cli/install.py --prefix "$HOME/.local"
export PATH="$HOME/.local/bin:$PATH"
zph --version
```

The resulting `~/.local/bin/zph` is a single zip application. It can be copied
to another machine with the same or a newer Python interpreter; it does not
need a virtual environment, `pip`, `setuptools`, or `wheel`.
Running `zph --upgrade` from that installation requires `pip` on the login node
and transitions it to the regular user installation above.

Login uses a short-lived browser link. If a browser cannot be opened on the
machine running `zph`, copy the printed URL to any browser, sign in, and return
to the waiting terminal. No API token needs to be copied through the clipboard.

Every directory is identified by the `HASH` in its Alamo `metadata` file. The
CLI does not create a Zephyr-specific identity file in the run directory.

`zph add PATH...` expands wildcard patterns, walks every matching path
recursively, and imports each directory containing an Alamo `metadata` file.
Both `zph add output*` and `zph add 'output*'` work. Each result is clearly
labeled as `ADDED`, `UPDATED`, `SKIPPED`, or `ERROR`; `thermo.dat` is imported
when present, along with Alamo's `out.log` and `diff.patch`. Watchers refresh
the captured terminal output as the simulation runs. Interactive output uses
color; set `NO_COLOR=1` for plain output. Recursive scans prune numbered BoxLib
data trees such as `00000cell` and `00000node` without entering them. A
directory containing `metadata` is treated as a complete run root, so its
potentially large descendants are not scanned. Alamo source/vendor trees,
virtual environments, VCS data, and package caches are also excluded. Bulk
registration resolves the server catalog once and synchronizes up to four runs
concurrently.

`zph sync PATH...` finds every metadata-rooted copy recursively, including
several copies with the same HASH, then inventories filenames below each run.
It records the absolute path, site/host, file count, path fingerprint, and the
presence of numbered BoxLib `cell` or `node` trees. The normal scan avoids
per-file stat calls and uses `~/.config/zephyr/sync-cache.json` to skip directory
reads when all cached directory timestamps are unchanged. Use
`zph sync --deep PATH` to additionally recompute total bytes and a size/mtime
fingerprint. This is an inventory operation: it never uploads the raw files.
Old locations remain visible with their last update time after a copy is moved.
Set `ZEPHYR_SITE` to a stable cluster or filesystem name if the hostname is too
specific; `SLURM_CLUSTER_NAME` is used automatically when available.

`zph put` looks for `metadata` beside each target file. Thus
`zph put output/myfile.png` automatically selects the run described by
`output/metadata`, and files from multiple run directories can be uploaded in
one command. Pass `--directory RUN_DIRECTORY` to override this association.

`zph get` accepts an output-directory name, HASH, or Zephyr UID and preserves
the recorded output-directory name by default. Ambiguous names open a numbered
chooser. Existing local destinations open a second chooser with safe rename,
alternate-path, merge/overwrite, and cancel options. Non-interactive jobs can
select the behavior with `--output PATH`, `--rename`, or `--overwrite`.
Successful gets and puts refresh the same copy inventory as `zph sync`.

See the repository's main README for the complete workflow.
