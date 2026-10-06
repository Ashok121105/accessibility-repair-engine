from backend.app.accessibility.models import AffectedNode, Violation
from backend.app.accessibility.wcag import normalize_violation


def test_normalize_known_axe_rule_with_wcag_tags() -> None:
    normalized = normalize_violation(
        Violation(
            id="button-name",
            impact="serious",
            tags=["wcag2a", "wcag412", "cat.name-role-value"],
            wcag_tags=["wcag2a", "wcag412"],
            description="Buttons must have discernible text",
            help="Add a text label to the button",
            help_url="https://dequeuniversity.com/rules/axe/button-name",
            affected_nodes=[
                AffectedNode(
                    selectors=["button.icon-only"],
                    html='<button class="icon-only"></button>',
                    failure_summary="Add an accessible name.",
                )
            ],
        )
    )

    assert normalized.rule_id == "button-name"
    assert normalized.wcag_criterion == "4.1.2 Name, Role, Value"
    assert normalized.wcag_level == "A"
    assert normalized.category == "Buttons without accessible names"
    assert normalized.explanation.startswith("Assistive technology needs")
    assert normalized.affected_node_count == 1
    assert normalized.affected_html_elements == ['<button class="icon-only"></button>']
    assert normalized.css_selectors == ["button.icon-only"]
    assert normalized.help_url == "https://dequeuniversity.com/rules/axe/button-name"


def test_normalize_unknown_rule_does_not_invent_wcag_mapping() -> None:
    normalized = normalize_violation(
        Violation(
            id="project-specific-rule",
            impact="minor",
            description="A project-specific issue was detected",
            help="Review the affected element",
            affected_nodes=[
                AffectedNode(
                    selectors=[".custom"],
                    html='<div class="custom"></div>',
                    failure_summary="Correct the project-specific issue.",
                )
            ],
        )
    )

    assert normalized.wcag_criterion == "WCAG mapping unavailable"
    assert normalized.wcag_level == "WCAG mapping unavailable"
    assert normalized.explanation == "Correct the project-specific issue."
    assert normalized.category == "Other axe-core finding"


def test_known_rule_fallback_maps_criterion_but_does_not_guess_level() -> None:
    normalized = normalize_violation(
        Violation(
            id="color-contrast",
            impact="serious",
            description="Elements must have sufficient color contrast",
            help="Increase the contrast",
        )
    )

    assert normalized.wcag_criterion == "1.4.3 Contrast (Minimum)"
    assert normalized.wcag_level == "WCAG mapping unavailable"


def test_normalize_supports_wcag_criteria_with_two_digit_final_component() -> None:
    normalized = normalize_violation(
        Violation(
            id="reflow-rule",
            impact="serious",
            wcag_tags=["wcag21aa", "wcag1410"],
            description="Content must reflow",
            help="Ensure content reflows",
        )
    )

    assert normalized.wcag_criterion == "1.4.10 Reflow"
    assert normalized.wcag_level == "AA"


def test_landmark_violation_gets_explanation_without_inferred_criterion() -> None:
    normalized = normalize_violation(
        Violation(
            id="landmark-one-main",
            impact="moderate",
            description="Ensures the document has a main landmark",
            help="Add a main landmark",
        )
    )

    assert normalized.category == "Landmark structure"
    assert normalized.wcag_criterion == "WCAG mapping unavailable"
    assert "direct way to find the page's primary content" in normalized.explanation
