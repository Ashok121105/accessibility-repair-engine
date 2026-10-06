import type { DashboardSummary } from "../../types/api";

export default function RepairProgress({ summary }: { summary: DashboardSummary }) {
  const ratio =
    summary.repair.success_proposed > 0
      ? `${summary.repair.success_verified} verified / ${summary.repair.success_proposed} proposed`
      : "Unavailable until a real proposal is recorded";
  return (
    <section className="dashboard-panel-card repair-progress" aria-label="Repair summary">
      <div className="dashboard-card-kicker">REPAIR SUMMARY</div>
      <h3>Progress backed by recorded operations</h3>
      <div className="repair-progress-metrics">
        <div><strong>{summary.repair.proposed}</strong><span>Repairs proposed</span></div>
        <div><strong>{summary.repair.verified}</strong><span>Repairs verified</span></div>
        <div><strong>{summary.repair.applied}</strong><span>Repairs applied to copy</span></div>
        <div><strong>{summary.repair.regressions_detected}</strong><span>Regressions detected</span></div>
      </div>
      <p><b>Repair success:</b> {ratio}</p>
    </section>
  );
}
