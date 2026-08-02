// Loads the locally bundled Egypt boundary GeoJSON and exposes its parsed,
// sanitized polygon geometry once, memoized.
//
// Imported with Vite's `?raw` suffix, which inlines the file's full text
// into the JS bundle at BUILD time -- there is no `fetch()`/XHR involved
// and no request to any host at runtime, local or remote.
//
// Source data note (carried in the bundled file's own `properties`):
// iso3 "EGY", source_layer "egy_admin0", source_format "Esri File
// Geodatabase", usage_note: "Simplified for offline frontend SVG
// rendering; approximate display only."
import egyptBoundaryRaw from "../assets/egypt-boundary.geojson?raw";
import { extractEgyptGeometry, normalizeToPolygons } from "./mapProjection";

let cached = null;

// Returns { polygons, error }. polygons is a (possibly empty)
// polygons[][rings][points] structure; error is a short human-readable
// string when the bundled file could not be parsed into usable geometry,
// or null on success. Never throws.
export function getEgyptPolygons() {
  if (cached) return cached;

  try {
    const geojson = JSON.parse(egyptBoundaryRaw);
    const geometry = extractEgyptGeometry(geojson);
    const polygons = normalizeToPolygons(geometry);
    cached = polygons.length > 0
      ? { polygons, error: null }
      : { polygons: [], error: "Egypt boundary geometry is empty or an unsupported type." };
  } catch (e) {
    cached = { polygons: [], error: "Could not parse the local Egypt boundary file." };
  }
  return cached;
}
