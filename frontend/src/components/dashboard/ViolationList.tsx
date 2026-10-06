import type { ApplicationViolation } from "../../types/api";

export default function ViolationList({
  title,
  violations,
}: {
  title: string;
  violations: ApplicationViolation[];
}) {
  return (
    <section className="dashboard-violation-list">
      <h4>{title}<span>{violations.length}</span></h4>
      {violations.length === 0 ? (
        <p className="dashboard-list-empty">None recorded.</p>
      ) : (
        <ul>
          {violations.map((violation, index) => (
            <li key={`${violation.rule_id}-${index}`}>
              <div className="dashboard-violation-heading">
                <strong>{violation.rule_id}</strong>
                <span className={`impact-badge ${(violation.impact ?? "unknown").toLowerCase()}`}>
                  {violation.impact ?? "impact unavailable"}
                </span>
              </div>
              <p>{violation.description}</p>
              <span className="dashboard-wcag">{violation.wcag_criterion}</span>
              {violation.affected_elements.map((element, elementIndex) => (
                <code className="dashboard-selector" key={`${element.selector}-${elementIndex}`}>
                  {element.selector || "Selector unavailable"}
                </code>
              ))}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
