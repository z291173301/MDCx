# embyfin-mcp - an Emby and Jellyfin MCP server, CLI and Go SDKs

[![GitHub release](https://img.shields.io/github/v/release/katbyte/embyfin-mcp?color=blueviolet)](https://github.com/katbyte/embyfin-mcp/releases/latest)
[![Go Version](https://img.shields.io/github/go-mod/go-version/katbyte/embyfin-mcp?color=00ADD8)](https://github.com/katbyte/embyfin-mcp/blob/main/go.mod)
[![License](https://img.shields.io/github/license/katbyte/embyfin-mcp?color=blue)](https://github.com/katbyte/embyfin-mcp/blob/main/LICENSE)
![build](https://github.com/katbyte/embyfin-mcp/actions/workflows/build.yaml/badge.svg)
![test](https://github.com/katbyte/embyfin-mcp/actions/workflows/pr-tests.yaml/badge.svg)
![live tests](https://github.com/katbyte/embyfin-mcp/actions/workflows/pr-integration.yaml/badge.svg)
![lint](https://github.com/katbyte/embyfin-mcp/actions/workflows/pr-golangci-lint.yaml/badge.svg)
[![coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/katbyte/embyfin-mcp/badges/coverage.json)](https://github.com/katbyte/embyfin-mcp/actions/workflows/coverage.yaml)

An [MCP](https://modelcontextprotocol.io) server, CLI and Go SDKs that **audit an
[Emby](https://emby.media) or [Jellyfin](https://jellyfin.org) library for the things that
actually go wrong, and fix what they find** - from Claude Code, Claude Desktop, or any other
MCP client.

Both servers already expose a large API, and an MCP server that wraps it lets a model browse
your library and read your watch state. This one does that too, but the reason it exists is
the layer above: **12 audits**, each a sweep over the whole library for one specific thing
that goes wrong in a real collection - unmatched films, wrong-year matches, duplicates, a
4K and a 1080p copy merged into one entry, a file whose runtime says it is not the film it
claims to be, a DVD rip still waiting for a better copy, an episode missing between two on
disk, a genre spelled three ways - returning a worklist rather than a dump, and naming the
tool that fixes it.

The same tools drive either server: `EMBYFIN_BACKEND` picks Emby or Jellyfin, the
differences between them live in one package, and every tool is tested against both.

### The audits

| audit | what it catches |
|---|---|
| `audit_all` | every audit in one call, counts only, so one call says where a library needs work - start here after a scan |
| `audit_missing_metadata_provider` | items with no tmdb/imdb/tvdb id: never matched, so nothing else can be filled in automatically; `item_identify` fixes them |
| `audit_missing_poster` | items with no primary image; `item_artwork` and `item_artwork_set` fix them |
| `audit_missing_overview` | items with no plot text, usually a failed match; `item_refresh` or `item_identify` fix them |
| `audit_year_mismatch` | items whose folder says `(2021)` while the matched metadata says 1984: the wrong edition, or the wrong film |
| `audit_duplicates` | separate entries sharing one tmdb/imdb id, in one library or across libraries, each group listing every copy with its path and quality |
| `audit_multiple_versions` | one entry the server has merged from several files - a 4K and a 1080p copy - which is what `audit_duplicates` cannot see (Jellyfin merges same-folder versions at scan time; Emby only when merged in its web client, so there the pair shows up in `audit_duplicates`) |
| `audit_runtime` | files whose runtime disagrees with what it should be: truncated downloads, wrong files, wrong matches. Episodes against the median of their season; movies against TMDB's runtime (needs `EMBYFIN_TMDB_KEY`, paged with `start_index`) |
| `audit_quality` | films and episodes worth replacing with a better copy: below a resolution (720 lines by default, so 480p and 576p rips), in a legacy codec (MPEG-2, XviD and DivX, WMV, VC-1), or below a bitrate when one is given; an item is judged by its best version, lowest resolution first |
| `audit_missing_episodes` | series with episodes missing: the numbers a season skips between the episodes on disk, whole seasons skipped, and, when the server records them, the episodes its provider lists without a file |
| `audit_spelling` | genres, tags and studios that mean the same thing spelled differently: `Sci-Fi` and `Sci Fi`, `Science-Fiction` and `Science Fiction`, a letter apart, or a studio cut short (`Warner Bros.` and `Warner Bros. Pictures`); each group names the spelling to keep, and `metadata_rename` merges it |
| `audit_unwatched` | the films, or series, no account on the server has watched, oldest additions first, optionally only those added more than some days ago: what to archive, or what to recommend |

The design principle: **detection is code, correction is judgment.** The server runs cheap
deterministic checks over the whole library and produces worklists; the AI reasons only about
the anomalies. Every response is a trimmed projection of what a decision needs, never the raw
API object (`BaseItemDto` runs to 150 fields; `item_get` returns about 15).

### What else is in the box

- **81 tools, in toolsets.** Search, browse by filter and inspect, identify and re-identify,
  batch edits and renames across the library, artwork, subtitles, watch state, progress, next
  up, favourites, per-user statistics, people, playlists, collections, remote control of
  playing devices, scans, tasks, logs and libraries - each in a toolset a session can load on
  its own, so a client spends about a thousand tokens of context by default rather than ten
  thousand.
- **Two Go SDKs.** `lib/emby` and `lib/jf` are complete typed clients for the Emby and
  Jellyfin APIs - every one of their 499 and 346 operations, generated from the servers' own
  OpenAPI documents,
  no dependencies outside the standard library, no knowledge of MCP - useful on their own,
  whether or not you care about AI. `lib/embyfin` is the thin layer on top that makes the
  two servers answer alike.
- **Tested against real servers.** Every tool runs against an actual Emby and an actual
  Jellyfin in Docker, the suite fails if a registered tool has no test, and the servers'
  calls out to TMDB and TheTVDB are recorded once and replayed, so CI needs no network.

## Installation

```bash
go install github.com/katbyte/embyfin-mcp@latest
```

Tested against Emby 4.10 and Jellyfin 12.0; both servers' current stable images are what the
live suites run.

## Configuration

All options can be passed as command-line flags, environment variables, or via a configuration file.

| Variable | Flag | Description |
|---|---|---|
| `EMBYFIN_BACKEND` | `--backend`, `-b` | `emby` (default) or `jellyfin` |
| `EMBYFIN_SERVER` | `--server`, `-s` | media server URL, e.g. `http://nas:8096` |
| `EMBYFIN_TOKEN` | `--token`, `-t` | API key (Emby: dashboard → Advanced → API Keys; Jellyfin: dashboard → API Keys) |
| `EMBYFIN_READ_ONLY` | `--read-only` | register only tools that never change server state |
| `EMBYFIN_ENABLE_DELETE` | `--enable-delete` | register `item_delete` (removes the media file) and `library_delete` |
| `EMBYFIN_TOOLSETS` | `--toolsets` | groups of tools to register, default `core`: `all`, `core`, `curation`, `watching`, `organise`, `remote`, `admin`, or a resource family like `item` (`core` is always included) |
| `EMBYFIN_ALLOW_TOOLS` | `--allow-tools` | only register these tools (names, `library_*` globs, or `essential`) |
| `EMBYFIN_DENY_TOOLS` | `--deny-tools` | never register these tools (names or globs such as `*_delete`) |
| `EMBYFIN_TMDB_KEY` | `--tmdb-key` | TMDB API key or read access token; enables the movie mode of `audit_runtime` |
| `EMBYFIN_LOG` | | log level (`WARN` default; `DEBUG`, `TRACE`, ...) |
| `EMBYFIN_LISTEN` | `--listen` | serve MCP over HTTP on this address (e.g. `:8080`) instead of stdio |
| `EMBYFIN_AUTH_TOKEN` | `--auth-token` | bearer token required on the HTTP endpoint (required with `--listen`) |
| `EMBYFIN_ALLOW_NO_AUTH` | `--allow-no-auth` | serve HTTP with no bearer token at all: anyone who can reach the port can use every tool |

An API key acts as the server, not as a user, so the tools that read or change watch state
take a `user` (name or id) and default to the first administrator.

### Configuration File

You can place a `.embyfin-mcp` file in your home directory `~/.embyfin-mcp` (for global settings)
or in your current directory `./.embyfin-mcp` (for per-project settings). Keys match the long flag
names using the `env` format:

```env
BACKEND=jellyfin
SERVER=http://nas:8096
TOKEN=ey...
```

## Usage

Quick connectivity check:

```bash
embyfin-mcp info
```

### Register with Claude Code

`.mcp.json`:

```json
{
  "mcpServers": {
    "embyfin": {
      "command": "embyfin-mcp",
      "args": ["serve"],
      "env": {
        "EMBYFIN_BACKEND": "jellyfin",
        "EMBYFIN_SERVER": "http://nas:8096",
        "EMBYFIN_TOKEN": "...",
        "EMBYFIN_TOOLSETS": "curation"
      }
    }
  }
}
```

Or from the shell:

```bash
claude mcp add embyfin -e EMBYFIN_SERVER=http://nas:8096 -e EMBYFIN_TOKEN=... -- embyfin-mcp serve
```

### Run as a service (HTTP transport)

`serve --listen :8080` serves the MCP Streamable HTTP transport at `/mcp` (plus `GET /healthz`)
instead of stdio. `EMBYFIN_AUTH_TOKEN` is required: clients must send `Authorization: Bearer
<token>`, and the server refuses to start without one unless `EMBYFIN_ALLOW_NO_AUTH=true` says
that anyone who can reach the port may use every tool. Register it from any machine:

```bash
claude mcp add --transport http embyfin http://nas:8080/mcp \
  --header "Authorization: Bearer $EMBYFIN_AUTH_TOKEN"
```

### Docker

Releases publish a multi-arch (amd64, arm64) image to `ghcr.io/katbyte/embyfin-mcp`, tagged
`vX.Y.Z`, `vX.Y` and `latest`. `docker-compose.yml` is the default always-on deployment: it runs
that image and reads secrets from a gitignored `.env` (copy `.env.example`). Adjust
`EMBYFIN_SERVER`, `EMBYFIN_BACKEND` and `TZ` in the compose file, then:

```bash
cp .env.example .env      # fill in EMBYFIN_TOKEN and EMBYFIN_AUTH_TOKEN
docker compose up -d
```

`make docker` builds the same image from source, tagged `embyfin-mcp`, with version info from
git. The image is alpine-based (so `docker exec -it embyfin-mcp sh` works), runs as a non-root
user and has a healthcheck against `/healthz`. The binary is the entrypoint, so `docker run --rm
ghcr.io/katbyte/embyfin-mcp info` works as a connectivity check with the `EMBYFIN_*` variables
passed via `-e`.

## MCP Tools

Tools are named resource-first (`library_*`, `item_*`, `audit_*`, `session_*`...) so they group
by what they act on. Every tool carries MCP annotations (read-only or destructive) and tools
that change server state say so in their descriptions. Wherever a tool takes a library, user,
session, playlist or collection it accepts a name as well as an id, and an unknown name comes
back as an error listing what exists. Timeframe-taking tools default to the last 60 days.

| Resource | Tools |
|---|---|
| server | `server_info`, `server_stats`, `server_activity`, `server_devices`, `server_logs`, `server_log` |
| tasks | `task_list`, `task_run` |
| libraries | `library_list`, `library_get` (counts by type), `library_search` (by title, with filters: library, genre, year, person, sort), `library_items` (browse by genre, tag, studio, rating, year and watch state, sorted and paged), `library_filters` (every genre, tag, studio, rating and year, with counts), `library_recent`, `library_genres`, `library_people`, `library_scan` (every library, or one), `library_create`, `library_edit` (rename, add and remove folders, switch nfo saving), `library_delete` |
| audits | the 12 audits in [the table above](#the-audits) |
| items | `item_get`, `item_find_by_metadata_id` (the definitive "do I already have this?"), `item_similar`, `item_refresh`, `item_edit`, `item_batch_edit` (the same genres, tags, studios or rating across many items; `add_*` and `remove_*` edit each item's own list), `item_instant_mix`, `item_last_watched`, `item_watch_history`, `item_set_watched`, `item_set_progress`, `item_set_favourite` |
| metadata | `metadata_rename` (a genre, tag or studio, everywhere it is used; renaming onto an existing value merges, `remove` drops it) |
| people | `person_get` (an actor, director or writer and everything the library holds with them in it) |
| identify | `item_identify` (candidates from the server's providers) → `item_identify_apply` |
| artwork | `item_artwork` (current images plus remote candidates) → `item_artwork_set` |
| subtitles | `item_subtitle_search` → `item_subtitle_download` |
| shows | `show_seasons`, `show_episodes`, `show_missing` (the provider's episodes the library lacks) |
| users | `user_list`, `user_get` (permissions, libraries, and how much they have watched), `user_history`, `user_next_up`, `user_in_progress` (with positions), `user_favourites`, `user_stats` (films and episodes watched, hours, series finished, top genres and series) |
| sessions | `session_list`, `session_play`, `session_command`, `session_message` |
| playlists | `playlist_list`, `playlist_get`, `playlist_create`, `playlist_edit` (rename, move an entry), `playlist_add`, `playlist_remove`, `playlist_delete` |
| collections | `collection_list`, `collection_get`, `collection_create`, `collection_edit` (rename, sort name, overview), `collection_add`, `collection_remove`, `collection_delete` |

`item_delete` (permanently removes the media file) and `library_delete` are only registered
when `--enable-delete` / `EMBYFIN_ENABLE_DELETE` is set. `--read-only` registers the 52 read
tools and nothing else, so a write tool is absent from `tools/list` rather than refused when
called.

### Choosing which tools load

**The default is `core`: seven read-only tools, about 1,100 tokens.** The whole surface is
around 10,700 tokens of tool definitions before anyone asks a question, which is a poor way to
spend a client's context by default. `--toolsets` / `EMBYFIN_TOOLSETS` loads the groups a session
actually needs, and `core` comes along with whatever else is asked for, because nothing else
can find a library or open an item.

**Curating a library needs `EMBYFIN_TOOLSETS=curation`** - the audits and everything that
fixes what they find. `EMBYFIN_TOOLSETS=all` restores every tool.

| toolset | tools | with core | ~tokens |
|---|---|---|---|
| `core` *(default)* | 7 | 7 | 1,100 |
| `remote` | 4 | 11 | 1,600 |
| `admin` | 12 | 19 | 2,400 |
| `watching` | 13 | 20 | 2,400 |
| `organise` | 14 | 21 | 2,700 |
| `curation` | 31 | 38 | 6,100 |
| `all` | 81 | 81 | 10,700 |

Tokens are what the model sees: each tool's name, description and input schema, measured over
a real `tools/list` at four bytes a token. Every tool also carries an output schema, another
10,700 tokens across `all`, but clients keep that to themselves to validate results rather than
sending it to the model.

`--toolsets` also takes a resource family - `library`, `item`, `audit`, `show`, `user`,
`person`, `metadata`, `session`, `playlist`, `collection`, `server`, `task` - which is every
tool with that prefix:

```sh
EMBYFIN_TOOLSETS=all                # every tool
EMBYFIN_TOOLSETS=curation           # audits plus everything that fixes what they find
EMBYFIN_TOOLSETS=watching,remote    # a client that plays things rather than curates them
EMBYFIN_TOOLSETS=audit              # read-only detection, nothing that writes
EMBYFIN_TOOLSETS=core,item,show     # core plus two whole families
```

`embyfin-mcp tools` prints what the current flags would register, grouped by toolset, and
needs no server:

```sh
embyfin-mcp tools                   # the default set
embyfin-mcp tools --toolsets all    # every tool
embyfin-mcp tools --read-only -q    # names only
```

### Narrowing further

`--allow-tools` and `--deny-tools` narrow whatever the toolsets left, and take comma-separated
tool names, globs with a leading or trailing `*`, or the `essential` preset (`library_list`,
`library_search`, `item_get`, `user_next_up`, `item_set_watched`):

```sh
EMBYFIN_ALLOW_TOOLS=essential
EMBYFIN_ALLOW_TOOLS=library_*,item_get,user_*
EMBYFIN_DENY_TOOLS=*_delete,session_*
```

A pattern that matches no tool aborts startup and names it, so a typo cannot silently hide a
tool.

### A typical curation session

1. `audit_all` says where the library needs work; `audit_missing_metadata_provider` lists
   the films never matched to a provider.
2. For each, `item_identify` returns candidates with year and ids; compare them with the
   file and `item_identify_apply candidate=N`.
3. `audit_year_mismatch` finds the wrong editions; the same two tools fix them.
4. `audit_missing_poster` and `item_artwork` / `item_artwork_set` fill the gaps.
5. `audit_duplicates` and `audit_multiple_versions` show what to prune;
   `audit_runtime` and `audit_quality` show what to re-download.
6. `audit_spelling` finds the genres, tags and studios typed several ways; `metadata_rename`
   merges each group, and `item_batch_edit` puts the right genre on a whole franchise.
7. `audit_missing_episodes` lists the gaps in each series to fill.

## Using the clients on their own

`lib/emby` and `lib/jf` are complete Go clients for the Emby and Jellyfin APIs that depend on
nothing but the standard library, the shared base client in `lib/client` and
`go-kt/version`, and know nothing of MCP. If you only want to talk to one of the servers from
Go, take the package and ignore the rest:

```go
import "github.com/katbyte/embyfin-mcp/lib/jf"

c, err := jf.New("http://nas:8096", os.Getenv("EMBYFIN_TOKEN"))
res, err := c.GetItems(ctx, jf.GetItemsOperationOptions{
    Recursive: new(true), IncludeItemTypes: []jf.BaseItemKind{jf.BaseItemKindMovie}, Limit: 50,
})
for _, it := range res.Model.Items { ... }

all, err := c.GetItemsComplete(ctx, jf.GetItemsOperationOptions{Recursive: new(true)}) // every page
```

They are generated from the servers' own OpenAPI documents (`docs/`, see
[docs/README.md](docs/README.md)) by `internal/pandorest`, a generator kept in this
repository and modelled on [hashicorp/pandora](https://github.com/hashicorp/pandora): an
importer normalises each spec into checked-in definitions (`api-definitions/`, one file per
tag) through named workarounds for the spec's known bugs, a differ reports what a spec
refresh changes, and a generator writes one file per operation and model from the
definitions. That is **a method for every one of Emby's 499 operations and Jellyfin's
346**, each with typed options, a typed body, a `{Model, HttpResponse}` result, the
status codes the operation documents (anything else is an error), and a `Complete` pager on
every paged list. `make apicheck` proves the coverage claim against the spec, `make gencheck`
(and the unit tests) fail when the generated code is stale, and the integration suite proves
the shapes **against a running server** - which is the only thing that catches the server
changing shape underneath a spec that says otherwise. See
[internal/pandorest/README.md](internal/pandorest/README.md).

`lib/embyfin` is the backend-neutral layer the tools use: the handful of item, library, user,
session and provider operations a curation session needs, answering the same way on both
servers. [docs/README.md](docs/README.md) records where the two servers differ and how it
hides that.

## Development

```bash
make            # fmt + build
make check-all  # build + unit tests + both live suites on both servers (needs docker) + every linter
```

### Tests

`make test` is hermetic and fast. It covers the pure logic - tool registration and toolsets,
the audit heuristics, the CLI's flags, config files and HTTP auth, the record/replay proxy -
and, against a canned server, the requests the base client, the two generated clients and the
neutral `lib/embyfin` build for each server and the answers they decode. It also re-imports
both specs and regenerates both SDKs to check the checked-in code is current, and applies every
importer workaround twice to prove each one notices when its bug is fixed.

Everything else runs against **a real Emby and a real Jellyfin in Docker**, because a stub can
only confirm what you already believed. Two suites, each in its own container, each run
against both servers:

| | Covers | Command |
|---|---|---|
| `integration/` | the `lib/emby` and `lib/jf` clients: bespoke tests that the calls the tools rely on decode with their fields populated and do what they say, and a sweep that calls every GET in each document against the server and classifies the ones that cannot answer in a container | `make testacc-integration` |
| `acceptance/` | the tools: name resolution, projections, audits, provider flows, and journeys that chain them (edits during a library scan and through a refresh, every fixable audit fixed and re-audited, the fixes each audit names with the fetchers on and off, a client's playback reaching the history tools, a series watched through, a user restricted to one library, a library's whole life, deletes letting go of what held their items, writes repeated and made in parallel, copies of a film watched, a genre added, renamed and removed, lookups that must change nothing), and the built binary itself over stdio and HTTP (flags and environment reaching the server, nothing but protocol on stdout, the bearer check, clean shutdown, refusing to start without a token) | `make testacc-acceptance` |

```bash
make testacc                        # both suites on both servers, each in a throwaway container
make testacc-acceptance-jellyfin    # one suite on one server
make check-all                      # build + unit + live suites + every linter
make cover                          # every suite merged into one coverage number
```

Coverage has to span every suite or it lies: `go test -cover ./...` reports a fraction for
`tools/`, because almost everything real happens in the live suites behind the `integration`
tag. `make cover` runs each into its own binary coverage directory and merges them with
`go tool covdata` - stdlib tooling, no third-party merger - which is what the badge reports.
The generated `lib/emby` and `lib/jf` are left out of the number and reported on a line of
their own: they are one method per operation, and the integration suite exercises the ones
the tools rely on rather than all 781.

**Every tool is exercised on both servers.** Tool coverage is enforced rather than claimed: the
acceptance suite records every tool it calls and fails if the server registered one nothing
called, so a new tool cannot ship untested. The servers' own calls out to TMDB, TheTVDB, OMDb
and the image CDNs go through a record/replay proxy (`lib/providerproxy`) - the containers are
started with `HTTPS_PROXY` pointing at it and trust its certificate authority - so neither suite
needs a network:

```bash
make record         # re-record the cassettes against the real providers (EMBYFIN_TMDB_KEY for the runtime audit)
make record-check   # check the cassettes still match, without rewriting them
```

`record-check` compares the *shape* of live responses against the recordings - renamed fields,
vanished fields, changed types - and ignores values, so it goes red when a provider changes its
contract rather than when a poster changes.

Fixtures are generated, never committed: `scripts/testenv.sh` writes one-second videos with
`ffmpeg` under `~/.cache/embyfin-mcp` (`EMBYFIN_TEST_DATA` to move them - not `$TMPDIR`, which
Docker Desktop does not share), each with a Kodi-style `.nfo` carrying the real film's ids,
completes the server's setup wizard, mints an API key and a second user, and prints the
environment. The suites create the libraries through `library_create` and fill them with
`library_scan`, so building the fixtures is itself part of the coverage. Two libraries are
clean and fetch their metadata from the providers (through the proxy), so the audits have
something to leave alone and identify has something to find; the two `Messy` libraries keep
the providers off and are seeded with every defect the audits exist to find - a film with no
ids, one with no plot and no poster, a folder whose year disagrees with its metadata, one
film twice, one film in two versions, a runtime that cannot be right - and each audit has a
test against them. A fifth library holds music - four artists, five albums, twenty one-second
tracks tagged with the real MusicBrainz ids, art beside and inside them - so the mixes have
something to work with and the audits can be pointed at albums; it too keeps the providers
off, and it carries a rip with no art and a genre spelled two ways.
`scripts/testenv.sh fixtures` writes just the media tree if you want to look at the layout.
Requires docker, ffmpeg, jq and openssl; the suites skip when `EMBYFIN_SERVER` and
`EMBYFIN_TOKEN` are unset, so they never fail for want of a daemon.

Dev tools are pinned in `.tools/go.mod` (actionlint in `.tools/actionlint/go.mod`) and built
into `.tools/bin` by make. On a noexec checkout point `TOOLS_BIN` somewhere local, e.g.
`make TOOLS_BIN=~/.cache/embyfin-mcp/bin lint`.
