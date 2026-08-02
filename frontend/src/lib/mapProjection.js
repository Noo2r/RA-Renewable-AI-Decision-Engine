// Geometry + coordinate-projection helpers for the RA Egypt demo map.
//
// This is NOT a GIS-grade projection -- there is no ellipsoid model, no
// proper equirectangular/Mercator correction, no coordinate reference
// system, no latitude-based longitude scaling. It is a single linear
// rescale of the *actual* Egypt GeoJSON bounding box onto an SVG viewBox,
// shared identically by the country outline, the decorative Nile path,
// and every station marker, so none of them can ever drift apart. Good
// enough for a demo overview map -- not for anything requiring real-world
// positional accuracy.

function isFiniteNumber(v) {
  return typeof v === "number" && Number.isFinite(v);
}

function isValidPoint(pt) {
  return Array.isArray(pt) && pt.length >= 2 && isFiniteNumber(pt[0]) && isFiniteNumber(pt[1]);
}

// Finds the Egypt feature in a GeoJSON document and returns its geometry
// ([longitude, latitude]-ordered, per the GeoJSON spec). Tolerant of a
// bare Geometry, a single Feature, or a FeatureCollection with one or
// more features (in which case the Egypt-like one is picked by iso3/iso2/
// name, falling back to the first feature).
export function extractEgyptGeometry(geojson) {
  if (!geojson || typeof geojson !== "object") return null;
  if (geojson.type === "FeatureCollection") {
    const features = Array.isArray(geojson.features) ? geojson.features : [];
    const named = features.find((f) => {
      const p = (f && f.properties) || {};
      return p.iso3 === "EGY" || p.iso2 === "EG" || /egypt/i.test(p.adm0_name || p.name || "");
    });
    const feature = named || features[0];
    return (feature && feature.geometry) || null;
  }
  if (geojson.type === "Feature") return geojson.geometry || null;
  if (geojson.type === "Polygon" || geojson.type === "MultiPolygon") return geojson;
  return null;
}

// Normalizes Polygon | MultiPolygon geometry into a flat
// polygons[][rings][points] structure ([lon, lat] pairs). Each polygon's
// first ring is its outer boundary; any further rings are holes -- both
// are preserved. Malformed rings/points are dropped rather than thrown.
export function normalizeToPolygons(geometry) {
  if (!geometry || !Array.isArray(geometry.coordinates)) return [];
  const rawPolygons =
    geometry.type === "Polygon" ? [geometry.coordinates]
    : geometry.type === "MultiPolygon" ? geometry.coordinates
    : [];

  const clean = [];
  for (const polygon of rawPolygons) {
    if (!Array.isArray(polygon)) continue;
    const cleanRings = [];
    for (const ring of polygon) {
      if (!Array.isArray(ring)) continue;
      const points = ring.filter(isValidPoint);
      if (points.length >= 3) cleanRings.push(points);
    }
    if (cleanRings.length > 0) clean.push(cleanRings);
  }
  return clean;
}

export function computeBounds(polygons) {
  let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
  for (const polygon of polygons || []) {
    for (const ring of polygon) {
      for (const [lon, lat] of ring) {
        if (lon < minLon) minLon = lon;
        if (lon > maxLon) maxLon = lon;
        if (lat < minLat) minLat = lat;
        if (lat > maxLat) maxLat = lat;
      }
    }
  }
  if (!Number.isFinite(minLon) || !Number.isFinite(maxLon) || !Number.isFinite(minLat) || !Number.isFinite(maxLat)) {
    return null;
  }
  return { minLon, maxLon, minLat, maxLat };
}

// Builds one shared lon/lat -> SVG-pixel projection, fit to `polygons`'
// own bounding box (plus `padding`) inside a width x height viewBox,
// preserving aspect ratio (one uniform scale for both axes -- the
// geometry is never stretched independently on x vs y) and centered in
// the available space. Returns null if `polygons` has no usable bounds.
export function createGeoProjection(polygons, width, height, padding = 16) {
  const bounds = computeBounds(polygons);
  if (!bounds) return null;

  const lonSpan = Math.max(bounds.maxLon - bounds.minLon, 1e-9);
  const latSpan = Math.max(bounds.maxLat - bounds.minLat, 1e-9);
  const availableW = Math.max(width - padding * 2, 1);
  const availableH = Math.max(height - padding * 2, 1);
  const scale = Math.min(availableW / lonSpan, availableH / latSpan);

  const drawnW = lonSpan * scale;
  const drawnH = latSpan * scale;
  const offsetX = padding + (availableW - drawnW) / 2;
  const offsetY = padding + (availableH - drawnH) / 2;

  function project(latitude, longitude) {
    if (!isFiniteNumber(latitude) || !isFiniteNumber(longitude)) return null;
    const lon = Math.min(bounds.maxLon, Math.max(bounds.minLon, longitude));
    const lat = Math.min(bounds.maxLat, Math.max(bounds.minLat, latitude));
    return {
      x: offsetX + (lon - bounds.minLon) * scale,
      y: offsetY + (bounds.maxLat - lat) * scale, // SVG y increases downward -- flip
    };
  }

  return { project, bounds };
}

// Converts already-normalized polygons[][rings][points] geometry into one
// SVG <path> `d` string using the "evenodd" fill rule -- each ring becomes
// its own M...Z subpath, so holes (a polygon's 2nd+ ring) render correctly
// without needing a separate <path> per polygon or a GIS library.
export function polygonsToPathD(polygons, project) {
  const subpaths = [];
  for (const polygon of polygons || []) {
    for (const ring of polygon) {
      const pts = ring.map(([lon, lat]) => project(lat, lon)).filter(Boolean);
      if (pts.length < 3) continue;
      const [first, ...rest] = pts;
      subpaths.push(
        `M ${first.x.toFixed(1)} ${first.y.toFixed(1)} ` +
        rest.map((p) => `L ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ") +
        " Z"
      );
    }
  }
  return subpaths.join(" ");
}
