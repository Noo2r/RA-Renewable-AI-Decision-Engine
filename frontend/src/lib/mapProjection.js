// Simplified visualization projection for the RA Egypt demo map.
//
// This is NOT a GIS-grade projection -- there is no ellipsoid model, no
// equirectangular/Mercator correction, no coordinate reference system.
// It is a single linear rescale of longitude -> x and latitude -> y across
// a fixed demo bounding box, good enough for placing three station markers
// on a stylized outline. Do not reuse this for anything requiring
// real-world positional accuracy.

export const MAP_BOUNDS = {
  minLon: 25.0,
  maxLon: 35.9,
  minLat: 22.0,
  maxLat: 31.8,
};

export const MAP_VIEWBOX = { width: 400, height: 400 };

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

// longitude -> SVG x, latitude -> SVG y. SVG y increases downward while
// latitude increases northward/upward, so the y axis is flipped. Points
// outside MAP_BOUNDS are clamped to the nearest edge rather than drawn
// off-canvas.
export function projectToSvg(latitude, longitude) {
  const { minLon, maxLon, minLat, maxLat } = MAP_BOUNDS;
  const { width, height } = MAP_VIEWBOX;

  const lon = clamp(longitude, minLon, maxLon);
  const lat = clamp(latitude, minLat, maxLat);

  const x = ((lon - minLon) / (maxLon - minLon)) * width;
  const y = ((maxLat - lat) / (maxLat - minLat)) * height;

  return { x, y };
}
