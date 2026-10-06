import re

from backend.app.accessibility.models import Violation

WCAG_UNAVAILABLE = "WCAG mapping unavailable"

CRITERIA: dict[str, str] = {
    "1.1.1": "Non-text Content",
    "1.3.1": "Info and Relationships",
    "1.4.3": "Contrast (Minimum)",
    "1.4.10": "Reflow",
    "2.1.1": "Keyboard",
    "2.4.4": "Link Purpose (In Context)",
    "2.4.6": "Headings and Labels",
    "2.4.11": "Focus Not Obscured (Minimum)",
    "2.5.8": "Target Size (Minimum)",
    "3.3.2": "Labels or Instructions",
    "4.1.1": "Parsing",
    "4.1.2": "Name, Role, Value",
}

RULE_CATEGORIES: dict[str, str] = {
    "image-alt": "Images without alternative text",
    "button-name": "Buttons without accessible names",
    "label": "Form controls without labels",
    "link-name": "Links without discernible names",
    "heading-order": "Heading and document structure",
    "empty-heading": "Heading and document structure",
    "page-has-heading-one": "Heading and document structure",
    "landmark-one-main": "Landmark structure",
    "region": "Landmark structure",
    "color-contrast": "Color contrast",
    "keyboard": "Keyboard accessibility",
    "accesskeys": "Keyboard accessibility",
    "aria-hidden-focus": "Keyboard accessibility",
    "focus-order-semantics": "Keyboard accessibility",
    "tabindex": "Keyboard accessibility",
    "duplicate-id": "Duplicate or invalid IDs",
    "duplicate-id-active": "Duplicate or invalid IDs",
    "duplicate-id-aria": "Duplicate or invalid IDs",
}

RULE_EXPLANATIONS: dict[str, str] = {
    "image-alt": "People using screen readers need text alternatives to understand the information conveyed by images.",
    "button-name": "Assistive technology needs an accessible name to announce a button's purpose.",
    "label": "A programmatic label lets assistive technology identify a form control and helps users understand what to enter.",
    "link-name": "A discernible link name lets users understand a link's purpose, including when navigating by links out of context.",
    "heading-order": "A logical heading hierarchy helps users navigate and understand the page's structure.",
    "empty-heading": "A heading without text does not clearly communicate the structure or topic of its section.",
    "page-has-heading-one": "A primary heading can help users identify the page's main topic and navigate its structure.",
    "landmark-one-main": "A main landmark gives assistive technology users a direct way to find the page's primary content.",
    "region": "Landmarks provide navigable structure so assistive technology users can move between major areas of a page.",
    "color-contrast": "Insufficient text contrast can make content difficult to read for people with low vision or color-vision deficiencies.",
    "keyboard": "Users must be able to operate the affected functionality without a mouse.",
    "accesskeys": "Conflicting access keys can interfere with keyboard commands and assistive technology shortcuts.",
    "aria-hidden-focus": "Keyboard-focusable content must not be hidden from assistive technology users.",
    "focus-order-semantics": "Keyboard focus should follow an order that preserves the meaning and operation of the page.",
    "tabindex": "Positive tabindex values can create a confusing focus order for keyboard users.",
    "duplicate-id": "Unique IDs are needed for reliable references between page elements and assistive technology relationships.",
    "duplicate-id-active": "Unique IDs are needed for reliable references between page elements and assistive technology relationships.",
    "duplicate-id-aria": "Unique IDs are needed for reliable references between page elements and assistive technology relationships.",
}

RULE_WCAG_FALLBACKS: dict[str, str] = {
    "image-alt": "1.1.1",
    "button-name": "4.1.2",
    "link-name": "2.4.4",
    "heading-order": "1.3.1",
    "color-contrast": "1.4.3",
}


def _criteria_from_tags(tags: list[str]) -> list[str]:
    criteria: list[str] = []
    for tag in tags:
        match = re.fullmatch(r"wcag(\d)(\d)(\d{1,2})", tag.lower())
        if match:
            criterion = ".".join(match.groups())
            if criterion not in criteria:
                criteria.append(criterion)
    return criteria


def _level_from_tags(tags: list[str]) -> str:
    for tag in tags:
        match = re.fullmatch(r"wcag\d+(aaa|aa|a)", tag.lower())
        if match:
            return match.group(1).upper()
    return WCAG_UNAVAILABLE


def normalize_violation(violation: Violation) -> Violation:
    rule_id = violation.rule_id or violation.id
    criteria = _criteria_from_tags(violation.wcag_tags)
    criterion_code = (
        criteria[0] if criteria else RULE_WCAG_FALLBACKS.get(rule_id)
    )
    criterion = (
        f"{criterion_code} {CRITERIA[criterion_code]}"
        if criterion_code in CRITERIA
        else criterion_code or WCAG_UNAVAILABLE
    )
    selectors = list(
        dict.fromkeys(
            selector
            for node in violation.affected_nodes
            for selector in node.selectors
        )
    )
    elements = [
        node.html for node in violation.affected_nodes if node.html
    ]
    explanation = RULE_EXPLANATIONS.get(rule_id)
    if explanation is None:
        explanation = next(
            (
                node.failure_summary
                for node in violation.affected_nodes
                if node.failure_summary
            ),
            violation.description,
        )

    return violation.model_copy(
        update={
            "rule_id": rule_id,
            "wcag_criterion": criterion,
            "wcag_level": _level_from_tags(violation.wcag_tags),
            "category": RULE_CATEGORIES.get(rule_id, "Other axe-core finding"),
            "explanation": explanation,
            "affected_html_selectors": list(
                dict.fromkeys(violation.affected_html_selectors + selectors)
            ),
            "affected_html_elements": elements,
            "css_selectors": selectors,
            "affected_node_count": len(violation.affected_nodes),
        }
    )
