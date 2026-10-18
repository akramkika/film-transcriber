import test from "node:test";
import assert from "node:assert/strict";
import { activeSegmentIndex, sourceTimeForSegment, formatTime, followScrollPosition } from "../../src/film_transcriber/static/sync.mjs";

const segments = [
  { start: 0.5, end: 2, text: "Premier dialogue" },
  { start: 2, end: 3.2, text: "Deuxième dialogue" },
  { start: 5, end: 6, text: "Après le silence" },
];

test("scene offset, exact starts and exclusive ends follow source time", () => {
  assert.equal(activeSegmentIndex(segments, 10.5, 10, 8), 0);
  assert.equal(activeSegmentIndex(segments, 12, 10, 8), 1);
  assert.equal(activeSegmentIndex(segments, 13.2, 10, 8), -1);
  assert.equal(activeSegmentIndex(segments, 15, 10, 8), 2);
  assert.equal(activeSegmentIndex(segments, 16, 10, 8), -1);
});

test("silence, out of scene, invalid positions and empty transcripts never highlight", () => {
  for (const position of [0, 10, 14, 18, 30, NaN, Infinity]) {
    assert.equal(activeSegmentIndex(segments, position, 10, 8), -1);
  }
  assert.equal(activeSegmentIndex([], 10.5, 10, 8), -1);
  assert.equal(activeSegmentIndex([{ start: 0, end: 20 }], 18, 10, 8), -1);
});

test("pause, seek backwards and faster playback use current position without a text timer", () => {
  assert.deepEqual([10.6, 10.6, 15.5, 11, 12.1, 14].map((time) => activeSegmentIndex(segments, time, 10, 8)), [0, 0, 2, 0, 1, -1]);
});

test("timestamp navigation adds the original scene offset", () => {
  assert.equal(sourceTimeForSegment(segments[2], 74.25), 79.25);
  assert.equal(sourceTimeForSegment(segments[0], 0), 0.5);
});

test("timestamps handle subsecond precision and minute/hour rollover", () => {
  assert.equal(formatTime(0), "00:00");
  assert.equal(formatTime(59.9996, true), "01:00,000");
  assert.equal(formatTime(3601.025, true), "01:00:01,025");
  assert.equal(formatTime(-1), "—");
  assert.equal(formatTime(Infinity), "—");
});

test("auto follow computes an inner-pane scroll only when the row leaves its viewport", () => {
  assert.equal(followScrollPosition(100, 150, 50, 300), null);
  assert.equal(followScrollPosition(0, 50, 200, 300), 0);
  assert.equal(followScrollPosition(400, 450, 0, 300), 275);
  assert.equal(followScrollPosition(400, 900, 0, 300), 376);
});
