"""IPC-2581 (rev B/C) - the neutral export of Allegro, Altium, Xpedition and others.

Read with ``defusedxml``: DTDs and entity declarations are refused outright (XXE,
entity expansion), the document is size-limited by ``FileRef``. Element names are
matched without namespaces (revisions use different namespace URIs).

Sources, in order of trust:

* ``Bom/BomItem`` - designators (``RefDes``), package, populate flag, value
  (``Characteristics/Textual`` named "Value"), description;
* ``Avl/AvlItem`` - MPN and manufacturer per BOM item (``OEMDesignNumber``), the chosen
  or best-ranked vendor part, manufacturer names from ``LogisticHeader/Enterprise``;
* ``Ecad/.../Component`` - placements: package for designators the BOM leaves without
  one, and the only source when the file has no BOM section (lower confidence).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from xml.etree.ElementTree import Element
from xml.etree.ElementTree import ParseError as XmlParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

from bomagent_bom.model import Component, ParsedDesign
from bomagent_cad.base import FileRef, ParseError

MAX_COMPONENTS = 100_000
SUFFIXES = {".xml", ".cvg", ".ipc2581"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _iter(root: Element, name: str) -> Iterator[Element]:
    for el in root.iter():
        if isinstance(el.tag, str) and _local(el.tag) == name:
            yield el


def _children(el: Element, name: str) -> Iterator[Element]:
    for child in el:
        if isinstance(child.tag, str) and _local(child.tag) == name:
            yield child


def load_xml(file: FileRef) -> Element:
    """Parse untrusted XML: no DTD, no entities, no network."""
    try:
        root: Element = fromstring(file.data, forbid_dtd=True)
    except DefusedXmlException as exc:
        raise ParseError(
            f"{file.name}: DTDs and entity declarations are not accepted", code="xml.forbidden"
        ) from exc
    except XmlParseError as exc:
        raise ParseError(f"{file.name}: not well-formed XML ({exc})", code="xml.malformed") from exc
    return root


class Ipc2581Parser:
    format_id = "ipc2581"
    version = "1.0.0"

    def sniff(self, file: FileRef) -> float:
        if file.suffix not in SUFFIXES:
            return 0.0
        return 0.95 if b"<IPC-2581" in file.data[:4096] else 0.0

    def parse(self, files: list[FileRef]) -> ParsedDesign:
        candidates = [f for f in files if self.sniff(f) > 0.5]
        if len(candidates) != 1:
            raise ParseError("expected exactly one IPC-2581 file", code="ipc2581.count")
        file = candidates[0]
        root = load_xml(file)
        if _local(str(root.tag)) != "IPC-2581":
            raise ParseError(f"{file.name}: root element is not IPC-2581", code="ipc2581.root")

        vendors = {
            e.get("id", ""): e.get("name", "") for e in _iter(root, "Enterprise") if e.get("id")
        }
        avl = self._avl(root, vendors)
        placements = {c.get("refDes", ""): c for c in _iter(root, "Component") if c.get("refDes")}
        limitations: list[str] = []
        boms = list(_iter(root, "Bom"))
        if boms:
            components = self._from_bom(boms[0], avl, placements, limitations)
            confidence = 1.0
        else:
            components = [
                Component(
                    refdes=ref,
                    value=el.get("part", ""),
                    footprint=el.get("packageRef", ""),
                )
                for ref, el in sorted(placements.items())
            ]
            limitations.append(
                "no BOM section: parts come from placements only (no values, MPNs or"
                " populate flags) - export IPC-2581 with the BOM function enabled"
            )
            confidence = 0.6
        if not components:
            raise ParseError(f"{file.name}: no components found", code="ipc2581.no_components")
        if len(components) > MAX_COMPONENTS:
            raise ParseError(f"{file.name}: too many components", code="file.too_large")
        if limitations and boms:
            confidence = max(0.7, 1.0 - 0.02 * len(limitations))
        return ParsedDesign(
            design_name=self._name(root, file),
            source_format=self.format_id,
            components=components,
            confidence=confidence,
            limitations=limitations,
            files=[f.source() for f in files],
            parser_version=self.version,
        )

    @staticmethod
    def _name(root: Element, file: FileRef) -> str:
        for tag, attr in (("StepRef", "name"), ("BomHeader", "assembly"), ("Step", "name")):
            for el in _iter(root, tag):
                if el.get(attr):
                    return str(el.get(attr))
        return Path(file.name).stem

    @staticmethod
    def _avl(root: Element, vendors: dict[str, str]) -> dict[str, tuple[str, str]]:
        """OEM design number -> (MPN, manufacturer) of the chosen / best-ranked part."""
        out: dict[str, tuple[str, str]] = {}
        for item in _iter(root, "AvlItem"):
            number = item.get("OEMDesignNumber", "")
            options = []
            for vmpn in _children(item, "AvlVmpn"):
                mpn = next(_children(vmpn, "AvlMpn"), None)
                vendor = next(_children(vmpn, "AvlVendor"), None)
                if mpn is None or not mpn.get("name"):
                    continue
                chosen = vmpn.get("chosen", "").lower() == "true"
                try:
                    rank = int(mpn.get("rank", "99"))
                except ValueError:
                    rank = 99
                manufacturer = (
                    vendors.get(vendor.get("enterpriseRef", ""), "") if vendor is not None else ""
                )
                options.append((not chosen, rank, mpn.get("name", ""), manufacturer))
            if number and options:
                _, _, mpn_name, manufacturer = min(options)
                out[number] = (mpn_name, manufacturer)
        return out

    @staticmethod
    def _from_bom(
        bom: Element,
        avl: dict[str, tuple[str, str]],
        placements: dict[str, Element],
        limitations: list[str],
    ) -> list[Component]:
        components: list[Component] = []
        seen: set[str] = set()
        for item in _children(bom, "BomItem"):
            number = item.get("OEMDesignNumberRef", "")
            value = ""
            for textual in _iter(item, "Textual"):
                if textual.get("textualCharacteristicName", "").casefold() == "value":
                    value = textual.get("textualCharacteristicValue", "")
                    break
            mpn, manufacturer = avl.get(number, ("", ""))
            fields = {
                k: v
                for k, v in (
                    ("MPN", mpn),
                    ("Manufacturer", manufacturer),
                    ("Description", item.get("description", "")),
                )
                if v
            }
            refs = list(_children(item, "RefDes"))
            if not refs:
                limitations.append(f"BOM item {number or '?'} lists no designators")
            for ref in refs:
                name = ref.get("name", "").strip()
                if not name:
                    continue
                if name in seen:
                    limitations.append(f"{name} appears in more than one BOM item")
                    continue
                seen.add(name)
                placement = placements.get(name)
                package = ref.get("packageRef", "") or (
                    placement.get("packageRef", "") if placement is not None else ""
                )
                components.append(
                    Component(
                        refdes=name,
                        value=value,
                        footprint=package,
                        fields=dict(fields),
                        dnp=ref.get("populate", "true").lower() == "false",
                    )
                )
        return components
