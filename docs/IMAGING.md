# Imaging (DICOM) and the Serenity link

LabSync's imaging module is a DICOM storage node for the local network. Imaging devices (CT, MRI, X-ray,
ultrasound) send studies to it the same way they send to a PACS. It keeps every image on disk until each
destination has confirmed it, so a Serenity outage or a dropped internet line never loses an image. It was
ported from the Serenity DICOM Communicator and runs in the same process as the analyzer engine, with its own
threads, queue and folder: a large study never delays a lab result, and an analyzer problem never stops imaging.

```
  CT / US / X-ray ──DICOM (LAN)──► LabSync imaging ──HTTPS + device key──► Serenity
                                     │  disk queue, retries, holds
  Analyzers ──ASTM / HL7 (LAN)──► LabSync engine ──HTTPS + device key──► Serenity (lab results)
                                     └──optional DICOM copy──► any other node (e.g. PostDICOM)
```

## What it does

| | |
|---|---|
| DICOM services | C-STORE SCP (all standard storage classes, any transfer syntax) and C-ECHO |
| Port | 11113 by default (avoids 104 and 11112). Bound exclusively: on Windows `SO_EXCLUSIVEADDRUSE`, so a port already used by PostDICOM or a PACS is reported instead of silently shared, and nobody can join ours. |
| Who may send | Devices registered in Serenity to send through this LabSync (downloaded with every heartbeat and kept on disk for offline starts), plus devices added on site. Checked by calling AE title and, optionally, IP or range. Others are refused at association time. |
| No data loss | Each image is written (fsync, atomic rename) and recorded in `imaging.db` before the device is told "Success". Files left on disk after a crash are re-queued at start. Below the free-space floor the device is told "out of resources" and retries later. |
| Sending to Serenity | `POST {url}/device-gateway/dicom/instances`, multipart/related streamed from disk, images of a study together, at most 40 MB per request (one image per request after a 413). |
| Outcomes | stored: done · hold (no matching order yet): retried 5, 15, 30 min then hourly for 7 days, then failed · retry: 30 s up to 15 min · reject: failed. "Retry" in the Imaging tab sends again at once. Re-sending an image from the device replaces the held copy. |
| Offline | Serenity unreachable or answering 5xx/429: the destination pauses (15 s up to 5 min); nothing counts against the images. |
| Copies | Optional extra DICOM destinations (C-STORE), for devices that can only send to one place. |
| Clean-up | Delivered images are deleted after 7 days (configurable). Undelivered images are never deleted. |
| Settings changes | Only the parts that changed restart: a new port moves the listener, new copy destinations restart their senders, analyzer changes leave imaging alone. |

## The Serenity link

One LabSync install is one device in Serenity (kind "Serenity communicator"). The setup code
(`SRN1.…`, shown once in Serenity) carries the API address and the device key; the key is stored in the
operating system's credential store. Everything uses the header `X-Device-Key`:

| Call | Purpose |
|---|---|
| `POST /device-gateway/heartbeat` | Every 60 s: status of instruments, the lab outbox and the imaging queue. The answer names the imaging devices allowed to send through this LabSync. |
| `POST /device-gateway/dicom/instances` | Images |
| `POST /device-gateway/lab-results` | Analyzer results (destination type `serenity`), in the 1.x JSON shape Serenity reads, with `Idempotency-Key` = the report id |

A refused key (401/403) never parks results or images: they stay queued and go once a new setup code is
entered.

## Data

`data/imaging/` in the LabSync data folder: `imaging.db` (queue), `images/` (received files, by day and study),
`state.json` (devices last downloaded from Serenity). Patient data is stored here until delivered; use BitLocker
(Windows) or FileVault (macOS) on the site computer.

## Testing

`pytest tests/test_imaging.py` runs real DICOM associations (pynetdicom as the modality) against a fake Serenity
gateway, and the dcmtk tools (`storescu`, `echoscu`) when installed.
