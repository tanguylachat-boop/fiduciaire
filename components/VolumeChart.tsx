"use client";

import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

export function VolumeChart({
  data,
}: {
  data: { date: string; volume: number }[];
}) {
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 10, right: 10, bottom: 0, left: -10 }}>
          <defs>
            <linearGradient id="fillVolume" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#3B82F6" stopOpacity={0.35} />
              <stop offset="100%" stopColor="#3B82F6" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#1F2230" vertical={false} />
          <XAxis
            dataKey="date"
            stroke="#5A5F6E"
            tick={{ fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            stroke="#5A5F6E"
            tick={{ fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            width={30}
          />
          <Tooltip
            contentStyle={{
              background: "#16181F",
              border: "1px solid #2A2E40",
              borderRadius: 8,
              fontSize: 12,
            }}
            labelStyle={{ color: "#E8EAF0" }}
            cursor={{ stroke: "#3B82F6", strokeOpacity: 0.3 }}
          />
          <Area
            type="monotone"
            dataKey="volume"
            stroke="#3B82F6"
            strokeWidth={2}
            fill="url(#fillVolume)"
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
