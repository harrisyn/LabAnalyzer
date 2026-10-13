"""Payload formats for outbound destinations."""

from __future__ import annotations

import base64
import csv
import io
from datetime import UTC, datetime
from typing import Any

from .. import __version__
from ..models import Report

SCHEMA = "labsync.result.v1"


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v not in ("", None, [], {})}


def labsync_json(report: Report, ctx: dict[str, Any], include_attachments: bool = False) -> dict[str, Any]:
    p, s = report.patient, report.specimen
    out: dict[str, Any] = {
        "schema": SCHEMA,
        "id": report.id,
        "instance_id": ctx.get("instance_id", ""),
        "source": {"app": "LabSync", "version": __version__},
        "device": _clean({
            "id": ctx.get("device_id"), "name": ctx.get("device_name"), "profile": ctx.get("profile"),
            "vendor": ctx.get("vendor"), "model": ctx.get("model"), "protocol": ctx.get("protocol"),
        }),
        "received_at": ctx.get("received_at"),
        "is_qc": report.is_qc,
        "patient": _clean({
            "id": p.id, "alternate_ids": p.alternate_ids,
            "name": _clean({"family": p.name.family, "given": p.name.given, "middle": p.name.middle}),
            "full_name": p.name.full, "birth_date": p.birth_date, "sex": p.sex, "physician": p.physician,
            "location": p.location,
        }) or None,
        "specimen": _clean({
            "id": s.id, "instrument_specimen_id": s.instrument_specimen_id, "type": s.type,
            "collected_at": s.collected_at, "priority": s.priority, "rack": s.rack, "position": s.position,
            "requested_tests": s.requested_tests,
        }),
        "results": [
            _clean({
                "sequence": o.sequence, "code": o.code, "name": o.name, "value": o.value,
                "numeric_value": o.numeric_value, "units": o.units, "reference_range": o.reference_range,
                "flags": o.flags, "abnormal": o.abnormal, "status": o.status, "observed_at": o.observed_at,
                "instrument": o.instrument, "comments": o.comments,
            })
            for o in report.observations
        ],
        "comments": report.comments,
    }
    if report.is_qc and report.qc_info:
        out["qc"] = report.qc_info
    if include_attachments and report.attachments:
        out["attachments"] = [
            {"name": a.name, "mime": a.mime, "data_base64": base64.b64encode(a.data).decode()} for a in report.attachments
        ]
    return out


def legacy_json(report: Report, ctx: dict[str, Any]) -> dict[str, Any]:
    """The exact payload shape LabSync 1.x posted, for servers already integrated with it."""
    p, s = report.patient, report.specimen
    results = []
    for o in report.observations:
        num = o.numeric_value
        results.append({
            "id": o.sequence,
            "test_code": o.code,
            "value": num if num is not None and not o.value.strip().startswith(("<", ">")) else o.value,
            "unit": o.units,
            "flags": ",".join(o.flags),
            "timestamp": o.observed_at or ctx.get("received_at"),
            "sequence": str(o.sequence),
        })
    return {
        "instance_id": ctx.get("instance_id", ""),
        "analyzer_type": ctx.get("legacy_analyzer_type") or ctx.get("model") or ctx.get("device_name", ""),
        "timestamp": datetime.now(UTC).isoformat(),
        "patient": {
            "db_id": ctx.get("report_db_id"),
            "patient_id": p.id or s.id,
            "sample_id": s.id,
            "name": p.name.full,
            "dob": p.birth_date,
            "sex": p.sex,
            "physician": p.physician,
        },
        "results": results,
    }


def fhir_bundle(report: Report, ctx: dict[str, Any]) -> dict[str, Any]:
    """FHIR R4 transaction: Patient (conditional), Specimen, Observations and a DiagnosticReport."""
    p, s = report.patient, report.specimen
    system = ctx.get("identifier_system") or "urn:labsync:mrn"
    specimen_system = ctx.get("specimen_system") or "urn:labsync:specimen"
    code_system = ctx.get("code_system") or f"urn:labsync:device:{ctx.get('profile') or 'generic'}"
    entries: list[dict[str, Any]] = []
    patient_ref = None
    if p.id:
        patient_ref = f"urn:uuid:{report.id[:8]}-0000-4000-8000-{report.id[-12:]}"
        res: dict[str, Any] = {"resourceType": "Patient", "identifier": [{"system": system, "value": p.id}]}
        if p.name:
            res["name"] = [_clean({"family": p.name.family, "given": [g for g in (p.name.given, p.name.middle) if g]})]
        if p.sex:
            res["gender"] = {"M": "male", "F": "female", "O": "other"}.get(p.sex, "unknown")
        if len(p.birth_date) == 10:
            res["birthDate"] = p.birth_date
        entries.append({"fullUrl": patient_ref, "resource": res,
                        "request": {"method": "POST", "url": "Patient", "ifNoneExist": f"identifier={system}|{p.id}"}})
    specimen_ref = f"urn:uuid:{report.id[:8]}-0000-4000-9000-{report.id[-12:]}"
    spec: dict[str, Any] = {"resourceType": "Specimen", "identifier": [{"system": specimen_system, "value": s.id}]}
    if patient_ref:
        spec["subject"] = {"reference": patient_ref}
    if s.type:
        spec["type"] = {"text": s.type}
    if s.collected_at:
        spec["collection"] = {"collectedDateTime": s.collected_at}
    if s.id:
        entries.append({"fullUrl": specimen_ref, "resource": spec,
                        "request": {"method": "POST", "url": "Specimen",
                                    "ifNoneExist": f"identifier={specimen_system}|{s.id}"}})
    obs_refs = []
    for i, o in enumerate(report.observations):
        ref = f"urn:uuid:{report.id[:8]}-{i:04x}-4000-a000-{report.id[-12:]}"
        obs_refs.append({"reference": ref})
        res = {
            "resourceType": "Observation",
            "status": {"P": "preliminary", "C": "corrected", "X": "cancelled"}.get(o.status, "final"),
            "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category",
                                      "code": "laboratory"}]}],
            "code": {"coding": [_clean({"system": code_system, "code": o.code, "display": o.name})], "text": o.name or o.code},
            "device": {"display": ctx.get("device_name", "")},
        }
        if patient_ref:
            res["subject"] = {"reference": patient_ref}
        if s.id:
            res["specimen"] = {"reference": specimen_ref}
        if o.observed_at:
            res["effectiveDateTime"] = o.observed_at
        num = o.numeric_value
        if num is not None and not o.value.strip().startswith(("<", ">")):
            res["valueQuantity"] = _clean({"value": num, "unit": o.units})
        else:
            res["valueString"] = o.value
        if o.reference_range:
            res["referenceRange"] = [{"text": o.reference_range}]
        if o.flags:
            res["interpretation"] = [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                                                  "code": f}]} for f in o.flags if f]
        if o.comments:
            res["note"] = [{"text": c} for c in o.comments]
        entries.append({"fullUrl": ref, "resource": res, "request": {"method": "POST", "url": "Observation"}})
    dr: dict[str, Any] = {
        "resourceType": "DiagnosticReport",
        "status": "final",
        "identifier": [{"system": "urn:labsync:report", "value": report.id}],
        "code": {"text": ", ".join(s.requested_tests) or ctx.get("device_name") or "Laboratory results"},
        "issued": ctx.get("received_at"),
        "result": obs_refs,
    }
    if patient_ref:
        dr["subject"] = {"reference": patient_ref}
    if s.id:
        dr["specimen"] = [{"reference": specimen_ref}]
    entries.append({"resource": dr, "request": {"method": "POST", "url": "DiagnosticReport",
                                                 "ifNoneExist": f"identifier=urn:labsync:report|{report.id}"}})
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


def csv_rows(report: Report, ctx: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["received_at", "device", "specimen_id", "patient_id", "patient_name", "code", "name", "value",
                "units", "reference_range", "flags", "status", "observed_at"])
    for o in report.observations:
        w.writerow([ctx.get("received_at"), ctx.get("device_name"), report.specimen.id, report.patient.id,
                    report.patient.name.full, o.code, o.name, o.value, o.units, o.reference_range, " ".join(o.flags),
                    o.status, o.observed_at])
    return buf.getvalue()
