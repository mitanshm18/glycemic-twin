import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ClinicalRecord } from "@/features/record/ClinicalRecord";

export const metadata: Metadata = { title: "Clinical record" };

export default async function RecordPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const pid = Number(id);
  if (!Number.isInteger(pid) || pid <= 0) notFound();
  return <ClinicalRecord patientId={pid} />;
}
