# Zephyr protocol

The server owns the versioned `/api/v1` HTTP/JSON protocol. The `zph` client
does not import server code. Compatibility is advertised at `/api/v1/meta`
and tested with request/response fixtures in this directory.

Additive fields may be introduced within protocol 1.0. Removing or changing
the meaning of a field requires a new protocol version.
