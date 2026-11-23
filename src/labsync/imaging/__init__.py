"""Imaging module: a DICOM storage node on the local network that keeps every
image on disk until each destination (a PACS, another DICOM node, a DICOMweb
server, or a destination added by an integration plugin) has it.

It runs beside the analyzer engine in the same process, with its own threads,
queue database and folder, so a large study never delays a lab result and an
analyzer problem never stops imaging.
"""
