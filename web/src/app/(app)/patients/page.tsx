import type { Metadata } from "next";
import { PatientList } from "@/features/patients/PatientList";

export const metadata: Metadata = { title: "Patients" };

export default function PatientsPage() {
  return <PatientList />;
}
