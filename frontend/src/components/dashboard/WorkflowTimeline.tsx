import { Check, Circle, Clock3 } from "lucide-react";

import type { DashboardWorkflowStep } from "../../types/api";

export default function WorkflowTimeline({
  steps,
}: {
  steps: DashboardWorkflowStep[];
}) {
  return (
    <section className="dashboard-panel-card" aria-label="Repair workflow timeline">
      <div className="dashboard-card-kicker">EVIDENCE PIPELINE</div>
      <ol className="dashboard-timeline">
        {steps.map((step) => (
          <li className={`timeline-${step.status.toLowerCase().replace(/ /g, "-")}`} key={step.name}>
            <span className="timeline-icon" aria-hidden="true">
              {step.status === "Completed" ? <Check size={14} /> : step.status === "Active" ? <Clock3 size={14} /> : <Circle size={12} />}
            </span>
            <strong>{step.name}</strong>
            <span className="timeline-status">{step.status}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
