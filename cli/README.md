# zph

`zph` is the lightweight command-line client for Zephyr. It has no runtime
dependencies outside Python's standard library.

```console
pipx install 'git+https://github.com/solidsgroup/zephyr.git#subdirectory=cli'
zph login https://zephyr.solids.group
zph import .
zph watch . --pid 12345
zph put '*.png'
zph get RUN_ID
```

Login uses a short-lived browser link. If a browser cannot be opened on the
machine running `zph`, copy the printed URL to any browser, sign in, and return
to the waiting terminal. No API token needs to be copied through the clipboard.

See the repository's main README for the complete workflow.
