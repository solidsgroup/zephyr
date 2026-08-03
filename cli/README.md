# zph

`zph` is the lightweight command-line client for Zephyr. It has no runtime
dependencies outside Python's standard library.

```console
pipx install zph
zph login https://zephyr.solids.group
zph import .
zph watch . --pid 12345
zph put '*.png'
zph get RUN_ID
```

See the repository's main README for the complete workflow.
