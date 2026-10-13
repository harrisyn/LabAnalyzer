# Supported instruments

LabSync ships a profile for each instrument family below. A profile is a set of
defaults (protocol, link type, serial settings, field positions); everything can
be overridden per device under **Advanced** in the device dialog or with the
`options` object in `config.json`.

**Status** means:

- **stable**: protocol behaviour covered by the automated test suite against the published standard.
- **beta**: built from the vendor's published host-interface specification on a standard protocol. Expect to confirm field positions (specimen ID, test code component) during commissioning.
- **experimental**: proprietary vendor framing reconstructed from public documentation. Validate on site with a capture before going live.

Regenerate this table with `labsync-cli profiles --markdown`.

| Category | Vendor | Models | Protocol | Default link | Status | Profile id |
|---|---|---|---|---|---|---|
| Any | Generic | ASTM E1381/E1394 instrument | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | stable | `generic_astm` |
| Any | Generic | ASTM records without low-level framing | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | stable | `generic_astm_unframed` |
| Any | Generic | HL7 v2.x (MLLP) | HL7 v2.x over MLLP | TCP/IP | stable | `generic_hl7` |
| Point of care | Generic | POCT1-A2 point-of-care device | POCT1-A2 (XML) | TCP/IP | stable | `generic_poct1a` |
| Any | Generic | Text capture (unparsed / regex) | Generic text capture | TCP/IP | stable | `generic_text` |
| Hematology | Sysmex | XN-L (XN-330/350/450/550) | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `sysmex_xn_l` |
| Hematology | Sysmex | XN series (XN-1000/2000/3000/9000) | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `sysmex_xn` |
| Hematology | Sysmex | XS / XT series (XS-1000i, XT-1800i, XT-4000i) | ASTM E1381/E1394 (LIS01/LIS2-A2) | RS-232 | beta | `sysmex_xs_xt` |
| Coagulation | Sysmex | CA / CS coagulation (CA-600, CS-2500/5100) | ASTM E1381/E1394 (LIS01/LIS2-A2) | RS-232 | beta | `sysmex_ca_cs` |
| Urinalysis | Sysmex | UF-1000i / UF-5000 / UN series | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `sysmex_uf` |
| Hematology | Mindray | BC hematology (BC-20s/30s/5000/5380/5390/6000/6800) | HL7 v2.x over MLLP | TCP/IP | beta | `mindray_bc_hl7` |
| Chemistry | Mindray | BS chemistry (BS-200/230/240/380/430/480/800/2000) | HL7 v2.x over MLLP | TCP/IP | beta | `mindray_bs_hl7` |
| Chemistry | Mindray | BS chemistry (ASTM mode) | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `mindray_bs_astm` |
| Immunoassay | Mindray | CL immunoassay (CL-900i/1000i/2000i/6000i) | HL7 v2.x over MLLP | TCP/IP | beta | `mindray_cl` |
| Chemistry | Roche | cobas c 111 | ASTM E1381/E1394 (LIS01/LIS2-A2) | RS-232 | beta | `roche_cobas_c111` |
| Chemistry / Immunoassay | Roche | cobas 4000 (c 311 / e 411) | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `roche_cobas_4000` |
| Chemistry / Immunoassay | Roche | cobas 6000 / 8000 (c 501/502, e 601/602, c 701/702, e 801) | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `roche_cobas_6000_8000` |
| Chemistry / Immunoassay | Roche | cobas pro / cobas pure | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `roche_cobas_pro_pure` |
| Urinalysis | Roche | cobas u 411 | ASTM E1381/E1394 (LIS01/LIS2-A2) | RS-232 | beta | `roche_cobas_u411` |
| Blood gas | Roche | cobas b 221 / b 123 | POCT1-A2 (XML) | TCP/IP | beta | `roche_cobas_b221` |
| Point of care | Roche | Accu-Chek Inform II / cobas pulse | POCT1-A2 (XML) | TCP/IP | beta | `roche_accuchek_inform` |
| Chemistry / Immunoassay | Abbott | ARCHITECT c / i / ci series | ASTM E1381/E1394 (LIS01/LIS2-A2) | RS-232 | beta | `abbott_architect` |
| Chemistry / Immunoassay / Hematology | Abbott | Alinity c / i / ci / h | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `abbott_alinity` |
| Hematology | Abbott | CELL-DYN Ruby / Sapphire / Emerald | ASTM E1381/E1394 (LIS01/LIS2-A2) | RS-232 | beta | `abbott_celldyn` |
| Point of care | Abbott | i-STAT Alinity / i-STAT 1 (via device manager) | POCT1-A2 (XML) | TCP/IP | beta | `abbott_istat` |
| Point of care | Abbott | Afinion 2 | POCT1-A2 (XML) | TCP/IP | beta | `abbott_afinion` |
| Chemistry / Immunoassay | Siemens | Atellica Solution / CI Analyzer | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `siemens_atellica` |
| Immunoassay | Siemens | ADVIA Centaur XP / XPT / CP | ASTM E1381/E1394 (LIS01/LIS2-A2) | RS-232 | beta | `siemens_advia_centaur` |
| Chemistry | Siemens | ADVIA 1800 / 2400 / XPT | ASTM E1381/E1394 (LIS01/LIS2-A2) | RS-232 | beta | `siemens_advia_chem` |
| Chemistry / Immunoassay | Siemens | Dimension Vista | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `siemens_dimension_vista` |
| Chemistry | Siemens | Dimension RxL / EXL / Xpand | Siemens Dimension host interface | RS-232 | experimental | `siemens_dimension` |
| Blood gas | Siemens | RAPIDPoint 500e | POCT1-A2 (XML) | TCP/IP | beta | `siemens_rapidpoint` |
| Chemistry | Beckman Coulter | AU480 / AU680 / AU5800 / DxC 700 AU | Beckman Coulter AU online | RS-232 | experimental | `beckman_au` |
| Hematology | Beckman Coulter | DxH 500 / 520 / 600 / 800 / 900 | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `beckman_dxh` |
| Immunoassay | Beckman Coulter | Access 2 / DxI 600 / DxI 800 / DxI 9000 | ASTM E1381/E1394 (LIS01/LIS2-A2) | RS-232 | beta | `beckman_access` |
| Chemistry / Immunoassay | QuidelOrtho | VITROS 350 / 4600 / 5600 / XT 7600 / ECiQ | ASTM E1381/E1394 (LIS01/LIS2-A2) | RS-232 | beta | `ortho_vitros` |
| Hematology | HORIBA | ABX Pentra 60/80/XLR, Pentra DX Nexus | ASTM E1381/E1394 (LIS01/LIS2-A2) | RS-232 | beta | `horiba_pentra` |
| Hematology | HORIBA | Yumizen H500 / H550 / H1500 | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `horiba_yumizen` |
| Immunoassay | Snibe | MAGLUMI 800 / 2000 / X3 / X6 / X8 | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `snibe_maglumi` |
| HbA1c | Bio-Rad | D-10 / VARIANT II Turbo | ASTM E1381/E1394 (LIS01/LIS2-A2) | RS-232 | beta | `biorad_d10` |
| Immunoassay | Tosoh | AIA-360 / AIA-900 / AIA-2000 | ASTM E1381/E1394 (LIS01/LIS2-A2) | RS-232 | beta | `tosoh_aia` |
| Coagulation | Stago | STA Compact Max / STA R Max / STA Satellite | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `stago_sta` |
| Coagulation | Werfen | ACL TOP family | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `werfen_acl_top` |
| Blood gas | Radiometer | ABL80 / ABL90 FLEX / ABL800 | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `radiometer_abl` |
| Point of care | Nova Biomedical | StatStrip / StatSensor | POCT1-A2 (XML) | TCP/IP | beta | `nova_statstrip` |
| Molecular | Cepheid | GeneXpert | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `cepheid_genexpert` |
| Hematology | HUMAN | HumaCount 5D / 5L / 30TS | ASTM E1381/E1394 (LIS01/LIS2-A2) | TCP/IP | beta | `human_humacount` |
| Chemistry | DiaSys | respons 910 / 920 | ASTM E1381/E1394 (LIS01/LIS2-A2) | RS-232 | beta | `diasys_respons` |
| Chemistry | Erba Mannheim | XL-200 / XL-640 / XL-1000 | ASTM E1381/E1394 (LIS01/LIS2-A2) | RS-232 | beta | `erba_xl` |

## Commissioning a new instrument

1. Add the device with the closest profile, or the generic profile for its protocol.
2. Point the analyzer's host/LIS interface at the PC's IP and the port shown on the Instruments tab
   (or select the serial port and match baud/parity to the analyzer).
3. Run a sample. Open **Messages**, double-click the transmission, and check the parsed report.
4. If a field lands in the wrong place, adjust the device's Advanced options, for example:

| Option (ASTM) | Meaning | Default |
|---|---|---|
| `specimen_id_field` / `specimen_id_component` | Where the LIS specimen ID is in the O record (1-based field) | 3 / best non-empty |
| `instrument_specimen_field` | Instrument sample/rack ID field in the O record | 4 |
| `test_code_component` | Which `^` component of the Universal Test ID is the test code | last non-empty |
| `strip_test_code_suffix` | Strip a dilution/version suffix after this character (`ALB/2` -> `ALB`) | `/` |
| `patient_id_fields` | P-record fields to try in order for the patient ID | `[3, 4, 5]` |
| `framing` | `auto`, `e1381` (ENQ/STX/checksums) or `none` (plain records) | `auto` |
| `checksum` | `strict` (NAK bad frames), `lenient` (accept and warn) or `ignore` | `strict` |
| `answer_queries` | Reply to host queries with orders from the order source | `true` |

| Option (HL7) | Meaning | Default |
|---|---|---|
| `specimen_id_sources` | Fields tried in order for the specimen ID | `SPM-2, OBR-3, OBR-2, ORC-3, ORC-2` |
| `ack` | `always`, `never`, or honour `msh15` | `always` |
| `query_style` | `mindray` answers QRY^Q02 with QCK^Q02 + DSR^Q03 | unset |

5. Capture bytes with **Save capture** in the message viewer and replay them later with
   `labsync-sim replay capture.bin --port <port>`, or parse offline with
   `labsync-cli parse capture.bin --profile <id>`.
