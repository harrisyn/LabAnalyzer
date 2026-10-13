"""Catalog of instrument profiles.

A profile is the starting point for a device connection: which protocol
engine to run, the usual physical link, and the instrument's quirks (where it
puts the sample ID, how it encodes test codes, how it names patients...).
Everything in a profile can be overridden per device in the configuration.

Maturity levels:
  stable        standard protocol, behaviour fully covered by tests
  beta          standard protocol with vendor-documented quirks; validate on site
  experimental  proprietary protocol implemented from vendor interface descriptions;
                validate layouts against a capture before going live
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DeviceProfile:
    id: str
    vendor: str
    model: str
    category: str
    protocol: str
    transport: str = "tcp_server"  # usual link: tcp_server | tcp_client | serial
    serial: dict[str, Any] = field(default_factory=lambda: {"baudrate": 9600, "bytesize": 8, "parity": "N", "stopbits": 1})
    options: dict[str, Any] = field(default_factory=dict)
    maturity: str = "beta"
    notes: str = ""

    @property
    def label(self) -> str:
        return f"{self.vendor} {self.model}"


SYSMEX_ASTM = {
    "astm": {
        "patient_id_fields": [5, 4, 3],
        "name_component_offset": 1,
        "instrument_specimen_component": 2,
        "test_code_component": 4,
        "query_specimen_component": 2,
    },
    "echo_query_specimen": True,
    "order_test_prefix": "^^^^",
}

ROCHE_ASTM = {
    "astm": {"strip_test_code_suffix": "/", "query_specimen_component": 2, "instrument_specimen_component": 0},
}

ABBOTT_ASTM = {"astm": {"strip_test_code_suffix": ""}}  # ^^^<assay no>^<name>^<dilution>^<status>

MINDRAY_HL7 = {"hl7": {"specimen_id_sources": ["OBR-3", "OBR-2", "SPM-2"]}, "query_style": "mindray"}


_P = DeviceProfile

PROFILES: list[DeviceProfile] = [
    # ---- generic -----------------------------------------------------------------
    _P("generic_astm", "Generic", "ASTM E1381/E1394 instrument", "Any", "astm", maturity="stable",
       notes="Standard LIS01-A2 / LIS2-A2. Works with most analyzers that offer an 'ASTM' host interface."),
    _P("generic_astm_unframed", "Generic", "ASTM records without low-level framing", "Any", "astm",
       options={"framing": "none"}, maturity="stable",
       notes="For TCP instruments that send plain H|...|L records with no ENQ/STX/checksums."),
    _P("generic_hl7", "Generic", "HL7 v2.x (MLLP)", "Any", "hl7", maturity="stable",
       notes="ORU^R01 / OUL^R22 results, original-mode ACK. Order queries via QRY^Q02 or QBP."),
    _P("generic_poct1a", "Generic", "POCT1-A2 point-of-care device", "Point of care", "poct1a", maturity="stable"),
    _P("generic_text", "Generic", "Text capture (unparsed / regex)", "Any", "text", maturity="stable",
       options={"framing": "stx_etx"},
       notes="Stores every transmission verbatim. Add result_regex/specimen_regex options to extract results."),

    # ---- Sysmex ----------------------------------------------------------------
    _P("sysmex_xn_l", "Sysmex", "XN-L (XN-330/350/450/550)", "Hematology", "astm", options=SYSMEX_ASTM,
       notes="ASTM over TCP (IPU) or RS-232. Patient name arrives as ^LAST^FIRST; sample number in O-4."),
    _P("sysmex_xn", "Sysmex", "XN series (XN-1000/2000/3000/9000)", "Hematology", "astm", options=SYSMEX_ASTM),
    _P("sysmex_xs_xt", "Sysmex", "XS / XT series (XS-1000i, XT-1800i, XT-4000i)", "Hematology", "astm",
       transport="serial", options=SYSMEX_ASTM),
    _P("sysmex_ca_cs", "Sysmex", "CA / CS coagulation (CA-600, CS-2500/5100)", "Coagulation", "astm",
       transport="serial", options=SYSMEX_ASTM),
    _P("sysmex_uf", "Sysmex", "UF-1000i / UF-5000 / UN series", "Urinalysis", "astm", options=SYSMEX_ASTM),

    # ---- Mindray ---------------------------------------------------------------
    _P("mindray_bc_hl7", "Mindray", "BC hematology (BC-20s/30s/5000/5380/5390/6000/6800)", "Hematology", "hl7",
       options=MINDRAY_HL7,
       notes="HL7 v2.3.1 over TCP. Histograms/scattergrams arrive as OBX ED images and are kept as attachments."),
    _P("mindray_bs_hl7", "Mindray", "BS chemistry (BS-200/230/240/380/430/480/800/2000)", "Chemistry", "hl7",
       options=MINDRAY_HL7, notes="HL7 v2.3.1. Host query (QRY^Q02) answered with QCK^Q02 / DSR^Q03."),
    _P("mindray_bs_astm", "Mindray", "BS chemistry (ASTM mode)", "Chemistry", "astm",
       notes="For BS models configured for ASTM instead of HL7."),
    _P("mindray_cl", "Mindray", "CL immunoassay (CL-900i/1000i/2000i/6000i)", "Immunoassay", "hl7", options=MINDRAY_HL7),

    # ---- Roche -----------------------------------------------------------------
    _P("roche_cobas_c111", "Roche", "cobas c 111", "Chemistry", "astm", transport="serial", options=ROCHE_ASTM),
    _P("roche_cobas_4000", "Roche", "cobas 4000 (c 311 / e 411)", "Chemistry / Immunoassay", "astm",
       options=ROCHE_ASTM, notes="Test codes arrive as ^^^<channel>/ and are normalised to the channel number."),
    _P("roche_cobas_6000_8000", "Roche", "cobas 6000 / 8000 (c 501/502, e 601/602, c 701/702, e 801)",
       "Chemistry / Immunoassay", "astm", options=ROCHE_ASTM),
    _P("roche_cobas_pro_pure", "Roche", "cobas pro / cobas pure", "Chemistry / Immunoassay", "astm",
       options=ROCHE_ASTM, notes="Also offers HL7; switch the protocol to hl7 if the host interface is set that way."),
    _P("roche_cobas_u411", "Roche", "cobas u 411", "Urinalysis", "astm", transport="serial", options=ROCHE_ASTM),
    _P("roche_cobas_b221", "Roche", "cobas b 221 / b 123", "Blood gas", "poct1a",
       notes="POCT1-A via cobas IT / direct. Set protocol to astm if the instrument is in ASTM mode."),
    _P("roche_accuchek_inform", "Roche", "Accu-Chek Inform II / cobas pulse", "Point of care", "poct1a"),

    # ---- Abbott ----------------------------------------------------------------
    _P("abbott_architect", "Abbott", "ARCHITECT c / i / ci series", "Chemistry / Immunoassay", "astm",
       transport="serial", options=ABBOTT_ASTM,
       notes="ASTM E1394 (Abbott Standard Interface). Not POCT1-A, despite what earlier versions claimed."),
    _P("abbott_alinity", "Abbott", "Alinity c / i / ci / h", "Chemistry / Immunoassay / Hematology", "astm",
       options=ABBOTT_ASTM),
    _P("abbott_celldyn", "Abbott", "CELL-DYN Ruby / Sapphire / Emerald", "Hematology", "astm", transport="serial"),
    _P("abbott_istat", "Abbott", "i-STAT Alinity / i-STAT 1 (via device manager)", "Point of care", "poct1a"),
    _P("abbott_afinion", "Abbott", "Afinion 2", "Point of care", "poct1a"),

    # ---- Siemens Healthineers ----------------------------------------------------
    _P("siemens_atellica", "Siemens", "Atellica Solution / CI Analyzer", "Chemistry / Immunoassay", "astm"),
    _P("siemens_advia_centaur", "Siemens", "ADVIA Centaur XP / XPT / CP", "Immunoassay", "astm", transport="serial"),
    _P("siemens_advia_chem", "Siemens", "ADVIA 1800 / 2400 / XPT", "Chemistry", "astm", transport="serial"),
    _P("siemens_dimension_vista", "Siemens", "Dimension Vista", "Chemistry / Immunoassay", "astm"),
    _P("siemens_dimension", "Siemens", "Dimension RxL / EXL / Xpand", "Chemistry", "dimension", transport="serial",
       maturity="experimental",
       notes="Proprietary Dimension host protocol (poll / no-request / result / acceptance). Confirm the "
             "result field layout (dimension_layout option) with a capture."),
    _P("siemens_rapidpoint", "Siemens", "RAPIDPoint 500e", "Blood gas", "poct1a"),

    # ---- Beckman Coulter ---------------------------------------------------------
    _P("beckman_au", "Beckman Coulter", "AU480 / AU680 / AU5800 / DxC 700 AU", "Chemistry", "beckman_au",
       transport="serial", options={"trailer_bytes": 0}, maturity="experimental",
       notes="AU online protocol with site-configurable fixed-width fields (au_header / au_test options)."),
    _P("beckman_dxh", "Beckman Coulter", "DxH 500 / 520 / 600 / 800 / 900", "Hematology", "astm"),
    _P("beckman_access", "Beckman Coulter", "Access 2 / DxI 600 / DxI 800 / DxI 9000", "Immunoassay", "astm",
       transport="serial"),

    # ---- Ortho / QuidelOrtho -----------------------------------------------------
    _P("ortho_vitros", "QuidelOrtho", "VITROS 350 / 4600 / 5600 / XT 7600 / ECiQ", "Chemistry / Immunoassay", "astm",
       transport="serial"),

    # ---- Others ------------------------------------------------------------------
    _P("horiba_pentra", "HORIBA", "ABX Pentra 60/80/XLR, Pentra DX Nexus", "Hematology", "astm", transport="serial"),
    _P("horiba_yumizen", "HORIBA", "Yumizen H500 / H550 / H1500", "Hematology", "astm"),
    _P("snibe_maglumi", "Snibe", "MAGLUMI 800 / 2000 / X3 / X6 / X8", "Immunoassay", "astm",
       options={"checksum": "lenient"}),
    _P("biorad_d10", "Bio-Rad", "D-10 / VARIANT II Turbo", "HbA1c", "astm", transport="serial"),
    _P("tosoh_aia", "Tosoh", "AIA-360 / AIA-900 / AIA-2000", "Immunoassay", "astm", transport="serial"),
    _P("stago_sta", "Stago", "STA Compact Max / STA R Max / STA Satellite", "Coagulation", "astm"),
    _P("werfen_acl_top", "Werfen", "ACL TOP family", "Coagulation", "astm"),
    _P("radiometer_abl", "Radiometer", "ABL80 / ABL90 FLEX / ABL800", "Blood gas", "astm",
       notes="Also offers POCT1-A and HL7; pick the protocol that matches the analyzer setting."),
    _P("nova_statstrip", "Nova Biomedical", "StatStrip / StatSensor", "Point of care", "poct1a"),
    _P("cepheid_genexpert", "Cepheid", "GeneXpert", "Molecular", "astm", notes="HL7 also available."),
    _P("human_humacount", "HUMAN", "HumaCount 5D / 5L / 30TS", "Hematology", "astm",
       options={"checksum": "lenient"}),
    _P("diasys_respons", "DiaSys", "respons 910 / 920", "Chemistry", "astm", transport="serial",
       options={"checksum": "lenient"}),
    _P("erba_xl", "Erba Mannheim", "XL-200 / XL-640 / XL-1000", "Chemistry", "astm", transport="serial"),
]

_BY_ID = {p.id: p for p in PROFILES}

# Names used by LabSync 1.x configuration files.
LEGACY_ANALYZER_NAMES = {
    "SYSMEX XN-L": "sysmex_xn_l",
    "Mindray BS-430": "mindray_bs_hl7",
    "HumaCount 5D": "human_humacount",
    "RESPONSE 920": "diasys_respons",
    "Roche Cobas": "roche_cobas_6000_8000",
    "Siemens Dimension": "siemens_dimension",
    "Abbott ARCHITECT": "abbott_architect",
    "VITROS": "ortho_vitros",
    "Beckman AU": "beckman_au",
}


def get_profile(profile_id: str) -> DeviceProfile:
    try:
        return _BY_ID[profile_id]
    except KeyError as exc:
        raise KeyError(f"unknown device profile {profile_id!r}") from exc


def find_profile(profile_id: str) -> DeviceProfile | None:
    return _BY_ID.get(profile_id)


def merged_options(profile: DeviceProfile, overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Deep-merge per-device overrides onto the profile options (one level of nesting)."""
    out: dict[str, Any] = {}
    for k, v in profile.options.items():
        out[k] = dict(v) if isinstance(v, dict) else v
    for k, v in (overrides or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def profiles_by_category() -> dict[str, list[DeviceProfile]]:
    groups: dict[str, list[DeviceProfile]] = {}
    for p in PROFILES:
        groups.setdefault(p.vendor, []).append(p)
    return groups
