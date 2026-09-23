# Changelog

## 0.1.1 (2026-09-15)

No code changes. 0.1.0 published its binaries and image but not the Homebrew
formula, because the tap token was not set; this release runs that path with
the token in place.

## 0.1.0 (2026-09-15)

Initial release.

- **81 tools** for Emby and Jellyfin, in toolsets: 12 audits, identify, artwork, subtitles,
  metadata edits, watch state, playlists, collections, sessions and server admin. `core` (7
  read-only tools) is the default; `--toolsets`, `--allow-tools`/`--deny-tools`, `--read-only`
  and `--enable-delete` decide the rest.
- **CLI**: `serve`, `info`, `tools`, `version`. Flags, `EMBYFIN_*` environment variables or a
  `.embyfin-mcp` file.
- **Transports**: stdio, or Streamable HTTP with `--listen` (bearer token required). Alpine
  Docker image at `ghcr.io/katbyte/embyfin-mcp`, plus `docker-compose.yml`.
- **Two generated Go SDKs**, `lib/emby` (Emby 4.10, 499 operations) and `lib/jf` (Jellyfin
  12.0, 346), written by `internal/pandorest` from the servers' own OpenAPI documents, over a
  shared base client. `lib/embyfin` is the thin layer that makes both servers answer alike.
- **Tested against real servers**: unit tests, an SDK suite and a tool suite against Emby and
  Jellyfin in Docker, with provider calls recorded and replayed. Every registered tool must
  have a test, every GET is swept, and `make cover` merges the lot into the coverage badge.
