import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { TwinWorkspace } from "@/features/twin/TwinWorkspace";

export const metadata: Metadata = { title: "Digital Twin" };

export default async function TwinPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const pid = Number(id);
  if (!Number.isInteger(pid) || pid <= 0) notFound();
  return <TwinWorkspace patientId={pid} />;
}
