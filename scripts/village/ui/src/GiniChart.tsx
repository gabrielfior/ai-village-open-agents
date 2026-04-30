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

  const pad = { top: 32, right: 24, bottom: 36, left: 56 };
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

  const yTicks = 5;
  const yLabels = Array.from({ length: yTicks + 1 }, (_, i) => (maxG * i) / yTicks);

  return (
    <div>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
        marginBottom: 10,
      }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: '#ccc' }}>
          Gini coefficient
        </span>
        <span style={{ fontSize: 11, color: '#555' }}>
          Epoch {points[0].epoch} – {points[points.length - 1].epoch}
        </span>
      </div>
      <svg width={width} height={height} style={{ display: 'block' }}>
        {/* background grid */}
        {yLabels.map((v, i) => (
          <g key={i}>
            <line
              x1={pad.left}
              y1={yScale(v)}
              x2={width - pad.right}
              y2={yScale(v)}
              stroke="#222"
              strokeWidth={1}
            />
            <text
              x={pad.left - 8}
              y={yScale(v) + 4}
              textAnchor="end"
              fill="#666"
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
            y={height - pad.bottom + 18}
            textAnchor="middle"
            fill="#666"
            fontSize={11}
          >
            Epoch {e}
          </text>
        ))}

        {/* axis lines */}
        <line x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} stroke="#444" strokeWidth={1} />
        <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} stroke="#444" strokeWidth={1} />

        {/* line */}
        <polyline
          points={line}
          fill="none"
          stroke="#4fc3f7"
          strokeWidth={2.5}
          strokeLinejoin="round"
        />

        {/* dots + value labels */}
        {points.map((p, i) => (
          <g key={i}>
            <circle
              cx={xScale(p.epoch)}
              cy={yScale(p.gini)}
              r={5}
              fill="#0d0d0d"
              stroke="#4fc3f7"
              strokeWidth={2}
            />
            <text
              x={xScale(p.epoch)}
              y={yScale(p.gini) - 12}
              textAnchor="middle"
              fill="#4fc3f7"
              fontSize={12}
              fontWeight={600}
            >
              {p.gini.toFixed(4)}
            </text>
          </g>
        ))}

        {/* min/max labels */}
        <text x={pad.left} y={height - pad.bottom + 4} fill="#555" fontSize={10} textAnchor="start">
          {minE}
        </text>
        <text x={width - pad.right} y={height - pad.bottom + 4} fill="#555" fontSize={10} textAnchor="end">
          {maxE}
        </text>
      </svg>
    </div>
  );
}
