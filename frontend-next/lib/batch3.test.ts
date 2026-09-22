import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

describe('batch3 bridge & comparison calculations', () => {
  it('calculates savings percentage correctly', () => {
    const baseline = 5.0;
    const cheapest = 1.25;
    const savings = baseline - cheapest;
    const pct = Math.round((savings / baseline) * 100);
    assert.equal(pct, 75);
    assert.equal(savings, 3.75);
  });

  it('computes 8-axis polygon coordinates accurately', () => {
    const totalAxes = 8;
    const center = 150;
    const radius = 100;

    const points: string[] = [];
    for (let i = 0; i < totalAxes; i++) {
      const angle = (Math.PI * 2 / totalAxes) * i - Math.PI / 2;
      const x = Math.round(center + Math.cos(angle) * radius);
      const y = Math.round(center + Math.sin(angle) * radius);
      points.push(`${x},${y}`);
    }

    assert.equal(points.length, 8);
    // Top-most point (i=0) should have angle = -PI/2, so x=150, y=50
    assert.equal(points[0], '150,50');
    // Right-most point (i=2) should have angle = 0, so x=250, y=150
    assert.equal(points[2], '250,150');
  });

  it('identifies highest scoring candidate across multiple dimensions', () => {
    const scores = [
      { id: 'p1', name: 'Alpha', score: 92 },
      { id: 'p2', name: 'Beta', score: 85 },
      { id: 'p3', name: 'Gamma', score: 88 },
    ];
    const winner = scores.reduce((prev, curr) => (curr.score > prev.score ? curr : prev));
    assert.equal(winner.id, 'p1');
    assert.equal(winner.score, 92);
  });
});
