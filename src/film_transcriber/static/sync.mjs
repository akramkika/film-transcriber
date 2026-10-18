/** All transcript positions are relative to the extracted scene, not the source file. */
export function activeSegmentIndex(segments, videoTime, sceneStart, sceneDuration = Infinity) {
  // Avoid subtraction noise at a shared boundary, e.g. 13.2 - 10 < 3.2.
  const time = Math.round((videoTime - sceneStart) * 1e6) / 1e6;
  if (!Number.isFinite(time) || time < 0 || time >= sceneDuration || segments.length === 0) return -1;
  let low = 0;
  let high = segments.length - 1;
  while (low <= high) {
    const middle = Math.floor((low + high) / 2);
    if (segments[middle].start <= time) low = middle + 1;
    else high = middle - 1;
  }
  return high >= 0 && time < segments[high].end ? high : -1;
}

export function sourceTimeForSegment(segment, sceneStart) {
  return segment.start + sceneStart;
}

export function formatTime(seconds, showFraction = false) {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  const millis = Math.round(seconds * 1000);
  const hours = Math.floor(millis / 3600000);
  const minutes = Math.floor(millis / 60000) % 60;
  const wholeSeconds = Math.floor(millis / 1000) % 60;
  const base = [minutes, wholeSeconds].map((value) => String(value).padStart(2, "0")).join(":");
  const clock = hours > 0 ? `${String(hours).padStart(2, "0")}:${base}` : base;
  return showFraction ? `${clock},${String(millis % 1000).padStart(3, "0")}` : clock;
}

/** Return a scroll position inside the text pane; never scroll the document. */
export function followScrollPosition(rowTop, rowBottom, scrollTop, paneHeight, padding = 24) {
  const viewportTop = scrollTop + padding;
  const viewportBottom = scrollTop + paneHeight - padding;
  if (rowTop >= viewportTop && rowBottom <= viewportBottom) return null;
  return Math.max(0, rowTop - Math.max(padding, (paneHeight - (rowBottom - rowTop)) / 2));
}
