# Integrations (plugins)

LabSync talks to any system through its generic destinations: REST/JSON, FHIR R4, HL7 over MLLP and folders for
lab results; DICOM nodes and DICOMweb servers for images. An **integration** adds what one particular platform
needs on top of that, for example:

- pairing with a one-time code, and a key kept in the operating system's credential store,
- its own destination types for results and images (no address or key to type in),
- a status heartbeat, and imaging devices registered on the platform's side that may send through this computer.

Integrations are **off by default** and nothing they add is shown until one is turned on under
**Settings > Integrations**. Sites that don't use the platform never see it.

## Writing one

A plugin is a subclass of `labsync.plugins.Plugin`, published by any Python package through the
`labsync.plugins` entry point group:

```toml
[project.entry-points."labsync.plugins"]
myplatform = "myplatform_labsync:MyPlatformPlugin"
```

```python
from labsync.plugins import Link, Plugin
from labsync.outbound.senders import HttpSender


class MyPlatformPlugin(Plugin):
    id = "myplatform"
    name = "My Platform"
    summary = "Send results and images to My Platform."
    lab_destination_types = {"myplatform": "My Platform"}      # optional
    imaging_destination_types = {"myplatform": "My Platform"}  # optional
    secret_fields = ("api_key",)                                # kept in the credential store

    def defaults(self):
        return {"url": "", "api_key": ""}

    def configured(self, settings):
        return bool(settings["url"] and settings["api_key"])

    def validate(self, settings):
        return [] if settings["url"] else ["My Platform: enter its address"]

    def make_sender(self, dest, settings):                      # lab results
        return HttpSender({**dest, "url": settings["url"] + "/results",
                           "auth": {"method": "api_key", "header": "X-Api-Key", "api_key": settings["api_key"]}})

    def make_imaging_destination(self, spec, settings, imaging_config):
        ...  # an object with id, name, configured and send(rows) -> [Outcome]; see labsync.imaging.destinations

    def make_link(self, settings):                              # optional heartbeat
        return MyLink(settings)

    def settings_panel(self, parent, settings):                 # optional Tk panel with collect() -> settings
        ...


class MyLink(Link):
    interval_seconds = 60

    def check(self, report):          # blocking; return the platform's answer or None
        ...

    def remote_nodes(self, answer):   # optional: [{"name", "ae_title", "allowed_ips"}]
        ...
```

Settings are stored under `config["plugins"][<id>]` with `enabled` plus the plugin's defaults. A destination of a
plugin type whose plugin is turned off is reported by validation and not sent to; its queue is kept.

## Bundled: Serenity

`labsync.plugins.serenity` pairs LabSync with a Serenity organisation.

1. In Serenity open **Devices**, register this computer and copy its setup code (`SRN1.…`, shown once; it carries
   the API address and the device key).
2. In LabSync open **Settings > Integrations**, turn on **Serenity**, paste the setup code and save. A Serenity
   destination for images is added for you; the sidebar shows the connection status.
3. For analyzer results add a destination of type **Serenity** under **Delivery** (nothing to fill in).

Everything uses the header `X-Device-Key`:

| Call | Purpose |
|---|---|
| `POST {url}/device-gateway/heartbeat` | Every 60 s: status of instruments, the lab outbox and the imaging queue. The answer names the imaging devices allowed to send through this computer. |
| `POST {url}/device-gateway/dicom/instances` | Images, multipart/related, with an outcome per image (stored, hold until an order exists, retry, reject) |
| `POST {url}/device-gateway/lab-results` | Analyzer results in the LabSync 1.x JSON shape, with `Idempotency-Key` = the report id |

A refused key (401/403) never parks results or images: they stay queued and go once a new setup code is entered.
