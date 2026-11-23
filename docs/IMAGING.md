# Imaging (DICOM)

LabSync's imaging module is a DICOM storage node for the local network. Imaging devices (CT, MRI, X-ray,
ultrasound) send studies to it the same way they send to a PACS. It keeps every image on disk until each
destination has confirmed it, so an outage or a dropped internet line never loses an image. It runs in the same
process as the analyzer engine, with its own threads, queue and folder: a large study never delays a lab result,
and an analyzer problem never stops imaging.

```
  CT / US / X-ray ──DICOM (LAN)──► LabSync imaging ──► each destination you add:
                                     │  disk queue,       · a PACS or any DICOM node (C-STORE)
                                     │  retries, holds    · a DICOMweb server (STOW-RS over HTTPS)
                                     │                    · a destination added by an integration plugin
  Analyzers ──ASTM / HL7 (LAN)──► LabSync engine ──► REST / FHIR / HL7 / folder / plugin destinations
```

## What it does

| | |
|---|---|
| DICOM services | C-STORE SCP (all standard storage classes, any transfer syntax) and C-ECHO |
| Address | AE title `LABSYNC` and port 11113 by default (the port avoids 104 and 11112). The port is bound exclusively: on Windows `SO_EXCLUSIVEADDRUSE`, so a port already used by a PACS or another communicator is reported instead of silently shared, and nobody can join ours. |
| Who may send | Devices added on site (calling AE title and, optionally, IP or range), plus devices sent down by a turned-on integration (kept on disk for offline starts). Others are refused at association time. |
| No data loss | Each image is written (fsync, atomic rename) and recorded in `imaging.db` before the device is told "Success". Files left on disk after a crash are re-queued at start. Below the free-space floor the device is told "out of resources" and retries later. |
| Batches | Images of a study go together, at most 40 MB per request over HTTPS (one image per request after a 413). |
| Outcomes | stored: done · hold (the destination isn't ready yet, e.g. no matching order): retried 5, 15, 30 min then hourly for 7 days, then failed · retry: 30 s up to 15 min · reject: failed. "Retry" on the Imaging page sends again at once. Re-sending an image from the device replaces the held copy. |
| Offline | A destination that can't be reached, answers 5xx/429 or refuses the credentials pauses (15 s up to 5 min); nothing counts against the images. |
| Clean-up | Delivered images are deleted after 7 days (configurable). Undelivered images are never deleted. |
| Settings changes | Only the parts that changed restart: a new port moves the listener, changed destinations restart their senders, analyzer changes leave imaging alone. |

## Destinations

| Type | Settings | Notes |
|---|---|---|
| DICOM node | AE title, host, port | C-STORE with LabSync's AE title as the caller: add LabSync as a sender on the receiving node. Works with a PACS, Orthanc, or a cloud PACS communicator on the same network (for example PostDICOM's). **Test connection** sends a C-ECHO. |
| DICOMweb server | URL of the DICOMweb root, sign-in (none, basic, bearer token, API key header), TLS | STOW-RS: `POST {url}/studies`, `multipart/related; type="application/dicom"`. Per-instance failures in the answer (Failed SOP Sequence) are mapped: out of resources / processing failure → retry; SOP class not supported, cannot understand, data set mismatch → reject; already stored → done. **Test connection** runs a QIDO-RS `GET {url}/studies?limit=1`. |
| Plugin types | from the integration | Shown only while that integration is turned on (see [PLUGINS.md](PLUGINS.md)). |

Passwords, tokens and API keys are kept in the operating system's credential store.

## Data

`data/imaging/` in the LabSync data folder: `imaging.db` (queue), `images/` (received files, by day and study),
`state.json` (devices last sent down by integrations). Patient data is stored here until delivered; use BitLocker
(Windows) or FileVault (macOS) on the site computer.

## Testing

`pytest tests/test_imaging.py` runs real DICOM associations (pynetdicom as the modality) against a fake DICOMweb
server, a fake DICOM node and a fake Serenity gateway, and the dcmtk tools (`storescu`, `echoscu`) when installed.
