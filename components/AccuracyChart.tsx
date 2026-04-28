"use client";

import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  Legend,
} from "recharts";

export function AccuracyChart({
  data,
}: {
  data: { day: string; triage: number; extraction: number; relance: number }[];
}) {
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 10, right: 10, bottom: 0, left: -10 }}>
          <CartesianGrid stroke="#1F2230" vertical={false} />
          <XAxis
            dataKey="day"
            stroke="#5A5F6E"
            tick={{ fontSize: 10 }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            stroke="#5A5F6E"
            tick={{ fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            width={35}
            domain={[70, 100]}
          />
          <Tooltip
            contentStyle={{
              background: "#16181F",
              border: "1px solid #2A2E40",
              borderRadius: 8,
              fontSize: 12,
            }}
            labelStyle={{ color: "#E8EAF0" }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Line type="monotone" dataKey="triage" stroke="#3B82F6" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="extraction" stroke="#A855F7" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="relance" stroke="#F59E0B" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
