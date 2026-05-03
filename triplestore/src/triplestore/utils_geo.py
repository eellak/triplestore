from __future__ import annotations

# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0
import json
import xml.etree.ElementTree as ET
import zipfile
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from shapely import wkt
from shapely.geometry import mapping


def _looks_like_geojson(value: Any) -> bool:
    """
    Check whether a value appears to be a valid GeoJSON object.

    Parameters
    ----------
    value : Any
        The value to inspect.

    Returns
    -------
    bool
        True if the value resembles a GeoJSON geometry or feature object,
        False otherwise.
    """
    if not isinstance(value, dict):
        return False

    geojson_type = value.get("type")
    if not isinstance(geojson_type, str):
        return False

    valid_types = {"Point", "MultiPoint", "LineString", "MultiLineString",
                   "Polygon", "MultiPolygon", "GeometryCollection", "Feature", "FeatureCollection"}
    return geojson_type in valid_types


def _parse_geojson_value(value: str, *, backend_name: str) -> dict[str, Any]:
    """
    Parse a string value as GeoJSON and return the decoded object.

    Parameters
    ----------
    value : str
        The string value to parse as GeoJSON.
    backend_name : str
        Backend name used in error messages.

    Returns
    -------
    dict[str, Any]
        The parsed GeoJSON object.

    Raises
    ------
    ValueError
        If the value is not valid JSON or does not represent a supported GeoJSON object.
    """
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        msg = (
            f"[{backend_name}] Cannot export result to GeoJSON because a result value "
            "is not valid JSON. Expected a GeoJSON geometry, Feature, or "
            "FeatureCollection encoded as a JSON string."
        )
        raise ValueError(msg) from exc

    if not _looks_like_geojson(parsed):
        msg = (
            f"[{backend_name}] Cannot export result to GeoJSON because a result value "
            "is valid JSON but not a supported GeoJSON object. Expected a GeoJSON "
            "geometry, Feature, or FeatureCollection with a valid 'type' field."
        )
        raise ValueError(msg)

    return parsed


def _strip_typed_literal(value: str) -> str:
    """
    Normalize an RDF literal by removing quotes and datatype suffix.
    It is primarily used to prepare WKT literals for geometry parsing.

    Parameters
    ----------
    value : str
        The literal value to normalize.

    Returns
    -------
    str
        The extracted literal value without surrounding quotes or datatype suffix.
    """
    text = value.strip()

    if text.startswith('"') and '"^^' in text:
        return text[1:text.index('"^^')]

    if text.startswith('"') and text.endswith('"'):
        return text[1:-1]

    return text


def _parse_wkt_value(value: str, *, backend_name: str) -> dict[str, Any]:
    """
    Parse a WKT literal and convert it to a GeoJSON geometry object.

    Parameters
    ----------
    value : str
        The WKT literal value to parse.
    backend_name : str
        Backend name used in error messages.

    Returns
    -------
    dict[str, Any]
        The parsed geometry as a GeoJSON-style dictionary.

    Raises
    ------
    ValueError
        If the input value cannot be parsed as WKT or cannot be converted to a GeoJSON geometry object.
    """
    text = _strip_typed_literal(value)

    try:
        geometry = wkt.loads(text)
    except Exception as exc:
        msg = (
            f"[{backend_name}] Cannot export result to GeoJSON because result value "
            "could not be parsed as WKT geometry. Expected a valid WKT value such as "
            "'POINT(x y)', 'LINESTRING(...)', or 'POLYGON(...)'."
        )
        raise ValueError(msg) from exc

    try:
        return dict(mapping(geometry))
    except Exception as exc:
        msg = (
            f"[{backend_name}] Cannot export result to GeoJSON because the parsed WKT "
            "geometry could not be converted to a GeoJSON geometry object."
        )
        raise ValueError(msg) from exc


def _build_feature_rows(results: list[dict[str, str]], *, backend_name: str) -> list[dict[str, Any]]:
    """
    Convert SELECT result rows to normalized GeoJSON-like Feature objects.

    Parameters
    ----------
    results : list[dict[str, str]]
        The SELECT query result bindings, where each dictionary represents a result row mapping variable names to string values.
    backend_name : str
        Backend name used in error messages.

    Returns
    -------
    list[dict[str, Any]]
        A list of normalized GeoJSON-like Feature objects, one for each input row.

    Raises
    ------
    ValueError
        If a row does not contain a supported geometry value, contains more than
        one geometry column, or contains a FeatureCollection value instead of a
        single geometry or Feature.
    """
    features: list[dict[str, Any]] = []

    for row in results:
        geometry_column = None
        geometry_value = None

        for key, value in row.items():
            try:
                parsed = _parse_geojson_value(value, backend_name=backend_name)
            except ValueError:
                continue

            if geometry_column is not None:
                msg = (
                    f"[{backend_name}] Cannot export SELECT results as geospatial data because "
                    "a result row contains more than one geometry column. Each row must contain "
                    "exactly one GeoJSON or WKT geometry value."
                )
                raise ValueError(msg)

            geometry_column = key
            geometry_value = parsed

        if geometry_column is None:
            for key, value in row.items():
                try:
                    parsed = _parse_wkt_value(value, backend_name=backend_name)
                except ValueError:
                    continue

                if geometry_column is not None:
                    msg = (
                        f"[{backend_name}] Cannot export SELECT results as geospatial data because "
                        "a result row contains more than one geometry column. Each row must contain "
                        "exactly one GeoJSON or WKT geometry value."
                    )
                    raise ValueError(msg)

                geometry_column = key
                geometry_value = parsed

        if geometry_column is None or geometry_value is None:
            msg = (
                f"[{backend_name}] Cannot export SELECT results as geospatial data because "
                "a result row does not contain any supported geometry value. Expected "
                "exactly one GeoJSON geometry, GeoJSON Feature, or WKT literal per row."
            )
            raise ValueError(msg)

        if geometry_value["type"] == "Feature":
            feature = geometry_value.copy()
            existing_properties = feature.get("properties", {})
            extra_properties = {k: v for k, v in row.items() if k != geometry_column}
            feature["properties"] = {**existing_properties, **extra_properties}
            features.append(feature)
            continue

        if geometry_value["type"] == "FeatureCollection":
            msg = (
                f"[{backend_name}] Cannot export SELECT results as geospatial data because "
                "a single result row contains a GeoJSON FeatureCollection. Each row must "
                "represent exactly one geometry or one GeoJSON Feature."
            )
            raise ValueError(msg)

        properties = {k: v for k, v in row.items() if k != geometry_column}
        features.append({
            "type": "Feature",
            "geometry": geometry_value,
            "properties": properties,
        })

    return features


def _build_geojson_feature_collection(results: list[dict[str, str]], *, backend_name: str) -> dict[str, Any]:
    """
    Build a GeoJSON FeatureCollection from SELECT result rows.

    Parameters
    ----------
    results : list[dict[str, str]]
        The SELECT query result bindings, where each dictionary represents a result row mapping variable names to string values.
    backend_name : str
        Backend name used in error messages.

    Returns
    -------
    dict[str, Any]
        A GeoJSON FeatureCollection containing one Feature for each input row.
    """
    return {
        "type": "FeatureCollection",
        "features": _build_feature_rows(results, backend_name=backend_name),
    }


def _format_coords(coord: list[float], *, separator: str, require_2d_or_3d: bool = False) -> str:
    """
    Format a coordinate list into a string using the given separator.

    Parameters
    ----------
    coord : list[float]
        The coordinate to format.
    separator : str
        The separator to use between coordinate values.
    require_2d_or_3d : bool, default=False
        If True, validate that the coordinate contains exactly 2 or 3 values.

    Returns
    -------
    str
        The formatted coordinate string.

    Raises
    ------
    ValueError
        If validation is enabled and the coordinate does not contain 2 or 3 values.
    """
    if require_2d_or_3d and len(coord) not in {2, 3}:
        msg = (
            "Invalid coordinate for export. Expected either 2 values (x, y) or "
            f"3 values (x, y, z), but got {len(coord)} values: {coord!r}."
        )
        raise ValueError(msg)

    return separator.join(str(x) for x in coord)


def _coords_to_kml(coord: list[float]) -> str:
    """
    Convert a coordinate list to KML coordinate text.

    Parameters
    ----------
    coord : list[float]
        The coordinate to format.

    Returns
    -------
    str
        The coordinate formatted as comma-separated KML coordinate text.
    """
    return _format_coords(coord, separator=",", require_2d_or_3d=True)


def _geometry_to_kml_element(geometry: dict[str, Any]) -> ET.Element:
    """
    Convert a GeoJSON-like geometry object to a KML XML element.

    Parameters
    ----------
    geometry : dict[str, Any]
        The GeoJSON-like geometry object to convert. The input is expected to
        contain at least a geometry "type" and its corresponding "coordinates".

    Returns
    -------
    xml.etree.ElementTree.Element
        The generated KML XML element representing the input geometry.

    Raises
    ------
    ValueError
        If the geometry type is not supported for KML export.
    """
    geom_type = geometry["type"]
    coords = geometry["coordinates"]

    if geom_type == "Point":
        point_el = ET.Element("Point")
        ET.SubElement(point_el, "coordinates").text = _coords_to_kml(coords)
        return point_el

    if geom_type == "LineString":
        line_el = ET.Element("LineString")
        ET.SubElement(line_el, "coordinates").text = " ".join(_coords_to_kml(c) for c in coords)
        return line_el

    if geom_type == "Polygon":
        poly_el = ET.Element("Polygon")

        outer = ET.SubElement(poly_el, "outerBoundaryIs")
        outer_ring = ET.SubElement(outer, "LinearRing")
        ET.SubElement(outer_ring, "coordinates").text = " ".join(_coords_to_kml(c) for c in coords[0])

        for ring in coords[1:]:
            inner = ET.SubElement(poly_el, "innerBoundaryIs")
            inner_ring = ET.SubElement(inner, "LinearRing")
            ET.SubElement(inner_ring, "coordinates").text = " ".join(_coords_to_kml(c) for c in ring)

        return poly_el

    if geom_type == "MultiPoint":
        multi = ET.Element("MultiGeometry")
        for point in coords:
            multi.append(_geometry_to_kml_element({"type": "Point", "coordinates": point}))
        return multi

    if geom_type == "MultiLineString":
        multi = ET.Element("MultiGeometry")
        for line in coords:
            multi.append(_geometry_to_kml_element({"type": "LineString", "coordinates": line}))
        return multi

    if geom_type == "MultiPolygon":
        multi = ET.Element("MultiGeometry")
        for poly in coords:
            multi.append(_geometry_to_kml_element({"type": "Polygon", "coordinates": poly}))
        return multi

    msg = (
        "Cannot export geometry to KML because the geometry type is not supported. "
        f"Got {geom_type!r}. Supported types are: 'Point', 'LineString', 'Polygon', "
        "'MultiPoint', 'MultiLineString', and 'MultiPolygon'."
    )
    raise ValueError(msg)


def _build_kml_document(results: list[dict[str, str]], *, backend_name: str) -> str:
    """
    Build a KML document from SELECT result rows.

    Parameters
    ----------
    results : list[dict[str, str]]
        The SELECT query result bindings, where each dictionary represents a result row mapping variable names to string values.
    backend_name : str
        Backend name used in error messages.

    Returns
    -------
    str
        The generated KML document as a formatted XML string.

    Raises
    ------
    ValueError
        If the result rows cannot be converted to valid feature objects or if any geometry cannot be represented in KML.
    """
    try:
        features = _build_feature_rows(results, backend_name=backend_name)
    except ValueError as exc:
        msg = (
            f"[{backend_name}] Cannot export SELECT results to KML because one or more "
            "result rows could not be converted to valid geospatial features."
        )
        raise ValueError(msg) from exc

    kml = ET.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    document = ET.SubElement(kml, "Document")

    for idx, feature in enumerate(features, start=1):
        placemark = ET.SubElement(document, "Placemark")

        props = feature.get("properties", {})
        name_value = props.get("name") or props.get("feature") or f"feature-{idx}"
        ET.SubElement(placemark, "name").text = str(name_value)

        if props:
            extended = ET.SubElement(placemark, "ExtendedData")
            for key, value in props.items():
                data_el = ET.SubElement(extended, "Data", name=str(key))
                ET.SubElement(data_el, "value").text = str(value)

        try:
            placemark.append(_geometry_to_kml_element(feature["geometry"]))
        except ValueError as exc:
            msg = (
                f"[{backend_name}] Cannot export SELECT results to KML because one or more "
                "feature geometries use a format that is not supported in KML export."
            )
            raise ValueError(msg) from exc

    try:
        ET.indent(kml, space="  ")
        return ET.tostring(kml, encoding="unicode")
    except Exception as exc:
        msg = (
            f"[{backend_name}] Failed to generate the final KML document due to an XML "
            "serialization error."
        )
        raise ValueError(msg) from exc


def _coords_to_gml_pos(coord: list[float]) -> str:
    """
    Convert a coordinate list to GML position text.

    Parameters
    ----------
    coord : list[float]
        The coordinate to format.

    Returns
    -------
    str
        The coordinate formatted as whitespace-separated GML position text.
    """
    return _format_coords(coord, separator=" ")


def _geometry_to_gml_element(geometry: dict[str, Any]) -> ET.Element:
    """
    Convert a GeoJSON-like geometry object to a GML XML element.

    Parameters
    ----------
    geometry : dict[str, Any]
        The GeoJSON-like geometry object to convert. The input is expected to
        contain at least a geometry ``type`` and its corresponding ``coordinates``.

    Returns
    -------
    xml.etree.ElementTree.Element
        The generated GML XML element representing the input geometry.

    Raises
    ------
    ValueError
        If the geometry type is not supported for GML export.
    """
    geom_type = geometry["type"]
    coords = geometry["coordinates"]

    ns = "http://www.opengis.net/gml"

    if geom_type == "Point":
        point_el = ET.Element(f"{{{ns}}}Point")
        ET.SubElement(point_el, f"{{{ns}}}pos").text = _coords_to_gml_pos(coords)
        return point_el

    if geom_type == "LineString":
        line_el = ET.Element(f"{{{ns}}}LineString")
        ET.SubElement(line_el, f"{{{ns}}}posList").text = " ".join(_coords_to_gml_pos(c) for c in coords)
        return line_el

    if geom_type == "Polygon":
        poly_el = ET.Element(f"{{{ns}}}Polygon")

        exterior = ET.SubElement(poly_el, f"{{{ns}}}exterior")
        outer_ring = ET.SubElement(exterior, f"{{{ns}}}LinearRing")
        ET.SubElement(outer_ring, f"{{{ns}}}posList").text = " ".join(_coords_to_gml_pos(c) for c in coords[0])

        for ring in coords[1:]:
            interior = ET.SubElement(poly_el, f"{{{ns}}}interior")
            inner_ring = ET.SubElement(interior, f"{{{ns}}}LinearRing")
            ET.SubElement(inner_ring, f"{{{ns}}}posList").text = " ".join(_coords_to_gml_pos(c) for c in ring)

        return poly_el

    if geom_type == "MultiPoint":
        multi = ET.Element(f"{{{ns}}}MultiPoint")
        for point in coords:
            member = ET.SubElement(multi, f"{{{ns}}}pointMember")
            member.append(_geometry_to_gml_element({"type": "Point", "coordinates": point}))
        return multi

    if geom_type == "MultiLineString":
        multi = ET.Element(f"{{{ns}}}MultiLineString")
        for line in coords:
            member = ET.SubElement(multi, f"{{{ns}}}lineStringMember")
            member.append(_geometry_to_gml_element({"type": "LineString", "coordinates": line}))
        return multi

    if geom_type == "MultiPolygon":
        multi = ET.Element(f"{{{ns}}}MultiPolygon")
        for poly in coords:
            member = ET.SubElement(multi, f"{{{ns}}}polygonMember")
            member.append(_geometry_to_gml_element({"type": "Polygon", "coordinates": poly}))
        return multi

    msg = (
        "Cannot export geometry to GML because the geometry type is not supported. "
        f"Got {geom_type!r}. Supported types are: 'Point', 'LineString', 'Polygon', "
        "'MultiPoint', 'MultiLineString', and 'MultiPolygon'."
    )
    raise ValueError(msg)


def _build_gml_document(results: list[dict[str, str]], *, backend_name: str) -> str:
    """
    Build a GML document from SELECT result rows.
    The resulting XML document is returned as a formatted string.

    Parameters
    ----------
    results : list[dict[str, str]]
        The SELECT query result bindings, where each dictionary represents a result row mapping variable names to string values.
    backend_name : str
        Backend name used in error messages.

    Returns
    -------
    str
        The generated GML document as a formatted XML string.

    Raises
    ------
    ValueError
        If the result rows cannot be converted to valid feature objects or if
        any geometry cannot be represented in GML.
    """
    try:
        features = _build_feature_rows(results, backend_name=backend_name)
    except ValueError as exc:
        msg = (
            f"[{backend_name}] Cannot export SELECT results to GML because one or more "
            "result rows could not be converted to valid geospatial features."
        )
        raise ValueError(msg) from exc

    ns_gml = "http://www.opengis.net/gml"
    ns_ex = "http://example.org/gml-export"

    ET.register_namespace("gml", ns_gml)
    ET.register_namespace("ts", ns_ex)

    root = ET.Element(f"{{{ns_ex}}}FeatureCollection")

    for idx, feature in enumerate(features, start=1):
        member = ET.SubElement(root, f"{{{ns_gml}}}featureMember")
        feat_el = ET.SubElement(member, f"{{{ns_ex}}}Feature", attrib={"fid": f"f{idx}"})

        props = feature.get("properties", {})
        for key, value in props.items():
            ET.SubElement(feat_el, f"{{{ns_ex}}}{key}").text = str(value)

        geom_prop = ET.SubElement(feat_el, f"{{{ns_ex}}}geometry")
        try:
            geom_prop.append(_geometry_to_gml_element(feature["geometry"]))
        except ValueError as exc:
            msg = (
                f"[{backend_name}] Cannot export SELECT results to GML because one or more "
                "feature geometries use a format that is not supported in GML export."
            )
            raise ValueError(msg) from exc

    try:
        ET.indent(root, space="  ")
        return ET.tostring(root, encoding="unicode")
    except Exception as exc:
        msg = (
            f"[{backend_name}] Failed to generate the final GML document due to an XML "
            "serialization error."
        )
        raise ValueError(msg) from exc


def _write_kmz_archive(kml_text: str, output_path: Path) -> Path:
    """
    Write a KMZ archive containing a KML document.

    Parameters
    ----------
    kml_text : str
        The KML document content to include in the archive.
    output_path : Path
        The output path for the generated ``.kmz`` file.

    Returns
    -------
    Path
        The path to the generated KMZ archive.
    """
    with zipfile.ZipFile(output_path, mode="w", compression=zipfile.ZIP_DEFLATED) as kmz_file:
        kmz_file.writestr("doc.kml", kml_text)

    return output_path


def export_geospatial_select_results(results: list[dict[str, str]], *, output_format: str, output_path: Path,
                                     backend_name: str = "backend") -> Path:
    """
    Export geospatial SELECT query results to a local file.

    Parameters
    ----------
    results : list[dict[str, str]]
        The SELECT query result bindings.
    output_format : str
        Export format ('geojson', 'kml', 'kmz', or 'gml').
    output_path : Path
        The output file path.
    backend_name : str, default="backend"
        Backend name used in error messages.

    Returns
    -------
    Path
        The path to the generated output file.

    Raises
    ------
    ValueError
        If the requested geospatial export format is not supported.
    """
    normalized_format = output_format.lower().lstrip(".")

    if normalized_format == "geojson":
        feature_collection = _build_geojson_feature_collection(results, backend_name=backend_name)
        output_path.write_text(json.dumps(feature_collection, indent=2, ensure_ascii=False), encoding="utf-8")
        return output_path

    if normalized_format == "kml":
        kml_text = _build_kml_document(results, backend_name=backend_name)
        output_path.write_text(kml_text, encoding="utf-8")
        return output_path

    if normalized_format == "kmz":
        kml_text = _build_kml_document(results, backend_name=backend_name)
        return _write_kmz_archive(kml_text, output_path)

    if normalized_format == "gml":
        gml_text = _build_gml_document(results, backend_name=backend_name)
        output_path.write_text(gml_text, encoding="utf-8")
        return output_path

    msg = f"[{backend_name}] Unsupported geospatial export format: {output_format}"
    raise ValueError(msg)
