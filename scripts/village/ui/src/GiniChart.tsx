import { GiniTimeseries } from './types';

interface Props {
  data: GiniTimeseries;
  width?: number;
  height?: number;
}

export default function GiniChart({ data, width = 600, height = 250 }: Props) {
  const points = data.gini_timeseries;
  if (points.length < 2) {
    return (
      <div style={{ color: '#888', fontSize: 14, padding: 20, textAlign: 'center' }}>
        Need at least 2 epochs for a chart
      </div>
    );
  }

  const pad = { top: 10, right: 10, bottom: 30, left: 50 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const epochs = points.map((p) => p.epoch);
  const minE = Math.min(...epochs);
  const maxE = Math.max(...epochs);
  const ginis = points.map((p) => p.gini);
  const maxG = Math.max(...ginis, 0.01);

  const xScale = (e: number) => pad.left + ((e - minE) / Math.max(1, maxE - minE)) * plotW;
  const yScale = (g: number) => pad.top + (1 - g / maxG) * plotH;

  const line = points.map((p) => `${xScale(p.epoch)},${yScale(p.gini)}`).join(' ');

  const yTicks = 4;
  const yLabels = Array.from({ length: yTicks + 1 }, (_, i) => (maxG * i) / yTicks);

  return (
    <div>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, color: '#ccc' }}>
        Gini coefficient
      </div>
      <svg width={width} height={height} style={{ background: '#0a0a0a', borderRadius: 6 }}>
        {/* grid lines */}
        {yLabels.map((v, i) => (
          <g key={i}>
            <line
              x1={pad.left}
              y1={yScale(v)}
              x2={width - pad.right}
              y2={yScale(v)}
              stroke="#333"
              strokeWidth={1}
            />
            <text
              x={pad.left - 6}
              y={yScale(v) + 4}
              textAnchor="end"
              fill="#888"
              fontSize={11}
            >
              {v.toFixed(3)}
            </text>
          </g>
        ))}

        {/* x-axis labels */}
        {epochs.map((e) => (
          <text
            key={e}
            x={xScale(e)}
            y={height - 6}
            textAnchor="middle"
            fill="#888"
            fontSize={11}
          >
            E{e}
          </text>
        ))}

        {/* line */}
        <polyline
          points={line}
          fill="none"
          stroke="#4fc3f7"
          strokeWidth={2}
          strokeLinejoin="round"
        />

        {/* dots */}
        {points.map((p, i) => (
          <circle
            key={i}
            cx={xScale(p.epoch)}
            cy={yScale(p.gini)}
            r={4}
            fill="#4fc3f7"
          />
        ))}

        {/* value labels */}
        {points.map((p, i) => (
          <text
            key={i}
            x={xScale(p.epoch)}
            y={yScale(p.gini) - 8}
            textAnchor="middle"
            fill="#4fc3f7"
            fontSize={11}
          >
            {p.gini.toFixed(4)}
          </text>
        ))}
      </svg>
    </div>
  );
}
