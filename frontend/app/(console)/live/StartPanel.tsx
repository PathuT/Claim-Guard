"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import {
  ApiError,
  type NewClaimFields,
  type PolicyRef,
  type SamplePack,
  getPolicy,
  listHospitals,
  listSamplePacks,
  samplePdfUrl,
} from "@/lib/api";
import { DEMO_SCENARIOS } from "@/lib/demoScenarios";
import { formatInr } from "@/lib/format";

type Mode = "samples" | "upload" | "replay";

const PERSONAS = [
  { label: "Priya Raman", policy: "KHA-SIL-004512" },
  { label: "Rahul Verma", policy: "KHA-SIL-007731" },
];

const input = "rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary";

export function StartPanel({
  disabled,
  onSamplePack,
  onUpload,
  onReplay,
}: {
  disabled: boolean;
  onSamplePack: (pack: SamplePack) => void;
  onUpload: (fields: NewClaimFields) => void;
  onReplay: (claimId: string, label: string) => void;
}) {
  const [mode, setMode] = useState<Mode>("samples");
  const tabs: { id: Mode; label: string }[] = [
    { id: "samples", label: "Sample documents" },
    { id: "upload", label: "Upload your own PDFs" },
    { id: "replay", label: "Replay a seeded scenario" },
  ];

  return (
    <section className="rounded-xl border border-border bg-card shadow-sm p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold text-card-foreground">Start a claim</h2>
        <div className="flex flex-wrap gap-1 rounded-md bg-secondary p-1">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setMode(tab.id)}
              className={`rounded px-3 py-1 text-xs font-medium transition-colors ${
                mode === tab.id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>
      <div className="mt-4">
        {mode === "samples" && <SamplePacks disabled={disabled} onPick={onSamplePack} />}
        {mode === "upload" && <UploadForm disabled={disabled} onSubmit={onUpload} />}
        {mode === "replay" && <Replay disabled={disabled} onPick={onReplay} />}
      </div>
    </section>
  );
}

function SamplePacks({ disabled, onPick }: { disabled: boolean; onPick: (pack: SamplePack) => void }) {
  const { data: packs, error } = useSWR("sample-packs", listSamplePacks);
  if (error) return <p className="text-sm text-destructive">{error instanceof ApiError ? error.message : "Could not load sample packs."}</p>;
  if (!packs) return <p className="text-sm text-muted-foreground">Loading sample documents…</p>;

  return (
    <div className="grid gap-3 md:grid-cols-3">
      {packs.map((pack) => (
        <div
          key={pack.pack_id}
          className={`flex flex-col gap-2 rounded-md border p-4 ${pack.poisoned ? "border-destructive/40 bg-destructive/5" : "border-border bg-secondary"}`}
        >
          <div className="flex items-start justify-between gap-2">
            <span className="font-medium text-card-foreground">{pack.title}</span>
            {pack.poisoned && <span className="shrink-0 rounded-full bg-destructive/10 px-2 py-0.5 text-[10px] font-semibold text-destructive">ATTACK</span>}
          </div>
          <span className="text-xs text-muted-foreground">{pack.persona}</span>
          <p className="text-sm text-card-foreground">{pack.summary}</p>
          <p className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">Expected: </span>
            {pack.expected}
          </p>
          <p className="text-xs tabular-nums text-muted-foreground">Claimed {formatInr(pack.claimed_amount)} · {pack.admission_date} → {pack.discharge_date}</p>
          <div className="mt-auto flex flex-wrap items-center gap-3 pt-2">
            <button
              type="button"
              disabled={disabled}
              onClick={() => onPick(pack)}
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
            >
              Upload &amp; run
            </button>
            <a href={samplePdfUrl(pack.pack_id, "final_bill")} target="_blank" rel="noopener noreferrer" className="text-xs text-muted-foreground underline hover:text-foreground">
              bill.pdf
            </a>
            <a href={samplePdfUrl(pack.pack_id, "discharge_summary")} target="_blank" rel="noopener noreferrer" className="text-xs text-muted-foreground underline hover:text-foreground">
              discharge.pdf
            </a>
          </div>
        </div>
      ))}
    </div>
  );
}

export function UploadForm({ disabled, onSubmit }: { disabled: boolean; onSubmit: (fields: NewClaimFields) => void }) {
  const { data: hospitals } = useSWR("reference-hospitals", listHospitals);
  const [policyNumber, setPolicyNumber] = useState("");
  const [policy, setPolicy] = useState<PolicyRef | null>(null);
  const [policyError, setPolicyError] = useState<string | null>(null);
  const [memberId, setMemberId] = useState("");
  const [hospitalId, setHospitalId] = useState("");
  const [admissionDate, setAdmissionDate] = useState("");
  const [dischargeDate, setDischargeDate] = useState("");
  const [statedIllness, setStatedIllness] = useState("");
  const [claimedAmount, setClaimedAmount] = useState("");
  const [finalBill, setFinalBill] = useState<File | null>(null);
  const [dischargeSummary, setDischargeSummary] = useState<File | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    const trimmed = policyNumber.trim();
    if (trimmed.length < 8) return;
    let cancelled = false;
    getPolicy(trimmed)
      .then((p) => {
        if (cancelled) return;
        setPolicy(p);
        setPolicyError(null);
        setMemberId(p.members[0]?.member_id ?? "");
      })
      .catch((err) => {
        if (cancelled) return;
        setPolicy(null);
        setPolicyError(err instanceof ApiError ? err.message : "Policy lookup failed.");
      });
    return () => {
      cancelled = true;
    };
  }, [policyNumber]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!policy || !memberId || !hospitalId) {
      setFormError("Pick a valid policy, member and hospital.");
      return;
    }
    if (!finalBill || !dischargeSummary) {
      setFormError("Attach both the final bill and the discharge summary PDFs.");
      return;
    }
    setFormError(null);
    onSubmit({
      policyNumber: policy.policy_number,
      memberId,
      hospitalId,
      admissionDate,
      dischargeDate,
      statedIllness: statedIllness.trim(),
      claimedAmount: Number(claimedAmount),
      finalBill,
      dischargeSummary,
    });
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <div className="grid gap-3 md:grid-cols-3">
        <label className="flex flex-col gap-1 text-sm">
          Policy number
          <input value={policyNumber} onChange={(e) => setPolicyNumber(e.target.value)} placeholder="KHA-SIL-004512" required className={input} />
          <span className="flex gap-2 text-xs">
            {PERSONAS.map((p) => (
              <button key={p.policy} type="button" onClick={() => setPolicyNumber(p.policy)} className="text-muted-foreground underline hover:text-foreground">
                {p.label}
              </button>
            ))}
          </span>
          {policy && (
            <span className="text-xs text-success">
              {policy.holder_name} · {policy.plan} · sum insured {formatInr(policy.sum_insured)} · since {policy.start_date}
            </span>
          )}
          {policyError && <span className="text-xs text-destructive">{policyError}</span>}
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Member
          <select value={memberId} onChange={(e) => setMemberId(e.target.value)} disabled={!policy} required className={input}>
            {!policy && <option value="">Enter a policy first</option>}
            {policy?.members.map((m) => (
              <option key={m.member_id} value={m.member_id}>
                {m.name} ({m.relationship_to_holder}, {m.age})
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Hospital
          <select value={hospitalId} onChange={(e) => setHospitalId(e.target.value)} required className={input}>
            <option value="">Select a hospital…</option>
            {hospitals?.map((h) => (
              <option key={h.hospital_id} value={h.hospital_id}>
                {h.name} — {h.city}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Admission date
          <input type="date" value={admissionDate} onChange={(e) => setAdmissionDate(e.target.value)} required className={input} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Discharge date
          <input type="date" value={dischargeDate} onChange={(e) => setDischargeDate(e.target.value)} required className={input} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Claimed amount (₹)
          <input type="number" min={1} value={claimedAmount} onChange={(e) => setClaimedAmount(e.target.value)} required className={`${input} tabular-nums`} />
        </label>
      </div>
      <label className="flex flex-col gap-1 text-sm">
        Stated illness
        <input value={statedIllness} onChange={(e) => setStatedIllness(e.target.value)} placeholder="e.g. Dengue fever" required className={input} />
      </label>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          Final bill (PDF)
          <input type="file" accept="application/pdf" onChange={(e) => setFinalBill(e.target.files?.[0] ?? null)} required className={`${input} text-xs`} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Discharge summary (PDF)
          <input type="file" accept="application/pdf" onChange={(e) => setDischargeSummary(e.target.files?.[0] ?? null)} required className={`${input} text-xs`} />
        </label>
      </div>
      {formError && <p className="text-sm text-destructive">{formError}</p>}
      <button
        type="submit"
        disabled={disabled}
        className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
      >
        Upload &amp; run
      </button>
    </form>
  );
}

function Replay({ disabled, onPick }: { disabled: boolean; onPick: (claimId: string, label: string) => void }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted-foreground">
        Re-runs an already-seeded S01–S10 claim through the same live pipeline (no upload step) — useful for showing a
        specific behaviour such as a duplicate bill or a missing document.
      </p>
      <div className="grid gap-2 md:grid-cols-2">
        {DEMO_SCENARIOS.map((s) => (
          <button
            key={s.id}
            type="button"
            disabled={disabled}
            onClick={() => onPick(s.claimId, s.label)}
            className="flex flex-col items-start gap-0.5 rounded-md border border-border bg-secondary px-3 py-2 text-left transition-colors hover:border-primary/40 hover:bg-card disabled:opacity-50"
          >
            <span className="text-sm font-medium text-card-foreground">{s.label}</span>
            <span className="text-xs text-muted-foreground">{s.description}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
