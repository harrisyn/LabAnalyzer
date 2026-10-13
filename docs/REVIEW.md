# LabSync 2.0: review of 1.x and what changed

This records what the review of the 1.x code base found and how 2.0 addresses it.

## Summary

1.x could only work end to end for one configuration: a Sysmex XN-L sending well-formed single-frame ASTM
over TCP, on Windows, with an HTTP endpoint. Every other analyzer type failed at start-up, valid ASTM traffic
from strict instruments would have been rejected because of a checksum bug, macOS could not start, and the
repository contained a live API key. The core (protocols, transport, storage, delivery) has been rewritten
around a protocol-independent result model, with an automated test suite. The UI was rebuilt on the same
foundations.

## Findings in 1.x

### Blocking defects

| # | Finding | Where (1.x) | Effect |
|---|---|---|---|
| 1 | The TCP server constructed every parser with `config=` and called `handle_data()`, but only the Sysmex parser had either. The others exposed `async process_data()` and no `config` parameter. | `src/network/tcp_server.py`, `src/protocols/*` | Mindray, HumaCount, Roche, Abbott, Siemens, Response and HL7 configurations crashed when a connection was opened. |
| 2 | ASTM checksum computed as XOR including STX. The standard is the modulo-256 sum of bytes from the frame number through ETX/ETB. | `src/protocols/astm_parser.py` | Every correct frame from an instrument that checks host replies would be NAKed; frames were never really validated. |
| 3 | One `recv()` treated as one frame: no stream buffering. | `tcp_server.py`, parsers | Frames split across TCP segments, or several frames in one segment, were lost or mis-parsed. Common on real networks and serial bridges. |
| 4 | A single parser instance shared by every connected client. | `tcp_server.py` | Two analyzers (or a reconnect) interleaved state and corrupted results. |
| 5 | No ETB continuation, frame-number or duplicate-frame handling; no ENQ/EOT state machine or timeouts. | Sysmex path | Long results (more than 240 characters a frame) were truncated; retransmits were stored twice. |
| 6 | Config and database paths built with `Path(os.getenv('LOCALAPPDATA'))`. | `src/utils/config.py`, `src/database/` | `TypeError` at start-up on macOS. Logs were written next to the source code, which is read-only once installed. |

### Security and privacy

| # | Finding | Effect |
|---|---|---|
| 7 | `config.json` with a real API key and the staging endpoint was committed. | The key is in git history and must be rotated. 2.0 removes the file, ignores it, and keeps secrets in the OS credential store. |
| 8 | `aiohttp` called with `ssl=False`. | Patient results were sent with TLS verification disabled (man-in-the-middle exposure). 2.0 verifies against the OS trust store, supports a custom CA bundle, and requires confirmation to turn verification off. |
| 9 | Updater downloaded and executed installers without any integrity check. | A compromised download path ran arbitrary code. 2.0 requires a matching `SHA256SUMS` entry. |
| 10 | XML parsed with `xml.etree` (Abbott parser). | Entity-expansion attacks. 2.0 uses `defusedxml`. |
| 11 | Secrets stored in plain text in the config file. | 2.0 stores them in Windows Credential Manager / macOS Keychain and writes the config file with user-only permissions. |

### Correctness

- OAuth2 expiry used `datetime.timedelta` on the `datetime` class (attribute error on first refresh).
- The daily scheduled sync computed the next run with `day + 1`, which fails at month end.
- SQL used the literal `'-? days'`, so the retention parameter was never bound.
- Results queries were capped at 100 rows with no paging; older results were invisible.
- HL7: an always-true message-type check, an operator-precedence bug in the ACK builder, and OBX segments not
  grouped under their OBR.
- The README listed Abbott ARCHITECT as POCT1-A; it uses ASTM (LIS2-A2).
- The Sysmex scattergram "Huffman decoder" was speculative and produced images unrelated to the data.
- Failed deliveries were only marked as not synced. There was no automatic retry or backoff, so recovering
  from an endpoint outage meant resending patient by patient from the GUI.

### Build and release

- Two overlapping workflows (`build.yml`, `release.yml`) built different artefacts.
- macOS was built `--onefile` into a `.app`, which macOS does not launch correctly and cannot be notarised.
- The workflow uploaded `LabSync-Setup.exe` while Inno Setup produced `LabSync-Setup-<version>.exe`.
- Heavy or unused dependencies (`numpy`, `matplotlib`, `nest_asyncio`, and `asyncio` from PyPI, which shadows
  the standard library on some installs).

## 2.0 design

- **Sans-I/O protocol handlers.** Each handler consumes bytes and produces a canonical `LabMessage`
  (patients, specimens, observations, attachments, queries). Transport, storage and delivery never see protocol
  details, so a new instrument is a profile or a handler, nothing else.
- **One handler per connection**, driven by a runner that owns the TCP server/client or serial port, ticks
  protocol timers, and reconnects with backoff.
- **Store first, deliver after.** Messages are written to SQLite (WAL) before anything else. A transactional
  outbox fans each report out to its destinations; workers retry with exponential backoff and jitter, honour
  real-time/interval/cron schedules, and survive restarts.
- **Profiles.** About 50 instrument profiles carry protocol, link and field-position defaults; any of them can
  be overridden per device.
- **GUI on a background engine.** The asyncio engine runs on its own thread; the Tk interface reads an event
  queue, so a slow endpoint or a busy analyzer never freezes the window.
- **Compatibility.** 1.x configurations migrate automatically (backup kept), and existing receivers keep
  getting the 1.x JSON shape via the `legacy` payload format.

## Verification

- 45 automated tests covering ASTM framing (checksums, ETB, frame wrap, byte-by-byte and coalesced delivery,
  NAK/retransmit, duplicates, unframed records, custom delimiters), LIS2-A2 records for Sysmex, Roche and
  multi-patient messages, QC detection, host queries, HL7 (Mindray ORU, chunked MLLP, ACK, encapsulated
  images, QRY/QCK/DSR, ORU round trip), POCT1-A conversations and XML entity rejection, Beckman AU, Dimension,
  regex capture, the outbox lifecycle, HTTP/OAuth2/MLLP/file senders, config migration and secrets, the CLI,
  and an end-to-end run from a simulated analyzer socket to an HTTP endpoint.
- The GUI was exercised against the ASTM, HL7 and POCT1-A simulators; every tab and dialog was checked.
- The PyInstaller build was produced and smoke-tested on Linux; CI builds and smoke-tests Windows and macOS.

## Needs on-site validation

These were implemented from public specifications and cannot be proven without the instrument:

- **Beckman Coulter AU** online format (field widths differ by model and site configuration; adjustable with
  options) and **Siemens Dimension** host interface: marked experimental.
- **Mindray DSR^Q03** order download: field layout follows Mindray's published LIS guide; confirm with a BS or
  BC analyzer in bidirectional mode.
- Per-site ASTM field positions (where the LIS barcode sits in the O record) for beta profiles. The message
  viewer and `labsync-cli parse` make this a few minutes' work with one capture.

## Follow-ups

- Windows code signing (Authenticode) in the release workflow once a certificate is available.
- A universal2 or Intel macOS build if Intel Macs are in use.
- Optional Windows service mode (the headless mode is ready for NSSM or a scheduled task today).
