import type { Metadata } from "next";
import { ModelOverview } from "@/features/model/ModelOverview";

export const metadata: Metadata = { title: "Model" };

export default function ModelPage() {
  return <ModelOverview />;
}
